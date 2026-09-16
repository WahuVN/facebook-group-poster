import csv
import os
import tempfile
import unittest
from pathlib import Path

import fb_group_poster as app


class CoreHelpersTests(unittest.TestCase):
    def test_parse_datetime_supported_and_empty(self):
        self.assertIsNone(app.parse_datetime(''))
        dt = app.parse_datetime('2026-05-05 21:30')
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 5, 5, 21, 30))
        dt2 = app.parse_datetime('05/05/2026 21:30')
        self.assertEqual(dt2, dt)

    def test_parse_datetime_rejects_invalid(self):
        with self.assertRaises(ValueError):
            app.parse_datetime('not-a-date')

    def test_audience_normalization(self):
        self.assertEqual(app.normalize_audience(None), app.AUDIENCE_DEFAULT)
        self.assertEqual(app.normalize_audience('Công khai'), app.AUDIENCE_PUBLIC)
        self.assertEqual(app.normalize_audience('friends'), app.AUDIENCE_FRIENDS)
        self.assertEqual(app.normalize_audience('only-me'), app.AUDIENCE_ONLY_ME)
        self.assertEqual(app.normalize_audience('unknown'), app.AUDIENCE_DEFAULT)

    def test_personal_target_detection(self):
        self.assertTrue(app.is_personal_profile_target('https://www.facebook.com/me'))
        self.assertTrue(app.is_personal_profile_target('https://facebook.com/example.user'))
        self.assertFalse(app.is_personal_profile_target('https://facebook.com/groups/123'))
        self.assertFalse(app.is_personal_profile_target('https://example.com/user'))

    def test_env_bool(self):
        old = os.environ.get('FB_TEST_BOOL')
        try:
            os.environ['FB_TEST_BOOL'] = 'yes'
            self.assertTrue(app.env_bool('FB_TEST_BOOL', False))
            os.environ['FB_TEST_BOOL'] = 'off'
            self.assertFalse(app.env_bool('FB_TEST_BOOL', True))
        finally:
            if old is None:
                os.environ.pop('FB_TEST_BOOL', None)
            else:
                os.environ['FB_TEST_BOOL'] = old

    def test_load_tasks_csv(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media = root / 'sample.mp4'
            media.write_bytes(b'demo')
            csv_path = root / 'posts.csv'
            with csv_path.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['enabled','group_url','video_path','caption','schedule_at','audience'])
                writer.writeheader()
                writer.writerow({'enabled':'1','group_url':'https://facebook.com/groups/123','video_path':'sample.mp4','caption':'Hello\\nWorld','schedule_at':'','audience':'public'})
            tasks = app.load_tasks(csv_path)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].video_path, media.resolve())
            self.assertEqual(tasks[0].caption, 'Hello\nWorld')
            self.assertEqual(tasks[0].audience, app.AUDIENCE_PUBLIC)


if __name__ == '__main__':
    unittest.main()
