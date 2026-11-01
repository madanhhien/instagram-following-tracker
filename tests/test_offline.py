import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPT=Path(__file__).resolve().parents[1]/'ig_following.py'
spec=importlib.util.spec_from_file_location('ig_following',SCRIPT)
t=importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

class DummyAPI:
    def __init__(self, batches):self.batches=batches
    def user_following_v1_chunk(self,uid,max_amount=100,max_id=''):
        i=int(max_id or '0')
        return self.batches[i], str(i+1) if i<len(self.batches)-1 else ''

class TestTracker(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        p=Path(self.tmp.name)
        self.old=(t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG)
        t.DATA=p/'data';t.BACKUPS=t.DATA/'backups';t.DB_FILE=t.DATA/'history.sqlite3';t.SESSION=t.DATA/'sess.json';t.CONFIG=t.DATA/'config.json'
        t.dirs()
    def tearDown(self):
        t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG=self.old
        self.tmp.cleanup()
    def _user(self,uid):
        return SimpleNamespace(pk=uid,username=f'test_{uid}')
    def test_imported_legacy_never_counts_as_follow(self):
        old, path=t.save_snapshot('target',expected=3,people=['test_1','test_2'],status='legacy',source='screenshots')
        newer, path2=t.save_snapshot('target',target_pk='12',expected=3,people=[{'pk':str(i),'username':f'test_{i}'} for i in [1,2,3]],status='verified')
        self.assertIsNone(newer['compared_to'])
        self.assertEqual(json.loads(newer['added_json']),[])
        self.assertTrue(path2.is_file())
        self.assertIsNone(json.loads(path2.read_text())['new_follow_count'])
    def test_verified_snapshots_compute_delta_and_username_rename(self):
        old,_=t.save_snapshot('target',target_pk='12',expected=3,people=[{'pk':str(i),'username':f'test_{i}'} for i in [1,2,3]],status='verified')
        b=[{'pk':'2','username':'test_2new'},{'pk':'3','username':'test_3'},{'pk':'4','username':'test_4'}]
        new,path=t.save_snapshot('target',target_pk='12',expected=3,people=b,status='verified')
        self.assertEqual(new['compared_to'],old['id'])
        self.assertEqual(json.loads(new['added_json']),['test_4'])
        self.assertEqual(json.loads(new['removed_json']),['test_1'])
        self.assertEqual(json.loads(new['renamed_json']),[{'before':'test_2','after':'test_2new'}])
        backup=json.loads(path.read_text())
        self.assertEqual(backup['new_follow_count'],1)
        self.assertEqual(backup['new_usernames'],['test_4'])
    def test_partial_does_not_replace_last_verified(self):
        old,_=t.save_snapshot('target',target_pk='12',expected=2,people=[{'pk':'1','username':'test_1'},{'pk':'2','username':'test_2'}],status='verified')
        partial,_=t.save_snapshot('target',target_pk='12',expected=3,people=[{'pk':'1','username':'test_1'}],status='partial')
        self.assertIsNone(partial['compared_to'])
        new,_=t.save_snapshot('target',target_pk='12',expected=3,people=[{'pk':str(i),'username':f'test_{i}'} for i in [1,2,3]],status='verified')
        self.assertEqual(new['compared_to'],old['id'])
    def test_collect_pagination_overlap(self):
        b=[[self._user(i) for i in [1,2,3]],[self._user(i) for i in [3,4,5]]]
        people,pages,duplicates,error=t.collect_pages(DummyAPI(b),'111')
        self.assertEqual(len(people),5);self.assertEqual(pages,2)
        self.assertEqual(duplicates,1);self.assertFalse(error)
    def test_separate_backup_per_check(self):
        one,b1=t.save_snapshot('target',target_pk='5',expected=1,people=[{'pk':'1','username':'test_1'}],status='verified')
        two,b2=t.save_snapshot('target',target_pk='5',expected=1,people=[{'pk':'1','username':'test_1'}],status='verified')
        self.assertNotEqual(b1,b2)
        self.assertEqual(json.loads(b2.read_text())['new_follow_count'],0)

if __name__=='__main__': unittest.main()
