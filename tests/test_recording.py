"""Isolated activity boundaries, durable CSV data and authenticated controls."""
import asyncio
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestClient, TestServer
import heartrate_live as live
from hr_recording import ActivityRecorder, Segment, describe_log
from hr_runtime import RuntimeControl


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.r = ActivityRecorder()
        self.r.start(self.root, {'warn': 100})

    def tearDown(self):
        self.r.close()
        self.tmp.cleanup()

    def mark(self, label, game=''):
        return self.r.change(label, game, {'warn': 100}, self.r.status()['segment_id'])

    def test_three_distinct_files_and_exact_boundary_membership(self):
        self.r.write(1000, 70, 69, 1)
        self.mark('game', '测试游戏')
        game_path = self.r.segment.path
        self.r.write(1001, 90, 69, 1)
        self.r.write(1002, 95, 69, 2)
        self.mark('non_game')
        self.r.write(1003, 75, None, 2)
        self.r.close()
        groups = {}
        for p in self.root.glob('*.csv'):
            with p.open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream))
            info = describe_log(p)
            groups[info['activity']] = [int(row['bpm']) for row in rows]
            self.assertEqual(list(rows[0])[:3], ['timestamp', 'iso_time', 'bpm'])
            self.assertEqual(len({row['segment_id'] for row in rows}), 1)
            meta = json.loads(p.with_suffix('.session.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['samples'], len(rows))
            self.assertIsNotNone(meta['ended_at'])
        self.assertEqual(groups, {'unmarked': [70], 'game': [90, 95], 'non_game': [75]})
        self.assertEqual(describe_log(game_path)['game'], '测试游戏')

    def test_stale_second_window_cannot_end_newer_segment(self):
        old = self.r.status()['segment_id']
        self.mark('game')
        with self.assertRaises(RuntimeError):
            self.r.change('non_game', '', {}, old)
        self.assertEqual(self.r.status()['activity'], 'game')

    def test_repeated_same_action_does_not_split_a_segment(self):
        self.mark('game', 'A')
        identity = self.r.status()['segment_id']
        self.mark('game', 'A')
        self.assertEqual(identity, self.r.status()['segment_id'])

    def test_new_file_failure_keeps_old_file_writable(self):
        before = self.r.status()['segment_id']
        with patch.object(Path, 'open', side_effect=PermissionError('synthetic disk error')):
            with self.assertRaises(OSError):
                self.mark('game')
        self.r.write(1000, 72, None, 1)
        self.assertEqual(before, self.r.status()['segment_id'])
        self.assertEqual(self.r.status()['samples'], 1)

    def test_end_metadata_failure_removes_candidate_keeps_old_context(self):
        original = Segment.metadata
        def metadata(segment, reason=None):
            if reason:
                raise PermissionError('synthetic read-only metadata')
            return original(segment, reason)
        with patch.object(Segment, 'metadata', metadata):
            with self.assertRaises(OSError):
                self.mark('game')
        self.assertEqual(self.r.status()['activity'], 'unmarked')
        self.assertEqual(len(list(self.root.glob('*.csv'))), 1)
        self.r.write(1000, 73, None, 1)
        self.assertEqual(self.r.status()['samples'], 1)

    def test_write_failure_is_visible_without_stopping_heart_rate(self):
        with patch.object(Segment, 'write', side_effect=OSError('synthetic full disk')):
            self.r.write(1000, 72, None, 1)
        self.assertIn('写入失败', self.r.status()['error'])

    def test_legacy_logs_are_unknown_and_preserved(self):
        path = self.root/'legacy.csv'
        content = b'timestamp,iso_time,bpm\n1,t,72\n'
        path.write_bytes(content)
        self.assertEqual(describe_log(path), {'samples': 1, 'activity': 'unmarked', 'game': ''})
        self.assertEqual(path.read_bytes(), content)

    def test_restart_does_not_resume_game_label(self):
        self.mark('game', 'A')
        self.r.close()
        self.r.start(self.root, {})
        self.assertEqual(self.r.status()['activity'], 'unmarked')

    def test_invalid_labels_and_multiline_names_are_rejected(self):
        for activity, name in [('bogus', ''), ('game', 'a\nb'), ('game', 'a'*81), ('game', None)]:
            with self.assertRaises(ValueError):
                self.mark(activity, name)

    def test_zero_sample_segment_still_has_label_and_open_boundary(self):
        self.mark('game', 'A')
        self.assertEqual(describe_log(self.r.segment.path)['activity'], 'game')
        meta = json.loads(self.r.segment.meta_path.read_text(encoding='utf-8'))
        self.assertIsNone(meta['ended_at'])
        self.assertIsNone(meta['samples'])


class RecordingApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = patch.object(live, 'PARAMS_FILE', self.root/'params.json')
        self.patch.start()
        self.hub = live.Hub(None, None, 12, 600)
        self.hub.start_csv(self.root/'custom-logs')
        self.runtime = RuntimeControl(self.root, 'http://127.0.0.1:8080', asyncio.Event(), self.hub.publish)
        self.headers = {'X-Control-Token': self.runtime.token}
        self.client = TestClient(TestServer(live.build_app(self.hub, self.runtime)))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.hub.close_csv()
        await self.client.close()
        self.patch.stop()
        self.tmp.cleanup()

    def body(self, label, game=''):
        return {'activity': label, 'game': game, 'expected_segment': self.hub.recording.status()['segment_id']}

    async def test_token_and_same_origin_required(self):
        body = self.body('game')
        self.assertEqual((await self.client.post('/control/recording', json=body)).status, 403)
        self.assertEqual((await self.client.post('/control/recording', json=body, headers={**self.headers, 'Origin':'https://example.invalid'})).status, 403)
        self.assertEqual(self.hub.recording.status()['activity'], 'unmarked')

    async def test_change_broadcasts_without_resetting_baseline_or_stats(self):
        self.hub.set_bpm(82)
        before = (self.hub.samples, self.hub.base_bpm, self.hub.params.copy())
        queue = asyncio.Queue()
        self.hub.queues.add(queue)
        response = await self.client.post('/control/recording', json=self.body('game', 'A'), headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await queue.get())['recording']['activity'], 'game')
        self.assertEqual(before, (self.hub.samples, self.hub.base_bpm, self.hub.params))
        self.assertEqual((await (await self.client.get('/hr')).json())['recording']['activity'], 'game')

    async def test_filters_custom_log_directory_and_replays_only_game_file(self):
        self.hub.set_bpm(70)
        await self.client.post('/control/recording', json=self.body('game', '<script>A</script>'), headers=self.headers)
        for i in range(12):
            with patch.object(live.time, 'time', return_value=1000+i):
                self.hub.set_bpm(80+i)
        await self.client.post('/control/recording', json=self.body('non_game'), headers=self.headers)
        self.hub.set_bpm(72)
        rows = await (await self.client.get('/logs?activity=game')).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['samples'], 12)
        response = await self.client.get('/replay', params={'file': rows[0]['name']})
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual(result['samples'], 12)
        self.assertEqual(result['min'], 80)
        self.assertEqual((await self.client.get('/logs?activity=bad')).status, 400)
        self.assertEqual((await self.client.get('/replay?file=../secret.csv')).status, 400)

    async def test_stale_request_and_shutdown_are_rejected(self):
        body = self.body('game')
        self.assertEqual((await self.client.post('/control/recording', json=body, headers=self.headers)).status, 200)
        self.assertEqual((await self.client.post('/control/recording', json=body, headers=self.headers)).status, 409)
        self.runtime.closing = True
        self.assertEqual((await self.client.post('/control/recording', json=self.body('non_game'), headers=self.headers)).status, 409)

    async def test_no_csv_is_explicitly_unavailable(self):
        self.hub.close_csv()
        self.hub.recording = ActivityRecorder()
        result = await (await self.client.get('/control/recording')).json()
        self.assertFalse(result['available'])
        response = await self.client.post('/control/recording', json=self.body('game'), headers=self.headers)
        self.assertEqual(response.status, 400)


if __name__ == '__main__':
    unittest.main()
