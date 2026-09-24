import csv
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

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


class ReliabilityPrivacyTests(unittest.TestCase):
    def test_retry_transient_is_bounded_with_capped_backoff(self):
        attempts = []
        sleeps = []

        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise ConnectionError('connection reset by peer')
            return 'ok'

        policy = app.RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.1,
            max_delay_seconds=0.2,
            jitter_seconds=0.0,
        )
        result = app.run_with_bounded_retry(
            operation,
            policy=policy,
            sleep_fn=sleeps.append,
            random_fn=lambda: 0.0,
        )
        self.assertEqual(result, 'ok')
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [0.1, 0.2])

    def test_retry_non_transient_is_not_retried(self):
        attempts = []
        sleeps = []

        def operation():
            attempts.append(1)
            raise ValueError('selector contract changed')

        with self.assertRaises(ValueError):
            app.run_with_bounded_retry(operation, sleep_fn=sleeps.append)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(sleeps, [])

    def test_retry_ambiguous_publish_state_is_not_retried(self):
        attempts = []

        def operation():
            attempts.append(1)
            raise app.AmbiguousPublishStateError('submit unknown')

        with self.assertRaises(app.AmbiguousPublishStateError):
            app.run_with_bounded_retry(operation, sleep_fn=lambda _seconds: None)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(
            app.classify_retry_error(app.AmbiguousPublishStateError('submit unknown')),
            'publish_state_ambiguous',
        )

    def test_structured_jsonl_logging_redacts_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / 'events.jsonl'
            logger = app.JsonlEventLogger(log_path, run_id='run-test')
            self.assertTrue(
                logger.emit(
                    'task_finished',
                    status='failed',
                    token='top-secret-token',
                    session_path='C:/private/session.json',
                    message='Authorization: Bearer super-secret-bearer',
                )
            )
            lines = log_path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload['run_id'], 'run-test')
            self.assertEqual(payload['event'], 'task_finished')
            self.assertEqual(payload['status'], 'failed')
            self.assertEqual(payload['token'], '[REDACTED]')
            self.assertEqual(payload['session_path'], '[REDACTED]')
            self.assertIn('Bearer [REDACTED]', payload['message'])
            self.assertNotIn('top-secret-token', lines[0])
            self.assertNotIn('super-secret-bearer', lines[0])
            self.assertIn('ts', payload)

    def test_save_session_state_is_atomic(self):
        class FakeContext:
            def storage_state(self, *, path):
                Path(path).write_text('{"cookies":[]}', encoding='utf-8')

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            destination = root / 'nested' / 'session.json'
            app.save_session_state(FakeContext(), destination)
            self.assertEqual(destination.read_text(encoding='utf-8'), '{"cookies":[]}')
            self.assertEqual(list(destination.parent.glob('*.tmp')), [])

    def test_default_session_path_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {'LOCALAPPDATA': td}, clear=False):
                expected = Path(td).resolve() / 'WAHU' / 'FacebookPublisher' / 'session.json'
                self.assertEqual(app.default_session_path(), expected)
                self.assertEqual(
                    app.default_event_log_path(),
                    expected.parent / 'logs' / 'events.jsonl',
                )

    def test_wait_until_deadline_has_low_drift(self):
        target = datetime.now() + timedelta(seconds=0.12)
        started = time.perf_counter()
        self.assertTrue(app.wait_until(target))
        elapsed = time.perf_counter() - started
        self.assertGreaterEqual(elapsed, 0.08)
        self.assertLess(elapsed, 0.60)


if __name__ == '__main__':
    unittest.main()
