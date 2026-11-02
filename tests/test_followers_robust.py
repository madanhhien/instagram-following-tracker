"""Regression tests for the V6 limited-list fallback and cautious verification."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'ig_following.py'
spec = importlib.util.spec_from_file_location('ig_tracker_v6',SCRIPT)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def u(i):
    return SimpleNamespace(pk=str(i),username=f'user_{i}')


class FakeAPI:
    def __init__(self, first, second_pages=None, count=3, after_count=None, high_level_error=None):
        self.first = first
        self.second_pages = second_pages if second_pages is not None else [list(first)]
        self.count=count
        self.after_count=after_count
        self.error=high_level_error
        self.high_calls=0
        self.graphql_calls=0
        self.metadata_calls=0

    def user_followers(self, user_id, amount=0):
        self.high_calls+=1
        if self.error:
            raise self.error
        return {int(x.pk):x for x in self.first}

    def user_followers_private_gql_chunk(self, user_id, max_amount=100, max_id=None):
        self.graphql_calls+=1
        page=int(max_id or 0)
        result=self.second_pages[page]
        next_cursor=str(page+1) if page+1<len(self.second_pages) else ''
        return result,next_cursor

    def user_info_by_username(self, username):
        self.metadata_calls+=1
        count=(self.after_count if self.after_count is not None and self.metadata_calls>1 else self.count)
        return SimpleNamespace(pk='9090',follower_count=count,following_count=1)


class V6Followers(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.orig=t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG
        t.DATA=Path(self.tmp.name)/'data'
        t.BACKUPS=t.DATA/'backups'
        t.DB_FILE=t.DATA/'history.sqlite3'
        t.SESSION=t.DATA/'instagram_session.json'
        t.CONFIG=t.DATA/'config.json'
        t.save_config({'target':'testtarget','login':'own_account'})

    def tearDown(self):
        t.DATA,t.BACKUPS,t.DB_FILE,t.SESSION,t.CONFIG=self.orig
        self.tmp.cleanup()

    def run_check(self, api):
        with patch.object(t,'login',return_value=api),contextlib.redirect_stdout(io.StringIO()):
            t.do_check(kind='followers')
        return t.get_rows('testtarget','followers')[-1]

    def test_high_level_complete_skips_extra_queries(self):
        api=FakeAPI([u(1),u(2),u(3)])
        row=self.run_check(api)
        self.assertEqual((row['status'],row['found_count']),('verified',3))
        self.assertEqual(row['source'],'instagrapi_auto')
        self.assertEqual((api.high_calls,api.graphql_calls,api.metadata_calls),(1,0,2))

    def test_library_limited_graphql_complete_is_usable(self):
        api=FakeAPI([u(1),u(2)],[[u(1),u(2)],[u(3)]])
        row=self.run_check(api)
        self.assertEqual((row['status'],row['found_count']),('verified',3))
        self.assertEqual(row['source'],'instagrapi_private_gql')
        self.assertEqual(api.graphql_calls,2)

    def test_union_same_as_count_stays_partial(self):
        api=FakeAPI([u(1),u(2)],[[u(2),u(3)]])
        row=self.run_check(api)
        self.assertEqual((row['status'],row['found_count']),('partial',3))
        self.assertIsNone(row['compared_to'])
        self.assertIn('KHÔNG dùng hợp nhất để xác minh',row['note'])
        self.assertEqual(json.loads(row['people_json']),
                         [{'pk':'1','username':'user_1'},
                          {'pk':'2','username':'user_2'},
                          {'pk':'3','username':'user_3'}])

    def test_two_sources_disagree_mark_partial(self):
        api=FakeAPI([u(1),u(2)],[[u(1),u(3),u(4)]])
        row=self.run_check(api)
        self.assertEqual(row['status'],'partial')
        self.assertIn('không nhất quán',row['note'])

    def test_profile_count_moves_mark_partial(self):
        api=FakeAPI([u(1),u(2),u(3)],count=3,after_count=4)
        row=self.run_check(api)
        self.assertEqual(row['status'],'partial')
        self.assertIn('Hồ sơ thay đổi',row['note'])

    def test_checkpoint_halts_all_automatic_fallback(self):
        class ChallengeRequired(Exception): pass
        api=FakeAPI([],high_level_error=ChallengeRequired('checkpoint'))
        row=self.run_check(api)
        self.assertEqual(row['status'],'partial')
        self.assertEqual(api.graphql_calls,0)
        self.assertEqual(api.metadata_calls,1)

    def test_non_restriction_error_tries_alternative(self):
        api=FakeAPI([],[[u(1),u(2),u(3)]],high_level_error=RuntimeError('temporary'))
        row=self.run_check(api)
        self.assertEqual(row['status'],'verified')
        self.assertEqual(row['source'],'instagrapi_private_gql')

    def test_following_function_not_modified(self):
        self.assertEqual(t.check_kind('following'),'following')
        self.assertEqual(t.kind_label('following'),'Following')


if __name__=='__main__':
    unittest.main()
