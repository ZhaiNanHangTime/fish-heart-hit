"""Synthetic regression checks. No BLE or physiological validation."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestClient, TestServer
import heartrate_live as live
from hr_baseline import Baseline
from hr_config import DEFAULT_PARAMS, merge_params
from hr_client import SnapshotClient
import replay_check

class BaselineTests(unittest.TestCase):
    def test_initial_activity_does_not_permanently_lock_high(self):
        baseline = Baseline()
        for t in range(180): baseline.add(t, 93)
        self.assertEqual(baseline.value, 93)
        for t in range(180, 780): baseline.add(t, 72)
        self.assertLess(baseline.value, 72.1)

    def test_calibration_requires_coverage_stability_and_no_gaps(self):
        b = Baseline()
        for t in range(59): b.add(t,72)
        self.assertFalse(b.calibrate(58)[0])
        for t in range(59,66): b.add(t,72)
        self.assertTrue(b.calibrate(65)[0])
        b.add(66,80)
        self.assertFalse(b.calibrate(66)[0])
        b = Baseline()
        for t in [*range(30), *range(40,76)]: b.add(t,72)
        self.assertFalse(b.calibrate(75)[0])

    def test_bad_parameters_rejected_without_mutation(self):
        for data in [[], {'anchorTau':0}, {'minGap':40}, {'fxKick':1}, {'skin':'bad'}, {'attack':float('nan')}, {'traceLayout':'bad'}, {'traceLayout':True}, {'traceLayout':None}, {'hudWidth':159}, {'hudHeight':1081}, {'fishScale':4.1}, {'hudWidth':True}, {'hudWidth':210.5}]:
            with self.assertRaises((ValueError,TypeError)):
                merge_params(DEFAULT_PARAMS,data)
        self.assertEqual(DEFAULT_PARAMS['minGap'],22)

    def test_hud_dimensions_are_independent_of_obs_dimensions(self):
        params=merge_params(DEFAULT_PARAMS,{'hudWidth':211,'hudHeight':119})
        self.assertEqual((params['hudWidth'],params['hudHeight']),(211,119))
        self.assertEqual((params['viewWidth'],params['viewHeight']),(520,170))

    def test_replay_uses_new_baseline_and_per_call_parameters(self):
        rows=[(t,72 if t<80 else 90) for t in range(120)]
        before=dict(replay_check.P)
        result=replay_check.replay(rows,params={**DEFAULT_PARAMS,'burstAbove':10})
        self.assertEqual(result['baseline_mode'],'rolling-p25')
        self.assertGreaterEqual(result['burst'],1)
        self.assertEqual(replay_check.P,before)

class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.mock=patch.object(live,'PARAMS_FILE',Path(self.temp.name)/'params.json')
        self.mock.start()
        self.hub=live.Hub(None,None,12,600)
        self.client=TestClient(TestServer(live.build_app(self.hub)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.mock.stop()
        self.temp.cleanup()

    async def test_hud_resize_persists_with_version_ack_without_changing_obs_or_skin(self):
        before=dict(self.hub.params)
        response=await self.client.post('/params',json={'hudWidth':220,'hudHeight':120})
        self.assertEqual(response.status,200)
        self.assertEqual(int(response.headers['X-Params-Version']),self.hub.params_version)
        saved=live.load_params()
        self.assertEqual((saved['hudWidth'],saved['hudHeight']),(220,120))
        for key in ('viewWidth','viewHeight','skin','burstRise','burstAbove'):
            self.assertEqual(saved[key],before[key])

    async def test_routes_assets_guard_and_no_traversal(self):
        for path in ['/', '/pixel.html','/console','/monitor','/effects','/test','/tune','/plain','/params/schema','/live.js']:
            response=await self.client.get(path)
            self.assertEqual(response.status,200,path)
            await response.read()
        for name in ['idle','alert_low','alert_mid','tense','high','charge','burst','recover']:
            response=await self.client.get('/assets/skins/xianyu/'+name+'.png')
            self.assertEqual(response.status,200)
            self.assertEqual(response.content_type,'image/png')
            await response.read()
        for path in ['/assets/','/assets/..%2fheartrate_live.py','/assets/%2e%2e/heartrate_live.py']:
            response=await self.client.get(path)
            self.assertIn(response.status,[403,404])
        with patch.object(live,'HERE',Path(self.temp.name)):
            live.build_app(self.hub)  # missing assets must not prevent startup

    async def test_immediate_config_broadcast_even_without_sensor(self):
        stream=await self.client.get('/events')
        async def event():
            while True:
                line=await asyncio.wait_for(stream.content.readline(),2)
                if line.startswith(b'data:'):
                    import json
                    return json.loads(line[5:])
        initial=await event()
        response=await self.client.post('/params',json={'skin':'xianyu','fxKick':False,'fishScale':1.2,'traceLayout':'lower'})
        self.assertEqual(response.status,200)
        snap=await event()
        self.assertEqual(snap['params_version'],initial['params_version']+1)
        self.assertEqual(snap['params']['fishScale'],1.2)
        self.assertFalse(snap['params']['fxKick'])
        self.assertEqual(snap['skin'],'xianyu')
        self.assertEqual(snap['params']['traceLayout'],'lower')
        self.assertFalse(snap['connected'])
        self.assertEqual(live.load_params()['skin'],'xianyu')
        self.assertEqual(live.load_params()['traceLayout'],'lower')
        response=await self.client.post('/params',json={'anchorTau':0})
        self.assertEqual(response.status,400)
        self.assertEqual(self.hub.params_version,snap['params_version'])
        stream.close()

    async def test_stdlib_client_receives_same_snapshot_and_reconnects(self):
        feed=SnapshotClient(str(self.client.make_url('')).rstrip('/'))
        try:
            for _ in range(60):
                if feed.latest().get('params_version'): break
                await asyncio.sleep(.05)
            initial = feed.latest()['params_version']
            self.assertGreater(initial,0)
            await self.client.post('/params',json={'skin':'ghost'})
            for _ in range(60):
                if feed.latest().get('skin')=='ghost': break
                await asyncio.sleep(.05)
            self.assertEqual(feed.latest()['params_version'],initial+1)
        finally:
            await asyncio.to_thread(feed.close)

    async def test_calibration_failure_and_reset_clear_base(self):
        response=await self.client.post('/calibrate')
        self.assertEqual(response.status,409)
        self.hub.baseline.value=93
        self.hub.base_bpm=93
        await self.client.post('/reset')
        self.assertIsNone(self.hub.snapshot()['base'])

    async def test_all_channels_apply_saved_offline_timeout(self):
        self.hub.connected = True
        self.hub.bpm = 82
        self.hub.updated_at = time.time() - 6
        self.assertIsNone(self.hub.snapshot()['bpm'])
        await self.client.post('/params',json={'offlineAfter':8})
        self.assertEqual(self.hub.snapshot()['bpm'],82)

    async def test_sse_heartbeat_keeps_service_live_without_sensor(self):
        stream=await self.client.get('/events')
        try:
            async def event():
                while True:
                    line=await asyncio.wait_for(stream.content.readline(),3)
                    if line.startswith(b'data:'):
                        import json
                        return json.loads(line[5:])
            initial=await event();heartbeat=await event()
            self.assertIsNone(heartbeat['bpm'])
            self.assertFalse(heartbeat['connected'])
            self.assertEqual(heartbeat['params_version'],initial['params_version'])
        finally:stream.close()

if __name__=='__main__': unittest.main()
