import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'ig_following.py'
spec = importlib.util.spec_from_file_location('ig_following_delete_test',SOURCE)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

class TestDelete(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backup = (t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG)
        t.DATA = Path(self.tmp.name)/'data'
        t.BACKUPS=t.DATA/'backups'
        t.DB_FILE=t.DATA/'history.sqlite3'
        t.SESSION=t.DATA/'instagram_session.json'
        t.CONFIG=t.DATA/'config.json'
        t.SESSION.parent.mkdir(parents=True)
        t.SESSION.write_text('secret-local-session')
        t.save_config({'target':'target','login':'login'})
    def tearDown(self):
        t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG=self.backup
        self.tmp.cleanup()
    def snapshot(self,ids,account='target',at='2026-11-01T10:00:00+07:00',status='verified'):
        return t.save_snapshot(account,target_pk='900',expected=len(ids),
            people=[{'pk':str(i),'username':f'user_{i}'} for i in ids],
            status=status,checked_at=at)
    def test_delete_middle_rebases_later_deltas(self):
        first,b1=self.snapshot([1,2],at='2026-11-01T10:00:00+07:00')
        middle,b2=self.snapshot([1,2,3],at='2026-11-02T10:00:00+07:00')
        last,b3=self.snapshot([1,3,4],at='2026-11-03T10:00:00+07:00')
        self.assertEqual(json.loads(last['added_json']),['user_4'])
        result=t.delete_history_row('target',middle['id'],True)
        self.assertEqual(result['deleted'],1)
        self.assertEqual(result['recalculated'],1)
        self.assertIsNone(t.get_row(middle['id']))
        self.assertFalse(b2.exists())
        self.assertFalse((t.BACKUPS/f'20261102100000_target_check_{middle["id"]}_following.txt').exists())
        after=t.get_row(last['id'])
        self.assertEqual(after['compared_to'],first['id'])
        self.assertEqual(json.loads(after['added_json']),['user_3','user_4'])
        self.assertEqual(json.loads(after['removed_json']),['user_2'])
        self.assertEqual(json.loads(b3.read_text())['new_usernames'],['user_3','user_4'])
        self.assertTrue(t.SESSION.exists())
    def test_delete_first_creates_new_baseline(self):
        first,_=self.snapshot([1],at='2026-11-01T10:00:00+07:00')
        second,b2=self.snapshot([1,2],at='2026-11-02T10:00:00+07:00')
        t.delete_history_row('target',first['id'])
        after=t.get_row(second['id'])
        self.assertIsNone(after['compared_to'])
        self.assertEqual(json.loads(after['added_json']),[])
        self.assertIsNone(json.loads(b2.read_text())['new_follow_count'])
    def test_delete_only_selected_account(self):
        one,_=self.snapshot([1])
        second,_=self.snapshot([5],account='different')
        t.delete_history_row('target',one['id'])
        self.assertFalse(t.get_rows('target'))
        self.assertEqual(len(t.get_rows('different')),1)
        self.assertTrue(t.SESSION.exists())
        self.assertEqual(t.config()['login'],'login')
    def test_refuse_other_account_without_deleting(self):
        a,_=self.snapshot([1]);b,_=self.snapshot([5],account='different')
        with self.assertRaises(ValueError):
            t.delete_history_row('target',b['id'])
        self.assertEqual(len(t.get_rows()),2)
    def test_menu_cancel_and_confirm(self):
        row,_=self.snapshot([1])
        with patch('builtins.input',side_effect=[str(row['id']),'NO']),contextlib.redirect_stdout(io.StringIO()):
            t.delete_menu()
        self.assertIsNotNone(t.get_row(row['id']))
        with patch('builtins.input',side_effect=[str(row['id']),f'XOA {row["id"]}','n']),contextlib.redirect_stdout(io.StringIO()):
            t.delete_menu()
        self.assertIsNone(t.get_row(row['id']))
        self.assertTrue(t.SESSION.exists())
    def test_cancel_zero_does_not_delete(self):
        row,_=self.snapshot([1])
        with patch('builtins.input',side_effect=['0']),contextlib.redirect_stdout(io.StringIO()):
            t.delete_menu()
        self.assertIsNotNone(t.get_row(row['id']))

if __name__=='__main__':unittest.main()
