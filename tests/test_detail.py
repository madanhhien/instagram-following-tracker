import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'ig_following.py'
spec=importlib.util.spec_from_file_location('ig_following_detail',SCRIPT)
t=importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

class DetailTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original=(t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG)
        t.DATA=Path(self.temp.name)/'data'
        t.BACKUPS=t.DATA/'backups'
        t.DB_FILE=t.DATA/'history.sqlite3'
        t.SESSION=t.DATA/'session.json'
        t.CONFIG=t.DATA/'config.json'
    def tearDown(self):
        t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG=self.original
        self.temp.cleanup()
    def test_partial_snapshot_shows_all_usernames_and_auto_txt(self):
        row, backup=t.save_snapshot(t.DEFAULT_TARGET,target_pk='123',expected=4,
            people=[{'pk':'11','username':'first.test'}, {'pk':'22','username':'second.test'},
                    {'pk':'33','username':'third.test'}],status='partial',checked_at='2026-11-01T12:42:38+07:00')
        txt=t.BACKUPS / f'20261101124238_{t.DEFAULT_TARGET}_check_{row["id"]}_following.txt'
        self.assertTrue(txt.exists())
        content=txt.read_text(encoding='utf-8')
        self.assertIn('first.test',content)
        self.assertIn('second.test',content)
        self.assertIn('third.test',content)
        self.assertIn('KHÔNG PHẢI THỨ TỰ FOLLOW THEO THỜI GIAN',content)
        out=io.StringIO()
        with patch('builtins.input',side_effect=[str(row['id']),'n']),contextlib.redirect_stdout(out):
            t.show_detail()
        display=out.getvalue()
        self.assertIn('TOÀN BỘ 3 USERNAME',display)
        self.assertIn('@first.test',display)
        self.assertIn('@second.test',display)
        self.assertIn('@third.test',display)
        self.assertIn('CHƯA THỂ KẾT LUẬN',display)
        self.assertIn('BẢN GHI CHƯA ĐẦY ĐỦ',display)
    def test_csv_export_contains_all_and_header(self):
        row,_=t.save_snapshot(t.DEFAULT_TARGET,target_pk='123',expected=2,
            people=[{'pk':'11','username':'alpha'},{'pk':'22','username':'beta'}],status='verified')
        csv_path=t.export_username_file(row,'csv')
        content=csv_path.read_text(encoding='utf-8-sig')
        self.assertIn('Instagram ID',content)
        self.assertIn('alpha',content)
        self.assertIn('beta',content)

if __name__=='__main__':unittest.main()
