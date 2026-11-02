#!/usr/bin/env python3
"""Instagram Following & Followers CLI - read-only snapshots and local history.

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
TZ = ZoneInfo('Asia/Ho_Chi_Minh')
USER_RE = re.compile(r'^[A-Za-z0-9._]{1,30}$')
DEFAULT_TARGET = ''  # Choose a target through menu 8; existing data/config are preserved.
PAGE_SIZE = 100
MAX_PAGES = 250
KINDS = ('following', 'followers')


def check_kind(kind):
    if kind not in KINDS:
        raise ValueError('Loại danh sách không hợp lệ')
    return kind


def kind_label(kind):
    return 'Followers' if kind == 'followers' else 'Following'

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
    # Non-destructive migration: every snapshot created before V5 is Following.
    cols = {r[1] for r in conn.execute('PRAGMA table_info(snapshots)')}
    if 'kind' not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN kind TEXT NOT NULL DEFAULT 'following'")
    conn.execute('CREATE INDEX IF NOT EXISTS ix_snapshots_account_kind ON snapshots(account,kind,checked_at,id)')
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
            return {'target': name(cfg['target']) if cfg.get('target') else '',
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


def get_rows(account=None, kind='following'):
    check_kind(kind)
    with con() as c:
        if account is not None:
            return [dict(r) for r in c.execute(
                'SELECT * FROM snapshots WHERE account=? AND kind=? ORDER BY checked_at,id',
                (account,kind))]
        return [dict(r) for r in c.execute(
            'SELECT * FROM snapshots WHERE kind=? ORDER BY checked_at,id', (kind,))]


def get_row(rowid):
    with con() as c:
        row = c.execute('SELECT * FROM snapshots WHERE id=?',(rowid,)).fetchone()
    return dict(row) if row else None


def people_of(row):
    return json.loads(row['people_json'])


def diff(old, new):
    """ID comparison only if both are complete sets with IDs; legacy uses names and stays unverified."""
    a, b = people_of(old), people_of(new)
    use_ids = all(p['pk'] for p in a+b)  # Empty verified list is a legitimate snapshot.
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
    verified = (old['status']=='verified' and new['status']=='verified' and bool(use_ids)
        and old.get('kind','following') == new.get('kind','following')
        and (not old.get('account') or not new.get('account') or old['account'] == new['account'])
        and (not old.get('target_pk') or not new.get('target_pk')
             or old.get('target_pk')==new.get('target_pk')))
    return {'added':added,'removed':removed,'renamed':renamed,'verified':verified,'by_id':use_ids}


def latest_verified(account, exclude=None, kind='following'):
    check_kind(kind)
    with con() as c:
        row = c.execute('''SELECT * FROM snapshots WHERE account=? AND kind=? AND status='verified' AND id!=? ORDER BY checked_at DESC,id DESC LIMIT 1''',
                        (account,kind,exclude or -1)).fetchone()
    return dict(row) if row else None


def export_username_file(row, kind='txt', destination=None):
    """Human-readable exports from an EXISTING snapshot; never call Instagram."""
    kind = kind.lower()
    if kind not in ('txt', 'csv'):
        raise ValueError('Chỉ hỗ trợ TXT hoặc CSV')
    ts = re.sub(r'[^0-9]', '', row['checked_at'])[:14]
    target = row['account']
    relationship = row.get('kind','following')
    check_kind(relationship)
    output = Path(destination) if destination else BACKUPS / f'{ts}_{target}_check_{row["id"]}_{relationship}.{kind}'
    output.parent.mkdir(parents=True, exist_ok=True)
    people = people_of(row)
    if kind == 'txt':
        lines = [f'Danh sách {kind_label(relationship)} ĐÃ THU ĐƯỢC của @{target}',
                 f'Lượt #{row["id"]} | Kiểm tra: {row["checked_at"]}',
                 f'Thu được: {row["found_count"]} | Instagram báo: {row["expected_count"]}',
                 f'Trạng thái: {status_label(row)}',
                 'THỨ TỰ DƯỚI ĐÂY LÀ THỨ TỰ API TRẢ VỀ, KHÔNG PHẢI THỨ TỰ FOLLOW THEO THỜI GIAN.',
                 'Nếu chưa đầy đủ, các username vắng mặt KHÔNG chứng minh tài khoản đó đã ngừng theo dõi.',
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
        'version':2, 'account':row['account'], 'kind':row.get('kind','following'), 'checked_at':row['checked_at'],
        'status':row['status'], 'source':row['source'], 'expected_count':row['expected_count'],
        'found_count':row['found_count'], 'pages':row['page_count'],
        'compared_to':row['compared_to'], 'new_follow_count':len(json.loads(row['added_json'])) if row['compared_to'] else None,
        'new_usernames':json.loads(row['added_json']),
        'new_follower_count':(len(json.loads(row['added_json'])) if row['compared_to'] else None)
                            if row['kind']=='followers' else None,
        'lost_follower_count':(len(json.loads(row['removed_json'])) if row['compared_to'] else None)
                             if row['kind']=='followers' else None,
        'removed_usernames':json.loads(row['removed_json']),
        'unfollow_count':len(json.loads(row['removed_json'])) if row['compared_to'] else None,
        'unfollow_usernames':json.loads(row['removed_json']),
        'renamed':json.loads(row['renamed_json']),
        'note':row['note'], row.get('kind','following'):people_of(row),
        'caution':'Changes are confirmed only if both snapshots are verified, have IDs and are the same kind and account.'
    }
    ts = re.sub(r'[^0-9]','',row['checked_at'])[:14]
    out = BACKUPS / f'{ts}_{row["account"]}_check_{row["id"]}.json'
    out.write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding='utf-8')
    protect(out)
    # Each snapshot also has a simple text file, readable without Python or JSON tooling.
    export_username_file(row,'txt')
    return out


def save_snapshot(account, target_pk='', expected=None, people=None, status='partial',
                  source='instagrapi', note='', pages=0, checked_at=None, origin=None,
                  kind='following'):
    kind = check_kind(kind)
    account = name(account)
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
        prev = latest_verified(account,kind=kind) if status=='verified' else None
        # compare against previous verified snapshot only; partial/legacy snapshots cannot trigger false changes
        proto = {'status':status,'people_json':json.dumps(people),'target_pk':target_pk,'kind':kind,'account':account}
        change = diff(prev,proto) if prev else None
        if change and not change['verified']:
            # e.g. target changed unexpectedly; refuse automatic claims
            change=None
        cur = c.execute('''INSERT INTO snapshots
          (account,target_pk,checked_at,expected_count,found_count,status,source,page_count,note,people_json,compared_to,added_json,removed_json,renamed_json,origin,kind)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            account,str(target_pk or ''),checked_at,expected,len(people),status,source,int(pages),
            safe_text(note)[:2000],json.dumps(people,ensure_ascii=False),
            prev['id'] if change else None,
            json.dumps(change['added'],ensure_ascii=False) if change else '[]',
            json.dumps(change['removed'],ensure_ascii=False) if change else '[]',
            json.dumps(change['renamed'],ensure_ascii=False) if change else '[]',origin,kind))
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


def collect_pages(client,user_id,method='mobile',kind='following'):
    """Use independently tracked cursors so page gaps/loops are detected."""
    check_kind(kind)
    if method not in ('mobile','graphql'):
        raise ValueError('Phương thức lấy dữ liệu không hợp lệ')
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
                func = client.user_followers_v1_chunk if kind=='followers' else client.user_following_v1_chunk
                batch,next_cursor = func(str(user_id),max_amount=PAGE_SIZE,max_id=cursor)
            else:
                func = (client.user_followers_private_gql_chunk if kind=='followers'
                        else client.user_following_private_gql_chunk)
                batch,next_cursor = func(str(user_id),max_amount=PAGE_SIZE,max_id=cursor or None)
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



def _parse_complete_users(raw):
    """Normalize high-level API dict/list, preserve stable PKs; fail closed on invalid data."""
    if isinstance(raw, dict):
        source = raw.values()
    elif isinstance(raw, (tuple, list)):
        source = raw
    else:
        raise ValueError('API Followers trả về kiểu dữ liệu không hợp lệ')
    people = []
    keys = set()
    usernames = set()
    for item in source:
        if isinstance(item, dict):
            pk = str(item.get('pk') or '')
            uname = str(item.get('username') or '').strip().lower()
        else:
            pk = str(getattr(item,'pk','') or '')
            uname = str(getattr(item,'username','') or '').strip().lower()
        if not pk.isdecimal() or not valid_username(uname):
            raise ValueError('API Followers trả về ID / username không hợp lệ')
        if pk in keys or uname in usernames:
            raise ValueError('Kết quả API Followers có ID hoặc username trùng lặp')
        keys.add(pk);usernames.add(uname)
        people.append({'pk':pk,'username':uname})
    return people


def _stop_on_instagram_restriction(exc):
    """Avoid probing other endpoints after checkpoints, challenges or rate limits."""
    signal = (type(exc).__name__+' '+safe_error(exc)).lower()
    return any(x in signal for x in (
        'challenge','checkpoint','captcha','feedbackrequired','feedback_required',
        'ratelimit','rate limit','pleasewait','please wait','twofactor','2fa',
        'loginrequired','login_required','login required'))


def collect_followers_robust(client, user_id, expected):
    """Try instagrapi's high-level auto-fallback, then one distinct private-GQL path.

    Only a complete *single source* can be considered verified. Combining two
    truncated lists may provide more usernames, but NEVER proves a complete
    simultaneous snapshot, even when the union has the expected count.

    Returns (people, pages, duplicates, error, source, note, complete_source).
    """
    if expected < 0:
        raise ValueError('Số Followers không hợp lệ')
    first = []
    failure = ''
    print('  Nguồn 1: instagrapi.user_followers() (tự xử lý nguồn giới hạn)')
    try:
        # Unlike V5's direct chunk API, this official instagrapi helper has a
        # fallback strategy for a limited followers list.
        raw = client.user_followers(str(user_id), amount=expected)
        first = _parse_complete_users(raw)
        print(f'    Thu được {len(first)}/{expected} Instagram ID duy nhất')
    except Exception as exc:
        failure = f'{type(exc).__name__}: {safe_error(exc)}'
        print('    Không hoàn thành nguồn 1: '+type(exc).__name__)
        if _stop_on_instagram_restriction(exc):
            return [],0,0,failure,'instagrapi_auto',(
                'Đã dừng vì Instagram yêu cầu xác minh / giới hạn; không gọi API khác.'),False

    if not failure and len(first)==expected:
        return first,0,0,'','instagrapi_auto',(
            'Nguồn 1: user_followers() khớp số lượng; thư viện tự xử lý nguồn giới hạn. '
            'Số trang nội bộ do thư viện quản lý; khớp số lượng không bảo đảm tuyệt đối.'),True

    print('  Nguồn 2: private GraphQL FollowersList (tối đa một lượt dự phòng)')
    second,pages,dups,gql_error=collect_pages(client,user_id,'graphql','followers')
    print(f'    Thu được {len(second)}/{expected} ID duy nhất từ nguồn 2')
    ids_first = {x['pk'] for x in first}
    ids_second = {x['pk'] for x in second}
    if not gql_error and len(second)==expected and ids_first <= ids_second:
        # It is safe to use this complete single-source result even if the
        # partial first source was incomplete; it did not contradict it.
        return second,pages,dups,'','instagrapi_private_gql',(
            f'Nguồn 1={len(first)}; nguồn 2={len(second)} đầy đủ theo số lượng; '
            'các ID nguồn 1 đều thuộc nguồn 2. Không bảo đảm tuyệt đối.'),True

    # Keep the most information for inspection, without claiming a verified
    # snapshot. Mixing different moments cannot establish an exact roster.
    merged = list(first)
    for item in second:
        if item['pk'] not in ids_first:
            merged.append(item)
    conflict = bool(ids_first-ids_second) if len(second)==expected else False
    notes = (f'Nguồn 1={len(first)}/{expected}; nguồn 2={len(second)}/{expected}; '
             f'hợp nhất để tham khảo={len(merged)}; KHÔNG dùng hợp nhất để xác minh.')
    if conflict:
        notes += ' Nguồn 1 và nguồn 2 không nhất quán về ID.'
    if failure: notes += ' Lỗi nguồn 1: '+failure
    if gql_error: notes += ' Lỗi nguồn 2: '+gql_error
    reason = gql_error or (failure if not second and not first else '')
    return merged,pages,dups,reason,'instagrapi_auto_partial',notes,False


def do_check(method='mobile',kind='following'):
    kind = check_kind(kind)
    cfg=config();target=cfg['target']
    if not target:
        print('Chưa chọn tài khoản mục tiêu. Chọn menu 8 trước khi kiểm tra.')
        return
    checked=now()
    print(f'\nĐang kiểm tra {kind_label(kind)} của @{target} lúc {checked}')
    print('API không chính thức; chỉ đọc, không tự follow/unfollow.')
    try:
        cl=login()
        # target information and pk from the authorized session
        info=cl.user_info_by_username(target)
        pk=str(getattr(info,'pk','') or '')
        count_attr = 'follower_count' if kind=='followers' else 'following_count'
        expected=int(getattr(info,count_attr))
        if not pk.isdecimal() or expected<0:
            raise ValueError('Không xác định được ID hoặc '+count_attr+' của tài khoản mục tiêu')
        print(f'Tổng Instagram báo: {expected}; ID tài khoản mục tiêu: {pk}')
        if kind=='followers' and method=='mobile':
            people,pages,duplicates,error,source,note,complete_source = collect_followers_robust(cl,pk,expected)
        else:
            people,pages,duplicates,error=collect_pages(cl,pk,method,kind)
            source='instagrapi_'+method
            note=f'Phương thức {method}; trang={pages}; trùng trang={duplicates}; '
            complete_source = not error

        # A source may have completed while the profile count changed mid-scan.
        # Never compare against a moving count as an exact point-in-time list.
        stable_count=True
        if not error or people:
            try:
                final_info=cl.user_info_by_username(target)
                final_pk=str(getattr(final_info,'pk','') or '')
                final_expected=int(getattr(final_info,count_attr))
                if final_pk != pk or final_expected != expected:
                    stable_count=False
                    note+=f' Hồ sơ thay đổi trong lúc kiểm tra (đầu={expected}, cuối={final_expected});'
            except Exception as exc:
                stable_count=False
                note+=' Không xác minh lại được số lượng sau kiểm tra ('+type(exc).__name__+');'

        found=len(people)
        status=('verified' if complete_source and not error and stable_count
                and found==expected and all(p['pk'] for p in people) else 'partial')
        if error: print('⚠ Lỗi thu thập:',error)
        if found!=expected: print(f'⚠ Chênh lệch: thu được {found}/{expected}.')
        if not stable_count:print('⚠ Số lượng hoặc ID tài khoản mục tiêu chưa ổn định/xác minh lại được.')
        if kind=='followers' and method=='mobile' and not complete_source:
            print('⚠ Danh sách hợp nhất chỉ để THAM KHẢO; không được xác minh để so sánh.')
        print('Tổng mục lặp qua các trang:',duplicates)
        note+=(f' Kết quả={found}/{expected}; '+
               ('khớp số lượng theo tiêu chí kiểm tra.' if status=='verified'
                else 'CHƯA ĐỦ hoặc chưa xác minh.'))

        row,backup=save_snapshot(target,pk,expected,people,status,source,note,pages,checked,kind=kind)
        print_result(row,backup)
    except KeyboardInterrupt:
        print('\nĐã hủy kiểm tra, không tự ghi kết quả chưa hoàn tất.');raise
    except Exception as exc:
        # Store failed checks in history with date and error message, but without secrets.
        label=type(exc).__name__
        msg=safe_error(exc)
        row,backup=save_snapshot(target,status='failed',source='instagrapi_'+method,
                                  note=f'Kiểm tra thất bại ({label}): {msg}',checked_at=checked,kind=kind)
        print('✗ Kiểm tra không thành công:',label,':',msg)
        print('Đã ghi nhận lượt kiểm tra thất bại vào lịch sử:',backup)
        if any(x in (label+' '+msg).lower() for x in ('challenge','captcha','feedback','rate limit','pleasewait','checkpoint','2fa')):
            print('Hãy kiểm tra tài khoản trong Instagram/Brave bình thường; KHÔNG thử đăng nhập lặp liên tục.')


def print_result(row,backup):
    print('\n'+'='*64)
    print(f'{kind_label(row.get("kind","following"))} | Lượt #{row["id"]} | {row["checked_at"]}')
    print(f'Đã lấy: {row["found_count"]} | Instagram báo: {row["expected_count"]} | trạng thái: {row["status"]}')
    if row['status']=='verified':
        print('✓ ĐÃ KHỚP SỐ LƯỢNG và kết thúc phân trang (không bảo đảm API luôn phản ánh tuyệt đối).')
        if row['compared_to']:
            added=json.loads(row['added_json']);removed=json.loads(row['removed_json']);renamed=json.loads(row['renamed_json'])
            if row.get('kind') == 'followers':
                print(f'So với lượt đủ dữ liệu #{row["compared_to"]}: +{len(added)} người theo dõi mới, -{len(removed)} người không còn theo dõi')
            else:
                print(f'So với lượt đủ dữ liệu #{row["compared_to"]}: +{len(added)} follow, -{len(removed)} unfollow')
            for u in added:print('   + @'+u)
            for u in removed:print('   - @'+u)
            for r in renamed:print('   ~ @'+r['before']+' → @'+r['after']+' (đổi username, cùng ID)')
        else:print('Là mốc đầu tiên được xác minh của loại danh sách này; chưa thể biết những thay đổi trước mốc này.')
    else:
        print('⚠ CHƯA XÁC MINH: không có kết luận về tài khoản thêm/bớt từ lượt này.')
    print('Đã sao lưu JSON:',backup)
    print('Đã sao lưu danh sách TXT:',export_username_file(row,'txt'))
    print('='*64)


def status_label(r):
    return {'verified':'KHỚP SỐ LƯỢNG','partial':'THIẾU/CHƯA ĐỦ','legacy':'MỐC CŨ (CHƯA ĐỦ)','failed':'THẤT BẠI'}.get(r['status'],r['status'])


def history(kind='following'):
    kind = check_kind(kind)
    rows=get_rows(config()['target'],kind)
    if not rows:
        print('Chưa có lịch sử.');return
    print('\nLỊCH SỬ '+kind_label(kind).upper()+' — @'+config()['target'])
    print('='*105)
    column = 'Follower mới' if kind=='followers' else 'Follow mới'
    print(f'{"ID":>4}  {"Ngày giờ":25} {"Đã lấy":>8}  {"Mong đợi":>8}   {column:>12}  Tình trạng')
    print('-'*105)
    for r in rows:
        added=str(len(json.loads(r['added_json']))) if r['compared_to'] else '—'
        print(f'{r["id"]:>4}  {r["checked_at"]:25} {r["found_count"]:>8}  {str(r["expected_count"] if r["expected_count"] is not None else "—"):>8}   {added:>10}  {status_label(r)}')
    print('='*105)
    print(f'— ở cột {column} nghĩa là không có đủ hai mốc xác minh để so sánh, KHÔNG phải 0.')


def show_detail(kind='following'):
    kind = check_kind(kind)
    try:
        ident=int(input('Nhập ID lượt kiểm tra: ').strip())
    except ValueError:
        print('ID không hợp lệ');return
    row=get_row(ident)
    if not row:
        print('Không tìm thấy lượt kiểm tra.');return
    if row['account']!=config()['target'] or row['kind']!=kind:
        print('Lượt kiểm tra này thuộc tài khoản hoặc loại danh sách khác.');return

    people=people_of(row)
    print('\n'+'='*80)
    print(f'CHI TIẾT {kind_label(kind)} — LƯỢT #{ident} | @{row["account"]}')
    print(f'Ngày giờ: {row["checked_at"]}')
    print(f'Trạng thái: {status_label(row)} | Thu được: {row["found_count"]} | Instagram báo: {row["expected_count"]}')
    shown_pages = ('thư viện quản lý nội bộ' if row['source']=='instagrapi_auto' and row['page_count']==0 else row['page_count'])
    print(f'Nguồn: {row["source"]} | Số trang: {shown_pages}')
    if row['note']:print('Ghi chú:',row['note'])
    print('-'*80)
    if row['compared_to']:
        added=json.loads(row['added_json'])
        removed=json.loads(row['removed_json'])
        renamed=json.loads(row['renamed_json'])
        print(f'KẾT QUẢ SO VỚI LƯỢT #{row["compared_to"]} (đều đã khớp số lượng):')
        label_new = 'Follower mới' if kind=='followers' else 'Follow mới'
        label_gone = 'Không còn theo dõi tài khoản mục tiêu' if kind=='followers' else 'Không còn xuất hiện'
        print(f'  {label_new}: {len(added)}'+(' | '+', '.join('@'+u for u in added) if added else ''))
        print(f'  {label_gone}: {len(removed)}'+(' | '+', '.join('@'+u for u in removed) if removed else ''))
        for r in renamed:
            print(f'  Đổi tên cùng ID: @{r["before"]} → @{r["after"]}')
    else:
        print('Thay đổi: CHƯA THỂ KẾT LUẬN (chưa có hai bản ghi đủ dữ liệu của loại danh sách này).')
    print('-'*80)
    print(f'TOÀN BỘ {len(people)} USERNAME {kind_label(kind).upper()} ĐÃ THU ĐƯỢC Ở LƯỢT #{ident}:')
    if not people:
        print('  (Không có username trong bản ghi này.)')
    else:
        for index, p in enumerate(people,1):
            suffix=f' | Instagram ID: {p["pk"]}' if p['pk'] else ' | ID chưa có'
            print(f'  {index:>3}. @{p["username"]}{suffix}')
    print('\nLƯU Ý: danh sách trên chỉ thể hiện thứ tự dữ liệu API trả về,')
    print('KHÔNG PHẢI thứ tự người này bấm Follow (cũ → mới hoặc mới → cũ).')
    if row['status']!='verified':
        print('⚠ BẢN GHI CHƯA ĐẦY ĐỦ: không suy ra thay đổi từ những tên còn thiếu.')
    print('='*80)
    saved_txt=export_username_file(row,'txt')
    print('File TXT của lượt này:',saved_txt)
    if input('Xuất thêm CSV để mở bằng Excel/LibreOffice? (y/N): ').strip().lower()=='y':
        print('Đã xuất CSV:',export_username_file(row,'csv'))


def compare_menu(kind='following'):
    kind = check_kind(kind)
    try:
        old_id=int(input('ID lượt cũ: ').strip()); new_id=int(input('ID lượt mới: ').strip())
    except ValueError: print('ID không hợp lệ');return
    old,new=get_row(old_id),get_row(new_id)
    if (not old or not new or old['account']!=new['account']
            or old['account']!=config()['target']
            or old['kind']!=kind or new['kind']!=kind):
        print('Hai lượt kiểm tra không tồn tại hoặc khác tài khoản / loại danh sách');return
    if old_id==new_id:
        print('Hãy chọn hai lượt kiểm tra khác nhau.');return
    delta=diff(old,new)
    if not delta['verified']:
        print('\n⚠ CẢNH BÁO: Một hoặc cả hai mốc chưa đầy đủ; đây chỉ là khác biệt quan sát, KHÔNG khẳng định follow/unfollow.')
    print(f'\nSo sánh {kind_label(kind)} #{old_id} ({old["checked_at"]}) → #{new_id} ({new["checked_at"]})')
    label_added = 'Người theo dõi mới' if kind=='followers' else 'Tài khoản mới được theo dõi'
    label_removed = 'Người không còn theo dõi' if kind=='followers' else 'Tài khoản không còn được theo dõi'
    print(f'{label_added}: {len(delta["added"])}')
    for p in delta['added']: print('   + @'+p)
    print(f'{label_removed}: {len(delta["removed"])}')
    for p in delta['removed']: print('   - @'+p)
    if delta['renamed']:
        print('Đổi username (cùng ID):')
        for p in delta['renamed']:print('   ~ @'+p['before']+' → @'+p['after'])
    if not delta['verified']:print('Chỉ có thể sử dụng làm đối chiếu tham khảo.')


def export_all(kind='following'):
    kind = check_kind(kind)
    rows=get_rows(config()['target'],kind)
    if not rows:print('Chưa có lịch sử.');return
    ts=datetime.now(TZ).strftime('%Y%m%d_%H%M%S')
    target=config()['target']
    suffix = '_FOLLOWERS' if kind=='followers' else ''
    jfile=BACKUPS/f'{ts}_{target}{suffix}_ALL_HISTORY.json'
    cfile=BACKUPS/f'{ts}_{target}{suffix}_SUMMARY.csv'
    out=[]
    for r in rows:
        d={k:v for k,v in r.items() if k not in {'people_json','added_json','removed_json','renamed_json'}}
        d.update({kind:people_of(r),'new_usernames':json.loads(r['added_json']),
                  'unfollow_usernames':json.loads(r['removed_json']),'renamed':json.loads(r['renamed_json'])})
        out.append(d)
    jfile.write_text(json.dumps({'exported_at':now(),'account':target,'kind':kind,'snapshots':out},ensure_ascii=False,indent=2),encoding='utf-8')
    with cfile.open('w',encoding='utf-8-sig',newline='') as fp:
        w=csv.writer(fp)
        w.writerow(['ID','Ngày kiểm tra','Trạng thái','Số thu được','Số Instagram',
                    'Follower mới' if kind=='followers' else 'Follow mới',
                    'Không còn theo dõi' if kind=='followers' else 'Unfollow',
                    'Danh sách tài khoản mới'])
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
    kind = check_kind(row.get('kind','following'))
    return [BACKUPS / f'{stem}.json',
            BACKUPS / f'{stem}_{kind}.txt',
            BACKUPS / f'{stem}_{kind}.csv']


def _recalculate_history(conn, account, kind='following'):
    """Rebase remaining verified snapshots of the same kind after deletion."""
    kind=check_kind(kind)
    rows = [dict(r) for r in conn.execute(
        'SELECT * FROM snapshots WHERE account=? AND kind=? ORDER BY checked_at,id', (account,kind))]
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


def delete_history_row(account, ident, remove_snapshot_files=True, kind='following'):
    """Delete exactly one snapshot ID of account; preserve other data and session.

    Recompute deltas so later snapshots never reference a deleted ID.
    Existing ALL_HISTORY exports remain unchanged; warn users they contain old data.
    """
    account = name(account)
    kind = check_kind(kind)
    ids = [int(ident)]
    with con() as conn:
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM snapshots WHERE account=? AND kind=? AND id IN (' +
            ','.join('?' for _ in ids) + ')', (account,kind,*ids))]
        if len(rows) != len(ids):
            raise ValueError('Có ID không tồn tại hoặc không thuộc tài khoản đang theo dõi. Chưa xóa gì.')
        conn.executemany('DELETE FROM snapshots WHERE account=? AND kind=? AND id=?', [(account,kind,i) for i in ids])
        changed_ids = _recalculate_history(conn, account,kind)
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


def delete_menu(kind='following'):
    """Only allow deleting one explicit snapshot ID; no bulk-delete path."""
    kind=check_kind(kind)
    account = config()['target']
    rows = get_rows(account,kind)
    if not rows:
        print('Không có lượt kiểm tra nào của tài khoản này để xóa.')
        return
    print('\n'+'='*65)
    print(f'XÓA MỘT LƯỢT {kind_label(kind)} — @{account} ({len(rows)} lượt)')
    print('Nhập ID lượt cần xóa, hoặc 0 để hủy.')
    print('='*65)
    history(kind)
    try:
        ident = int(input('ID lượt muốn xóa (0 = hủy): ').strip())
    except ValueError:
        print('ID không hợp lệ. Không thay đổi dữ liệu.')
        return
    if ident == 0:
        print('Đã hủy, không có thay đổi.')
        return
    row = get_row(ident)
    if not row or row['account'] != account or row['kind'] != kind:
        print('ID không tồn tại trong tài khoản hoặc loại danh sách đang xem. Không thay đổi dữ liệu.')
        return
    print(f'Bạn chọn DUY NHẤT lượt #{ident} — {row["checked_at"]} — {row["found_count"]} username.')
    print('Nếu xóa mốc đã xác minh, các kết quả so sánh sau đó được tính lại.')
    if input(f'Gõ chính xác XOA {ident} để xác nhận: ').strip() != f'XOA {ident}':
        print('Đã hủy, không có thay đổi.')
        return
    print('Chỉ áp dụng cho lượt này; không có chức năng xóa tất cả lịch sử.')
    print('Các file backup JSON/TXT/CSV RIÊNG của lượt này có thể được xóa cùng.')
    remove_files = input('Đưa cả file backup RIÊNG của lượt này ra khỏi thư mục? (y/N): ').strip().lower() == 'y'
    result = delete_history_row(account, ident, remove_files, kind)
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
        print(f"""\n{'='*64}
    INSTAGRAM FOLLOWING & FOLLOWERS TRACKER - TERMINAL
    Theo dõi: {('@'+cfg['target']) if cfg['target'] else '[Chưa chọn — menu 8]'}
    Đăng nhập: @{cfg['login'] or 'chưa có phiên'}
{'='*64}
 --- FOLLOWING: những tài khoản mục tiêu đang theo dõi ---
 1. Kiểm tra Following mới
 2. Xem lịch sử Following
 3. Xem chi tiết + toàn bộ username Following
 4. So sánh hai lần kiểm tra Following
 5. Xuất toàn bộ lịch sử Following (JSON + CSV)
 9. Thử cách lấy Following dự phòng
10. Xóa MỘT lượt Following theo ID
{'-'*64}
 --- FOLLOWERS: những người đang theo dõi tài khoản mục tiêu ---
11. Kiểm tra Followers (tự dùng nguồn dự phòng khi thiếu)
12. Xem lịch sử Followers
13. Xem chi tiết + toàn bộ username Followers
14. So sánh hai lần kiểm tra Followers
15. Xuất toàn bộ lịch sử Followers (JSON + CSV)
16. Thử cách lấy Followers dự phòng
17. Xóa MỘT lượt Followers theo ID
{'-'*64}
 --- CẤU HÌNH ---
 6. Nhập dữ liệu APP CŨ (chỉ Following)
 7. Đăng nhập / làm mới phiên Instagram
 8. Đổi tài khoản cần theo dõi
 0. Thoát
{'='*64}""")
        choice=input('Nhập lựa chọn: ').strip()
        try:
            if choice=='1':do_check('mobile','following')
            elif choice=='2':history('following')
            elif choice=='3':show_detail('following')
            elif choice=='4':compare_menu('following')
            elif choice=='5':export_all('following')
            elif choice=='6':import_legacy()
            elif choice=='7':login(force=True)
            elif choice=='8':change_target()
            elif choice=='9':
                print('Chỉ thử phương thức dự phòng khi kết quả chính thiếu; không tự hợp nhất hai lượt thiếu.')
                if input('Tiếp tục? (y/N): ').strip().lower()=='y':do_check('graphql','following')
            elif choice=='10':delete_menu('following')
            elif choice=='11':do_check('mobile','followers')
            elif choice=='12':history('followers')
            elif choice=='13':show_detail('followers')
            elif choice=='14':compare_menu('followers')
            elif choice=='15':export_all('followers')
            elif choice=='16':
                print('Chỉ thử phương thức dự phòng khi kết quả chính thiếu; không tự hợp nhất hai lượt thiếu.')
                if input('Tiếp tục? (y/N): ').strip().lower()=='y':do_check('graphql','followers')
            elif choice=='17':delete_menu('followers')
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
