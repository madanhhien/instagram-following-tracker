#!/usr/bin/env python3
"""Instagram Following CLI - read-only snapshots and local history.

Uses the unofficial instagrapi client. No relationship mutations; no password storage.
All dates use Asia/Ho_Chi_Minh; a count mismatch never produces a confirmed follow delta.
"""
from __future__ import annotations

import csv
import getpass
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

APP = Path(__file__).resolve().parent
DATA = APP / 'data'
BACKUPS = DATA / 'backups'
DB_FILE = DATA / 'history.sqlite3'
SESSION = DATA / 'instagram_session.json'
CONFIG = DATA / 'config.json'
SEED = APP / 'seed_2026-11-01.json'
TZ = ZoneInfo('Asia/Ho_Chi_Minh')
USER_RE = re.compile(r'^[A-Za-z0-9._]{1,30}$')
DEFAULT_TARGET = 'yu_hjeiiun.n'
PAGE_SIZE = 100
MAX_PAGES = 250
_client = None
_client_username = ''


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def safe_text(s):
    # Prevent terminal-control characters in username/source logs.
    return ''.join(c for c in str(s) if c.isprintable()).strip()


def safe_error(err):
    # Do not persist Instagram response bodies, auth headers, codes, cookies or tokens.
    msg = safe_text(err)
    for pattern in (r'(?i)(sessionid|csrftoken|password|token|authorization|cookie)[=:\s]+[^\s,;]+',
                    r'(?i)bearer\s+[^\s,;]+'):
        msg = re.sub(pattern, '[REDACTED]', msg)
    return msg[:180]


def valid_username(s):
    return bool(USER_RE.fullmatch(str(s)))


def name(s):
    value = str(s).strip().lstrip('@').lower()
    if not valid_username(value):
        raise ValueError('Username không hợp lệ: ' + safe_text(value)[:40])
    return value


def dirs():
    for p in (DATA, BACKUPS):
        p.mkdir(parents=True, exist_ok=True)
        try: p.chmod(0o700)
        except OSError: pass


def protect(path):
    try: Path(path).chmod(0o600)
    except OSError: pass


def db():
    dirs()
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      account TEXT NOT NULL,
      target_pk TEXT,
      checked_at TEXT NOT NULL,
      expected_count INTEGER,
      found_count INTEGER NOT NULL,
      status TEXT NOT NULL,
      source TEXT NOT NULL,
      page_count INTEGER NOT NULL DEFAULT 0,
      note TEXT NOT NULL DEFAULT '',
      people_json TEXT NOT NULL,
      compared_to INTEGER,
      added_json TEXT NOT NULL DEFAULT '[]',
      removed_json TEXT NOT NULL DEFAULT '[]',
      renamed_json TEXT NOT NULL DEFAULT '[]',
      origin TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS ix_snapshots_account ON snapshots(account,checked_at,id);
    ''')
    conn.commit()
    protect(DB_FILE)
    return conn


@contextmanager
def con():
    connection = db()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def config():
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text('utf-8'))
            return {'target': name(cfg.get('target', DEFAULT_TARGET)),
                    'login': name(cfg['login']) if cfg.get('login') else ''}
        except (ValueError, KeyError, json.JSONDecodeError):
            pass
    return {'target': DEFAULT_TARGET, 'login': ''}


def save_config(cfg):
    dirs()
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    protect(CONFIG)


def sanitize_people(people):
    """Map from stable numeric IDs to usernames where possible."""
    output, seen = [], set()
    for item in people:
        if isinstance(item, str):
            pk, username = '', item
        else:
            pk, username = str(item.get('pk') or ''), str(item.get('username') or '')
        username = username.strip().lstrip('@').lower()
        if not valid_username(username):
            raise ValueError('API trả về username không hợp lệ: ' + safe_text(username)[:50])
        if pk and not pk.isdecimal():
            raise ValueError('API trả về ID không hợp lệ')
        key = 'pk:'+pk if pk else 'username:'+username
        if key not in seen:
            seen.add(key)
            output.append({'pk': pk, 'username': username})
    usernames = [x['username'] for x in output]
    if len(set(usernames)) != len(usernames):
        raise ValueError('Username bị trùng giữa các ID; không xác minh kết quả')
    return output


def get_rows(account=None):
    with con() as c:
        if account:
            return [dict(r) for r in c.execute('SELECT * FROM snapshots WHERE account=? ORDER BY checked_at,id',(account,))]
        return [dict(r) for r in c.execute('SELECT * FROM snapshots ORDER BY checked_at,id')]


def get_row(rowid):
    with con() as c:
        row = c.execute('SELECT * FROM snapshots WHERE id=?',(rowid,)).fetchone()
    return dict(row) if row else None


def people_of(row):
    return json.loads(row['people_json'])


def diff(old, new):
    """ID comparison only if both are complete sets with IDs; legacy uses names and stays unverified."""
    a, b = people_of(old), people_of(new)
    use_ids = bool(a and b and all(p['pk'] for p in a+b))
    if use_ids:
        ka = {p['pk']:p for p in a}
        kb = {p['pk']:p for p in b}
    else:
        ka = {p['username']:p for p in a}
        kb = {p['username']:p for p in b}
    added = sorted((kb[k]['username'] for k in kb.keys()-ka.keys()))
    removed = sorted((ka[k]['username'] for k in ka.keys()-kb.keys()))
    renamed = sorted([{'before':ka[k]['username'], 'after':kb[k]['username']}
                      for k in ka.keys() & kb.keys() if ka[k]['username']!=kb[k]['username']],
                     key=lambda r:r['before']) if use_ids else []
    verified = old['status']=='verified' and new['status']=='verified' and bool(use_ids) and (
        not old.get('target_pk') or not new.get('target_pk') or old.get('target_pk')==new.get('target_pk'))
    return {'added':added,'removed':removed,'renamed':renamed,'verified':verified,'by_id':use_ids}


def latest_verified(account, exclude=None):
    with con() as c:
        row = c.execute('''SELECT * FROM snapshots WHERE account=? AND status='verified' AND id!=? ORDER BY checked_at DESC,id DESC LIMIT 1''',
                        (account,exclude or -1)).fetchone()
    return dict(row) if row else None


def export_username_file(row, kind='txt', destination=None):
    """Human-readable exports from an EXISTING snapshot; never call Instagram."""
    kind = kind.lower()
    if kind not in ('txt', 'csv'):
        raise ValueError('Chỉ hỗ trợ TXT hoặc CSV')
    ts = re.sub(r'[^0-9]', '', row['checked_at'])[:14]
    target = row['account']
    output = Path(destination) if destination else BACKUPS / f'{ts}_{target}_check_{row["id"]}_following.{kind}'
    output.parent.mkdir(parents=True, exist_ok=True)
    people = people_of(row)
    if kind == 'txt':
        lines = [f'Danh sách Following ĐÃ THU ĐƯỢC của @{target}',
                 f'Lượt #{row["id"]} | Kiểm tra: {row["checked_at"]}',
                 f'Thu được: {row["found_count"]} | Instagram báo: {row["expected_count"]}',
                 f'Trạng thái: {status_label(row)}',
                 'THỨ TỰ DƯỚI ĐÂY LÀ THỨ TỰ API TRẢ VỀ, KHÔNG PHẢI THỨ TỰ FOLLOW THEO THỜI GIAN.',
                 'Nếu chưa đầy đủ, các username vắng mặt KHÔNG có nghĩa là đã unfollow.',
                 '-' * 74]
        lines.extend(f'{idx:>3}. @{item["username"]}'+
                     (f'  |  ID {item["pk"]}' if item['pk'] else '')
                     for idx, item in enumerate(people, 1))
        output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    else:
        with output.open('w', encoding='utf-8-sig', newline='') as fp:
            writer=csv.writer(fp)
            writer.writerow(['STT','Username','Instagram ID','Ngày kiểm tra','Trạng thái bản ghi'])
            writer.writerows((idx, item['username'], item['pk'], row['checked_at'], row['status'])
                             for idx, item in enumerate(people, 1))
    protect(output)
    return output


def create_backup(row):
    backup = {
        'version':1, 'account':row['account'], 'checked_at':row['checked_at'],
        'status':row['status'], 'source':row['source'], 'expected_count':row['expected_count'],
        'found_count':row['found_count'], 'pages':row['page_count'],
        'compared_to':row['compared_to'], 'new_follow_count':len(json.loads(row['added_json'])) if row['compared_to'] else None,
        'new_usernames':json.loads(row['added_json']),
        'unfollow_count':len(json.loads(row['removed_json'])) if row['compared_to'] else None,
        'unfollow_usernames':json.loads(row['removed_json']),
        'renamed':json.loads(row['renamed_json']),
        'note':row['note'], 'following':people_of(row),
        'caution':'new_usernames is confirmed only if status=verified and compared_to points to another verified snapshot.'
    }
    ts = re.sub(r'[^0-9]','',row['checked_at'])[:14]
    out = BACKUPS / f'{ts}_{row["account"]}_check_{row["id"]}.json'
    out.write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding='utf-8')
    protect(out)
    # Each snapshot also has a simple text file, readable without Python or JSON tooling.
    export_username_file(row,'txt')
    return out


def save_snapshot(account, target_pk='', expected=None, people=None, status='partial',
                  source='instagrapi', note='', pages=0, checked_at=None, origin=None):
    people = sanitize_people(people or [])
    if status=='verified':
        if expected is None or len(people)!=expected or (len(people)==0 and expected!=0):
            raise ValueError('Không thể đánh dấu đầy đủ: số lượng chưa khớp')
        if any(not p['pk'] for p in people):
            raise ValueError('Không thể đánh dấu đầy đủ: có user thiếu ID')
    checked_at = checked_at or now()
    with con() as c:
        if origin:
            existing=c.execute('SELECT id FROM snapshots WHERE origin=?',(origin,)).fetchone()
            if existing:return dict(c.execute('SELECT * FROM snapshots WHERE id=?',(existing[0],)).fetchone()),None
        prev = latest_verified(account) if status=='verified' else None
        # compare against previous verified snapshot only; partial/legacy snapshots cannot trigger false changes
        proto = {'status':status,'people_json':json.dumps(people),'target_pk':target_pk}
        change = diff(prev,proto) if prev else None
        if change and not change['verified']:
            # e.g. target changed unexpectedly; refuse automatic claims
            change=None
        cur = c.execute('''INSERT INTO snapshots
          (account,target_pk,checked_at,expected_count,found_count,status,source,page_count,note,people_json,compared_to,added_json,removed_json,renamed_json,origin)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            account,str(target_pk or ''),checked_at,expected,len(people),status,source,int(pages),
            safe_text(note)[:2000],json.dumps(people,ensure_ascii=False),
            prev['id'] if change else None,
            json.dumps(change['added'],ensure_ascii=False) if change else '[]',
            json.dumps(change['removed'],ensure_ascii=False) if change else '[]',
            json.dumps(change['renamed'],ensure_ascii=False) if change else '[]',origin))
        ident=cur.lastrowid
        c.commit()
        row=dict(c.execute('SELECT * FROM snapshots WHERE id=?',(ident,)).fetchone())
    backup=create_backup(row)
    return row,backup


def import_legacy(verbose=True):
    """Import existing tracker screenshots and partial checks without promoting them to trusted data."""
    old = Path.home()/'ig_tracker_ubuntu/data/tracker.sqlite3'
    seed_count=0
    if old.exists() and old.resolve()!=DB_FILE.resolve():
        try:
            uri = f'file:{old}?mode=ro'
            with sqlite3.connect(uri,uri=True) as conn:
                conn.row_factory=sqlite3.Row
                for r in conn.execute('SELECT * FROM snapshots ORDER BY checked_at,id'):
                    orig=f'old_app_{r["id"]}_{r["checked_at"]}'
                    try:
                        people=[{'pk':'','username':v} for v in json.loads(r['names_json'])]
                        _, created=save_snapshot(name(r['account']), expected=r['expected_count'],people=people,
                            checked_at=r['checked_at'],status='legacy',source='old_'+str(r['source']),
                            note='NHẬP TỪ APP CŨ, CHƯA XÁC MINH; '+str(r['notes'] or ''),origin=orig)
                        if created: seed_count+=1
                    except (ValueError,TypeError):continue
        except (sqlite3.Error,OSError) as exc:
            if verbose:print('Không đọc được dữ liệu app cũ:',safe_text(exc))
    # Add seed only if no screenshot baseline from old database
    with con() as conn:
        prior=conn.execute("SELECT 1 FROM snapshots WHERE account=? AND checked_at LIKE '2026-11-01%' AND source LIKE '%screenshots%' LIMIT 1",(DEFAULT_TARGET,)).fetchone()
    if not prior and SEED.exists():
        try:
            obj=json.loads(SEED.read_text('utf-8'))
            ss=obj['accounts'][DEFAULT_TARGET]['snapshots'][0]
            _, created=save_snapshot(DEFAULT_TARGET,expected=147,people=ss['names'],
                status='legacy',source='screenshots',checked_at='2026-11-01T10:16:00+07:00',
                note='Ảnh 01/11: 146/147, có thể sai ký tự username. Không kết luận follow mới từ mốc ảnh.',
                origin='seed_screenshots_2026-11-01')
            if created:seed_count+=1
        except (ValueError,KeyError,IndexError,json.JSONDecodeError) as exc:
            if verbose:print('Không nhập được mốc ảnh:',safe_text(exc))
    if verbose:print(f'Đã nhập {seed_count} bản ghi lịch sử cũ (chỉ tham khảo).')
    return seed_count


def login(force=False):
    global _client,_client_username
    if _client is not None and not force:return _client
    try:
        from instagrapi import Client
    except ImportError:
        raise RuntimeError('Thiếu thư viện instagrapi. Chạy ./run.sh sau khi cài đặt theo README.')
    cfg=config()
    login_user=cfg['login']
    if not login_user:
        login_user=name(input('Username Instagram CỦA BẠN (không phải người cần theo dõi): ').strip())
    cl=Client()
    if SESSION.exists():
        try:
            cl.load_settings(str(SESSION))
            # Validate old session with authenticated endpoint.
            info=cl.account_info()
            actual=name(str(getattr(info,'username','')))
            if actual==login_user:
                print(f'✓ Phiên đăng nhập còn hiệu lực: @{actual}')
                _client=cl;_client_username=actual
                cfg['login']=actual;save_config(cfg)
                return cl
            print('Phiên trước thuộc một tài khoản khác; sẽ cần đăng nhập lại.')
        except Exception as exc:
            label=type(exc).__name__
            if any(x in label.lower() for x in ('challenge','feedback','rate','pleasewait','checkpoint','captcha')):
                raise RuntimeError('Instagram đang yêu cầu xác minh hoặc giới hạn: '+label+'. Dừng, mở Instagram bình thường để kiểm tra; không thử đăng nhập liên tục.')
            print('Phiên cũ không còn hiệu lực, cần đăng nhập lại ('+safe_text(label)+').')
    print('Mật khẩu chỉ nhập trong Terminal, không lưu vào script, DB hoặc file sao lưu.')
    password=getpass.getpass('Mật khẩu Instagram: ')
    if not password:raise RuntimeError('Chưa nhập mật khẩu')
    try:
        try:
            ok=cl.login(login_user,password)
        except Exception as exc:
            if type(exc).__name__=='TwoFactorRequired':
                code=input('Mã 2FA Instagram (nếu có): ').strip()
                ok=cl.login(login_user,password,verification_code=code)
            else: raise
        if not ok:raise RuntimeError('Instagram chưa chấp nhận đăng nhập')
        # Session is sensitive: private file, readable only by the local user
        cl.dump_settings(str(SESSION));protect(SESSION)
        cfg['login']=login_user;save_config(cfg)
        print('✓ Đăng nhập thành công; đã lưu phiên đăng nhập cục bộ.')
        _client=cl;_client_username=login_user
        return cl
    finally:
        del password


def collect_pages(client,user_id,method='mobile'):
    """Use independently tracked cursors so page gaps/loops are detected."""
    cursor=''
    seen_cursors=set()
    people=[]
    seen_ids=set()
    duplicate_count=0
    page_count=0
    error=''
    while page_count<MAX_PAGES:
        try:
            if method=='mobile':
                batch,next_cursor = client.user_following_v1_chunk(str(user_id),max_amount=PAGE_SIZE,max_id=cursor)
            else:
                batch,next_cursor = client.user_following_private_gql_chunk(str(user_id),max_amount=PAGE_SIZE,max_id=cursor or None)
        except Exception as exc:
            error=f'{type(exc).__name__}: {safe_error(exc)}'
            break
        page_count += 1
        if not isinstance(batch,(tuple,list)):
            error='Trang trả về không phải danh sách'
            break
        for user in batch:
            pk=str(getattr(user,'pk','') or '')
            uname=str(getattr(user,'username','') or '').lower()
            if not pk.isdecimal() or not valid_username(uname):
                error='API trả về ID / username không hợp lệ'
                break
            if pk not in seen_ids:
                people.append({'pk':pk,'username':uname});seen_ids.add(pk)
            else:
                duplicate_count += 1
        if error:break
        print(f'    Trang {page_count:>2} | {len(batch):>3} mục | {len(people):>4} tài khoản duy nhất')
        if not next_cursor:
            break
        token=str(next_cursor)
        if token==cursor or token in seen_cursors:
            error='Cursor phân trang lặp — dữ liệu chưa đủ'
            break
        seen_cursors.add(token)
        cursor=token
    else:
        error='Đạt giới hạn số trang — chưa kết thúc phân trang'
    return people,page_count,duplicate_count,error


def do_check(method='mobile'):
    cfg=config();target=cfg['target']
    checked=now()
    print(f'\nĐang kiểm tra Following của @{target} lúc {checked}')
    print('API không chính thức; chỉ đọc, không tự follow/unfollow.')
    try:
        cl=login()
        # target information and pk from the authorized session
        info=cl.user_info_by_username(target)
        pk=str(getattr(info,'pk','') or '')
        expected=int(getattr(info,'following_count'))
        if not pk.isdecimal() or expected<0:raise ValueError('Không xác định được ID hoặc following_count của tài khoản mục tiêu')
        print(f'Tổng Instagram báo: {expected}; ID tài khoản mục tiêu: {pk}')
        people,pages,duplicates,error=collect_pages(cl,pk,method)
        # We never silently fill missing users by merging distinct scans.
        found=len(people)
        status='verified' if not error and found==expected and all(p['pk'] for p in people) else 'partial'
        if error: print('⚠ Lỗi thu thập:',error)
        if found!=expected: print(f'⚠ Chênh lệch: thu được {found}/{expected}.')
        print('Tổng mục lặp qua các trang:',duplicates)
        # If after the paging total was zero while expected >0, still save failed attempt.
        note=(f'Phương thức {method}; trang={pages}; trùng trang={duplicates}; '+(error or 'Kết thúc phân trang; ')+
              ('khớp số lượng.' if status=='verified' else 'CHƯA ĐỦ hoặc chưa xác minh.'))
        row,backup=save_snapshot(target,pk,expected,people,status,'instagrapi_'+method,note,pages,checked)
        print_result(row,backup)
    except KeyboardInterrupt:
        print('\nĐã hủy kiểm tra, không tự ghi kết quả chưa hoàn tất.');raise
    except Exception as exc:
        # Store failed checks in history with date and error message, but without secrets.
        label=type(exc).__name__
        msg=safe_error(exc)
        row,backup=save_snapshot(target,status='failed',source='instagrapi_'+method,
                                  note=f'Kiểm tra thất bại ({label}): {msg}',checked_at=checked)
        print('✗ Kiểm tra không thành công:',label,':',msg)
        print('Đã ghi nhận lượt kiểm tra thất bại vào lịch sử:',backup)
        if any(x in (label+' '+msg).lower() for x in ('challenge','captcha','feedback','rate limit','pleasewait','checkpoint','2fa')):
            print('Hãy kiểm tra tài khoản trong Instagram/Brave bình thường; KHÔNG thử đăng nhập lặp liên tục.')


def print_result(row,backup):
    print('\n'+'='*64)
    print(f'Lượt #{row["id"]} | {row["checked_at"]}')
    print(f'Đã lấy: {row["found_count"]} | Instagram báo: {row["expected_count"]} | trạng thái: {row["status"]}')
    if row['status']=='verified':
        print('✓ ĐÃ KHỚP SỐ LƯỢNG và kết thúc phân trang (không bảo đảm API luôn phản ánh tuyệt đối).')
        if row['compared_to']:
            added=json.loads(row['added_json']);removed=json.loads(row['removed_json']);renamed=json.loads(row['renamed_json'])
            print(f'So với lượt đủ dữ liệu #{row["compared_to"]}: +{len(added)} follow, -{len(removed)} unfollow')
            for u in added:print('   + @'+u)
            for u in removed:print('   - @'+u)
            for r in renamed:print('   ~ @'+r['before']+' → @'+r['after']+' (đổi username, cùng ID)')
        else:print('Là mốc API đầu tiên được xác minh; chưa thể biết ai follow trước mốc này.')
    else:
        print('⚠ CHƯA XÁC MINH: không có kết luận follow/unfollow từ lượt này.')
    print('Đã sao lưu JSON:',backup)
    print('Đã sao lưu danh sách TXT:',export_username_file(row,'txt'))
    print('='*64)


def status_label(r):
    return {'verified':'KHỚP SỐ LƯỢNG','partial':'THIẾU/CHƯA ĐỦ','legacy':'MỐC CŨ (CHƯA ĐỦ)','failed':'THẤT BẠI'}.get(r['status'],r['status'])


def history():
    rows=get_rows(config()['target'])
    if not rows:
        print('Chưa có lịch sử.');return
    print('\n'+'='*105)
    print(f'{"ID":>4}  {"Ngày giờ":25} {"Đã lấy":>8}  {"Mong đợi":>8}   {"Follow mới":>10}  Tình trạng')
    print('-'*105)
    for r in rows:
        added=str(len(json.loads(r['added_json']))) if r['compared_to'] else '—'
        print(f'{r["id"]:>4}  {r["checked_at"]:25} {r["found_count"]:>8}  {str(r["expected_count"] if r["expected_count"] is not None else "—"):>8}   {added:>10}  {status_label(r)}')
    print('='*105)
    print('— ở cột Follow mới nghĩa là không có đủ hai mốc xác minh để so sánh, KHÔNG phải 0.')


def show_detail():
    try:
        ident=int(input('Nhập ID lượt kiểm tra: ').strip())
    except ValueError:
        print('ID không hợp lệ');return
    row=get_row(ident)
    if not row:
        print('Không tìm thấy lượt kiểm tra.');return
    if row['account']!=config()['target']:
        print('Lượt kiểm tra này thuộc tài khoản khác.');return

    people=people_of(row)
    print('\n'+'='*80)
    print(f'CHI TIẾT LƯỢT #{ident} | @{row["account"]}')
    print(f'Ngày giờ: {row["checked_at"]}')
    print(f'Trạng thái: {status_label(row)} | Thu được: {row["found_count"]} | Instagram báo: {row["expected_count"]}')
    print(f'Nguồn: {row["source"]} | Số trang: {row["page_count"]}')
    if row['note']:print('Ghi chú:',row['note'])
    print('-'*80)
    if row['compared_to']:
        added=json.loads(row['added_json'])
        removed=json.loads(row['removed_json'])
        renamed=json.loads(row['renamed_json'])
        print(f'KẾT QUẢ SO VỚI LƯỢT #{row["compared_to"]} (đều đã khớp số lượng):')
        print(f'  Follow mới: {len(added)}'+(' | '+', '.join('@'+u for u in added) if added else ''))
        print(f'  Không còn xuất hiện: {len(removed)}'+(' | '+', '.join('@'+u for u in removed) if removed else ''))
        for r in renamed:
            print(f'  Đổi tên cùng ID: @{r["before"]} → @{r["after"]}')
    else:
        print('Follow mới: CHƯA THỂ KẾT LUẬN (chưa có hai bản ghi đủ dữ liệu).')
    print('-'*80)
    print(f'TOÀN BỘ {len(people)} USERNAME ĐÃ THU ĐƯỢC Ở LƯỢT #{ident}:')
    if not people:
        print('  (Không có username trong bản ghi này.)')
    else:
        for index, p in enumerate(people,1):
            suffix=f' | Instagram ID: {p["pk"]}' if p['pk'] else ' | ID chưa có'
            print(f'  {index:>3}. @{p["username"]}{suffix}')
    print('\nLƯU Ý: danh sách trên chỉ thể hiện thứ tự dữ liệu API trả về,')
    print('KHÔNG PHẢI thứ tự người này bấm Follow (cũ → mới hoặc mới → cũ).')
    if row['status']!='verified':
        print('⚠ BẢN GHI CHƯA ĐẦY ĐỦ: không suy ra unfollow từ những tên còn thiếu.')
    print('='*80)
    saved_txt=export_username_file(row,'txt')
    print('File TXT của lượt này:',saved_txt)
    if input('Xuất thêm CSV để mở bằng Excel/LibreOffice? (y/N): ').strip().lower()=='y':
        print('Đã xuất CSV:',export_username_file(row,'csv'))


def compare_menu():
    try:
        old_id=int(input('ID lượt cũ: ').strip()); new_id=int(input('ID lượt mới: ').strip())
    except ValueError: print('ID không hợp lệ');return
    old,new=get_row(old_id),get_row(new_id)
    if not old or not new or old['account']!=new['account'] or old['account']!=config()['target']:
        print('Hai lượt kiểm tra không tồn tại hoặc khác tài khoản');return
    delta=diff(old,new)
    if not delta['verified']:
        print('\n⚠ CẢNH BÁO: Một hoặc cả hai mốc chưa đầy đủ; đây chỉ là khác biệt quan sát, KHÔNG khẳng định follow/unfollow.')
    print(f'\nSo sánh #{old_id} ({old["checked_at"]}) → #{new_id} ({new["checked_at"]})')
    print(f'Xuất hiện thêm: {len(delta["added"])}');[print('   + @'+p) for p in delta['added']]
    print(f'Không còn xuất hiện: {len(delta["removed"])}');[print('   - @'+p) for p in delta['removed']]
    if delta['renamed']:
        print('Đổi username (cùng ID):')
        for p in delta['renamed']:print('   ~ @'+p['before']+' → @'+p['after'])
    if not delta['verified']:print('Chỉ có thể sử dụng làm đối chiếu tham khảo.')


def export_all():
    rows=get_rows(config()['target'])
    if not rows:print('Chưa có lịch sử.');return
    ts=datetime.now(TZ).strftime('%Y%m%d_%H%M%S')
    target=config()['target']
    jfile=BACKUPS/f'{ts}_{target}_ALL_HISTORY.json'
    cfile=BACKUPS/f'{ts}_{target}_SUMMARY.csv'
    out=[]
    for r in rows:
        d={k:v for k,v in r.items() if k not in {'people_json','added_json','removed_json','renamed_json'}}
        d.update({'following':people_of(r),'new_usernames':json.loads(r['added_json']),
                  'unfollow_usernames':json.loads(r['removed_json']),'renamed':json.loads(r['renamed_json'])})
        out.append(d)
    jfile.write_text(json.dumps({'exported_at':now(),'account':target,'snapshots':out},ensure_ascii=False,indent=2),encoding='utf-8')
    with cfile.open('w',encoding='utf-8-sig',newline='') as fp:
        w=csv.writer(fp)
        w.writerow(['ID','Ngày kiểm tra','Trạng thái','Số thu được','Số Instagram','Follow mới','Unfollow','Danh sách follow mới'])
        for r in rows:
            added=json.loads(r['added_json'])
            w.writerow([r['id'],r['checked_at'],r['status'],r['found_count'],r['expected_count'],
                        len(added) if r['compared_to'] else '',
                        len(json.loads(r['removed_json'])) if r['compared_to'] else '', '; '.join(added)])
    protect(jfile);protect(cfile)
    print('Đã xuất toàn bộ lịch sử:')
    print('  JSON:',jfile)
    print('  CSV :',cfile)



def _snapshot_files(row):
    """Only files generated by this app for one exact snapshot ID."""
    ts = re.sub(r'[^0-9]', '', row['checked_at'])[:14]
    target = name(row['account'])
    check_id = int(row['id'])
    stem = f'{ts}_{target}_check_{check_id}'
    return [BACKUPS / f'{stem}.json',
            BACKUPS / f'{stem}_following.txt',
            BACKUPS / f'{stem}_following.csv']


def _recalculate_history(conn, account):
    """Rebase remaining verified snapshots so none refer to deleted IDs."""
    rows = [dict(r) for r in conn.execute(
        'SELECT * FROM snapshots WHERE account=? ORDER BY checked_at,id', (account,))]
    prev = None
    changed = []
    for row in rows:
        change = None
        if row['status'] == 'verified':
            if prev is not None:
                candidate = diff(prev, row)
                if candidate['verified']:
                    change = candidate
        new_ref = prev['id'] if change else None
        if row['status'] == 'verified':
            prev = row
        added = json.dumps(change['added'], ensure_ascii=False) if change else '[]'
        removed = json.dumps(change['removed'], ensure_ascii=False) if change else '[]'
        renamed = json.dumps(change['renamed'], ensure_ascii=False) if change else '[]'
        if (row['compared_to'] != new_ref or row['added_json'] != added or
            row['removed_json'] != removed or row['renamed_json'] != renamed):
            conn.execute('UPDATE snapshots SET compared_to=?,added_json=?,removed_json=?,renamed_json=? WHERE id=?',
                         (new_ref, added, removed, renamed, row['id']))
            changed.append(int(row['id']))
    return changed


def delete_history_row(account, ident, remove_snapshot_files=True):
    """Delete exactly one snapshot ID of account; preserve other data and session.

    Recompute deltas so later snapshots never reference a deleted ID.
    Existing ALL_HISTORY exports remain unchanged; warn users they contain old data.
    """
    account = name(account)
    ids = [int(ident)]
    with con() as conn:
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM snapshots WHERE account=? AND id IN (' +
            ','.join('?' for _ in ids) + ')', (account, *ids))]
        if len(rows) != len(ids):
            raise ValueError('Có ID không tồn tại hoặc không thuộc tài khoản đang theo dõi. Chưa xóa gì.')
        conn.executemany('DELETE FROM snapshots WHERE account=? AND id=?', [(account, i) for i in ids])
        changed_ids = _recalculate_history(conn, account)
    # Transaction committed; now refresh derived backup summaries.
    errors = []
    for rid in changed_ids:
        row = get_row(rid)
        if row:
            try:
                create_backup(row)
            except OSError as exc:
                errors.append(f'Không làm mới sao lưu lượt #{rid}: {type(exc).__name__}')
    removed_files = 0
    if remove_snapshot_files:
        for old in rows:
            for path in _snapshot_files(old):
                try:
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                        removed_files += 1
                except OSError as exc:
                    errors.append(f'Không xóa được {path.name}: {type(exc).__name__}')
    return {'deleted':len(rows), 'recalculated':len(changed_ids),
            'removed_files':removed_files, 'file_errors':errors}


def delete_menu():
    """Only allow deleting one explicit snapshot ID; no bulk-delete path."""
    account = config()['target']
    rows = get_rows(account)
    if not rows:
        print('Không có lượt kiểm tra nào của tài khoản này để xóa.')
        return
    print('\n'+'='*65)
    print(f'XÓA MỘT LƯỢT KIỂM TRA — @{account} ({len(rows)} lượt)')
    print('Nhập ID lượt cần xóa, hoặc 0 để hủy.')
    print('='*65)
    history()
    try:
        ident = int(input('ID lượt muốn xóa (0 = hủy): ').strip())
    except ValueError:
        print('ID không hợp lệ. Không thay đổi dữ liệu.')
        return
    if ident == 0:
        print('Đã hủy, không có thay đổi.')
        return
    row = get_row(ident)
    if not row or row['account'] != account:
        print('ID không tồn tại trong tài khoản đang theo dõi. Không thay đổi dữ liệu.')
        return
    print(f'Bạn chọn DUY NHẤT lượt #{ident} — {row["checked_at"]} — {row["found_count"]} username.')
    print('Nếu xóa mốc đã xác minh, các kết quả so sánh sau đó được tính lại.')
    if input(f'Gõ chính xác XOA {ident} để xác nhận: ').strip() != f'XOA {ident}':
        print('Đã hủy, không có thay đổi.')
        return
    print('Chỉ áp dụng cho lượt này; không có chức năng xóa tất cả lịch sử.')
    print('Các file backup JSON/TXT/CSV RIÊNG của lượt này có thể được xóa cùng.')
    remove_files = input('Đưa cả file backup RIÊNG của lượt này ra khỏi thư mục? (y/N): ').strip().lower() == 'y'
    result = delete_history_row(account, ident, remove_files)
    print(f'✓ Đã xóa đúng {result["deleted"]} lượt khỏi SQLite; cập nhật {result["recalculated"]} lượt còn lại.')
    if remove_files:
        print(f'Đã xóa {result["removed_files"]} file sao lưu riêng.')
    else:
        print('Đã giữ file sao lưu riêng của lượt này.')
    if result['file_errors']:
        for item in result['file_errors']:
            print('⚠',item)
    print('Phiên đăng nhập và các lượt kiểm tra khác không bị xóa.')
    print('Lưu ý: file ALL_HISTORY đã xuất trước đây có thể chứa dữ liệu cũ.')


def change_target():
    cfg=config();v=input('Username tài khoản muốn theo dõi: ').strip()
    try:
        cfg['target']=name(v)
        save_config(cfg)
        print('Đã đổi tài khoản theo dõi thành @'+cfg['target'])
    except ValueError as exc:print(exc)


def menu():
    dirs();db().close()
    if not (DATA/'bootstrap.done').exists():
        import_legacy(verbose=True)
        (DATA/'bootstrap.done').write_text(now(),encoding='utf-8')
        protect(DATA/'bootstrap.done')
    while True:
        cfg=config()
        print(f'''\n{'='*54}
    INSTAGRAM FOLLOWING TRACKER - TERMINAL
    Theo dõi: @{cfg['target']}
    Đăng nhập: @{cfg['login'] or 'chưa có phiên'}
{'='*54}
 1. KIỂM TRA Following ngay (API có phân trang)
 2. Xem LỊCH SỬ các lần kiểm tra
 3. Xem CHI TIẾT + TOÀN BỘ username từng lần
 4. SO SÁNH hai lần kiểm tra
 5. SAO LƯU toàn bộ lịch sử JSON + CSV
 6. Nhập lại dữ liệu APP CŨ (nếu cần)
 7. Đăng nhập / làm mới phiên Instagram
 8. Đổi tài khoản cần theo dõi
 9. Thử cách lấy DỰ PHÒNG (mobile GraphQL)
10. XÓA MỘT lượt kiểm tra theo ID
 0. Thoát
{'='*54}''')
        choice=input('Nhập lựa chọn: ').strip()
        try:
            if choice=='1':do_check('mobile')
            elif choice=='2':history()
            elif choice=='3':show_detail()
            elif choice=='4':compare_menu()
            elif choice=='5':export_all()
            elif choice=='6':import_legacy()
            elif choice=='7':login(force=True)
            elif choice=='8':change_target()
            elif choice=='9':
                print('Dự phòng chỉ nên thử khi phương pháp chính thiếu dữ liệu. Không tự hợp nhất hai lượt thiếu.')
                if input('Tiếp tục? (y/N): ').strip().lower()=='y':do_check('graphql')
            elif choice=='10':delete_menu()
            elif choice=='0':print('Đã thoát. Dữ liệu lịch sử vẫn được giữ.');break
            else:print('Lựa chọn không hợp lệ.')
        except KeyboardInterrupt:
            print('\nĐã dừng thao tác.')
        except Exception as exc:
            print('Lỗi:',type(exc).__name__,':',safe_text(exc)[:300])


if __name__=='__main__':
    if '--help' in sys.argv:
        print('Run: python ig_following.py (interactive menu). Requires instagrapi for online checks.')
    else:
        menu()
