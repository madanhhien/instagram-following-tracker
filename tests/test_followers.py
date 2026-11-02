"""Offline tests for V5 Followers, history separation, migration and export."""
import contextlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'ig_following.py'
spec = importlib.util.spec_from_file_location('ig_tracker_followers',SCRIPT)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


class FakeClient:
    def __init__(self, followers, expected=None):
        self.groups=followers
        self.expected=expected if expected is not None else len(set(x[0] for pg in followers for x in pg))
        self.calls=[]

    def user_info_by_username(self, username):
        return SimpleNamespace(pk='9090', follower_count=self.expected, following_count=2)

    def user_followers_v1_chunk(self, uid, max_amount=100, max_id=''):
        self.calls.append(('followers_mobile',uid,max_id))
        i=int(max_id or '0')
        pg=self.groups[i]
        return [SimpleNamespace(pk=pk,username=name) for pk,name in pg], str(i+1) if i+1<len(self.groups) else ''

    def user_followers_private_gql_chunk(self, uid, max_amount=100, max_id=None):
        self.calls.append(('followers_graphql',uid,max_id))
        i=int(max_id or '0')
        pg=self.groups[i]
        return [SimpleNamespace(pk=pk,username=name) for pk,name in pg], str(i+1) if i+1<len(self.groups) else ''


class TestFollowers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.saved=t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG
        t.DATA=Path(self.temp.name)/'data'
        t.BACKUPS=t.DATA/'backups'
        t.DB_FILE=t.DATA/'history.sqlite3'
        t.SESSION=t.DATA/'instagram_session.json'
        t.CONFIG=t.DATA/'config.json'
        t.save_config({'target':'testtarget','login':'own_account'})
        t.SESSION.write_text('private session')

    def tearDown(self):
        t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG=self.saved
        self.temp.cleanup()

    def snapshot(self,kind,people,at='2026-11-02T12:00:00+07:00',status='verified'):
        return t.save_snapshot('testtarget',target_pk='9090',expected=len(people),kind=kind,
            people=[{'pk':str(pk),'username':name} for pk,name in people],status=status,checked_at=at)

    def test_history_isolation_and_follower_deltas(self):
        following,_=self.snapshot('following',[(4,'we.follow')])
        f1,_=self.snapshot('followers',[(1,'alpha'),(2,'beta')])
        f2,b2=self.snapshot('followers',[(2,'beta.changed'),(3,'gamma')],at='2026-11-03T12:00:00+07:00')
        self.assertEqual(f2['compared_to'],f1['id'])
        self.assertEqual(json.loads(f2['added_json']),['gamma'])
        self.assertEqual(json.loads(f2['removed_json']),['alpha'])
        self.assertEqual(json.loads(f2['renamed_json']),[{'before':'beta','after':'beta.changed'}])
        self.assertEqual([r['id'] for r in t.get_rows('testtarget','followers')],[f1['id'],f2['id']])
        self.assertEqual([r['id'] for r in t.get_rows('testtarget')],[following['id']])
        self.assertEqual(json.loads(b2.read_text())['new_follower_count'],1)
        self.assertEqual(json.loads(b2.read_text())['lost_follower_count'],1)
        self.assertIn('followers',json.loads(b2.read_text()))
        self.assertIn('gamma',t.export_username_file(f2).read_text())
        self.assertTrue(str(t.export_username_file(f2)).endswith('_followers.txt'))
        self.assertEqual(t.diff(following,f1)['verified'],False)

    def test_partial_followers_cannot_confirm_changes(self):
        f1,_=self.snapshot('followers',[(1,'alpha'),(2,'beta')])
        partial,_=self.snapshot('followers',[(2,'beta')],at='2026-11-03T12:00:00+07:00',status='partial')
        self.assertIsNone(partial['compared_to'])
        self.assertFalse(t.diff(f1,partial)['verified'])
        after,_=self.snapshot('followers',[(2,'beta'),(3,'charlie')],at='2026-11-04T12:00:00+07:00')
        self.assertEqual(after['compared_to'],f1['id'])

    def test_detail_and_comparison_do_not_cross_kinds(self):
        following,_=self.snapshot('following',[(9,'followed')])
        followers,_=self.snapshot('followers',[(1,'follower')])
        with patch('builtins.input',side_effect=[str(following['id'])]),contextlib.redirect_stdout(io.StringIO()) as output:
            t.show_detail('followers')
        self.assertIn('loại danh sách khác',output.getvalue())
        with patch('builtins.input',side_effect=[str(following['id']),str(followers['id'])]),contextlib.redirect_stdout(io.StringIO()) as output:
            t.compare_menu('followers')
        self.assertIn('khác tài khoản / loại danh sách',output.getvalue())

    def test_delete_follower_snapshot_only_rebases_followers(self):
        following,_=self.snapshot('following',[(9,'followed')])
        f1,_=self.snapshot('followers',[(1,'alpha')])
        f2,b2=self.snapshot('followers',[(1,'alpha'),(2,'beta')],at='2026-11-03T12:00:00+07:00')
        f3,b3=self.snapshot('followers',[(1,'alpha'),(2,'beta'),(3,'gamma')],at='2026-11-04T12:00:00+07:00')
        with self.assertRaises(ValueError):
            t.delete_history_row('testtarget', following['id'],kind='followers')
        result=t.delete_history_row('testtarget',f2['id'],kind='followers')
        self.assertEqual(result['deleted'],1)
        self.assertFalse(b2.exists())
        self.assertIsNotNone(t.get_row(following['id']))
        self.assertEqual(t.get_row(f3['id'])['compared_to'],f1['id'])
        self.assertEqual(json.loads(t.get_row(f3['id'])['added_json']),['beta','gamma'])
        self.assertEqual(json.loads(b3.read_text())['new_follower_count'],2)
        self.assertTrue(t.SESSION.exists())

    def test_collection_uses_follower_api_with_pagination(self):
        api=FakeClient([[('1','alpha'),('2','beta')],[('2','beta'),('3','gamma')]],expected=3)
        for method in ('mobile','graphql'):
            with contextlib.redirect_stdout(io.StringIO()):
                people,pages,dupes,error=t.collect_pages(api,'9090',method,'followers')
            self.assertEqual((len(people),pages,dupes,error),(3,2,1,''))
            self.assertEqual(api.calls[-1][0],f'followers_{method}')

    def test_do_check_reads_follower_count_and_saves_kind(self):
        api=FakeClient([[('1','a'),('2','b')]],expected=2)
        with patch.object(t,'login',return_value=api),contextlib.redirect_stdout(io.StringIO()):
            t.do_check(kind='followers')
        self.assertEqual(len(t.get_rows('testtarget','followers')),1)
        row=t.get_rows('testtarget','followers')[0]
        self.assertEqual((row['status'],row['expected_count'],row['found_count']),('verified',2,2))
        self.assertEqual(t.get_rows('testtarget','following'),[])

    def test_do_check_partial_when_api_returns_less(self):
        api=FakeClient([[('1','a')]],expected=2)
        with patch.object(t,'login',return_value=api),contextlib.redirect_stdout(io.StringIO()):
            t.do_check(kind='followers')
        row=t.get_rows('testtarget','followers')[0]
        self.assertEqual(row['status'],'partial')
        self.assertIsNone(row['compared_to'])

    def test_export_followers_and_following_are_separate(self):
        self.snapshot('following',[(8,'outbound')])
        self.snapshot('followers',[(9,'inbound')])
        with contextlib.redirect_stdout(io.StringIO()):
            t.export_all('following')
            t.export_all('followers')
        files=list(t.BACKUPS.glob('*ALL_HISTORY.json'))
        self.assertEqual(len(files),2)
        payloads={json.loads(f.read_text())['kind']:json.loads(f.read_text()) for f in files}
        self.assertEqual(payloads['following']['snapshots'][0]['following'][0]['username'],'outbound')
        self.assertEqual(payloads['followers']['snapshots'][0]['followers'][0]['username'],'inbound')

    def test_zero_followers_verifiable(self):
        first,_=self.snapshot('followers',[])
        second,_=self.snapshot('followers',[(9,'new.follower')],at='2026-11-03T12:00:00+07:00')
        self.assertEqual(second['compared_to'],first['id'])
        self.assertEqual(json.loads(second['added_json']),['new.follower'])

    def test_migrate_existing_following_database(self):
        # Construct exactly the pre-V5 SQL schema and a historical row.
        with sqlite3.connect(t.DB_FILE) as conn:
            conn.executescript('''
            CREATE TABLE snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT NOT NULL,target_pk TEXT,
              checked_at TEXT NOT NULL,expected_count INTEGER,found_count INTEGER NOT NULL,
              status TEXT NOT NULL,source TEXT NOT NULL,page_count INTEGER NOT NULL DEFAULT 0,
              note TEXT NOT NULL DEFAULT '',people_json TEXT NOT NULL,compared_to INTEGER,
              added_json TEXT NOT NULL DEFAULT '[]',removed_json TEXT NOT NULL DEFAULT '[]',
              renamed_json TEXT NOT NULL DEFAULT '[]',origin TEXT UNIQUE
            );
            ''')
            conn.execute('''INSERT INTO snapshots(account,target_pk,checked_at,expected_count,found_count,
                status,source,people_json) VALUES (?,?,?,?,?,?,?,?)''',
                ('testtarget','9090','2026-11-01T12:00:00+07:00',1,1,'verified','instagrapi_mobile',
                 json.dumps([{'pk':'44','username':'old.following'}])))
        with t.db() as conn:
            cols={r[1] for r in conn.execute('PRAGMA table_info(snapshots)')}
        self.assertIn('kind',cols)
        previous=t.get_rows('testtarget','following')
        self.assertEqual(len(previous),1)
        self.assertEqual(previous[0]['kind'],'following')
        self.snapshot('followers',[(1,'follower')])
        self.assertEqual(len(t.get_rows('testtarget','following')),1)
        self.assertEqual(len(t.get_rows('testtarget','followers')),1)
        self.assertTrue(t.SESSION.exists())


if __name__=='__main__':
    unittest.main()
