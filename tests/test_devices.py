import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestClient, TestServer
import heartrate_live as live
from hr_devices import DeviceManager, device_id
from hr_runtime import RuntimeControl
from _ble_fakes import Radio


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(.005)
    await asyncio.wait_for(wait(), 1.5)


class DeviceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'devices.json'
        self.params = patch.object(live, 'PARAMS_FILE', Path(self.tmp.name) / 'params.json')
        self.params.start()
        self.hub = live.Hub(None, None, 12, 600)
        self.radio = Radio()
        self.switches = []
        self.manager = DeviceManager(self.hub, self.path, live.parse_bpm, scanner=self.radio,
                                     client_factory=self.radio.client, on_switch=lambda: self.switches.append(True))

    async def asyncTearDown(self):
        await self.manager.close()
        self.params.stop()
        self.tmp.cleanup()

    async def scan(self):
        await self.manager.action({'action': 'scan'})
        await self.manager.scan_task

    async def connect(self, address='test-one'):
        await self.manager.action({'action': 'connect', 'id': device_id(address)})
        await until(lambda: self.manager.state in ('waiting', 'unsupported', 'retrying'))

    async def test_new_user_requires_selection_and_does_not_probe_neighbors(self):
        stop = asyncio.Event();stop.set()
        await self.manager.run(stop)
        self.assertEqual(self.radio.scan_calls, 0)
        self.assertEqual(self.radio.finds, [])

    async def test_scan_lists_unadvertised_candidates_without_connecting(self):
        await self.scan()
        rows = self.manager.status()['devices']
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(row['heart_rate'] for row in rows), 1)
        self.assertEqual(self.radio.clients, [])
        self.assertNotIn('test-one', json.dumps(rows))

    async def test_duplicate_scan_is_one_radio_task_and_can_be_stopped(self):
        self.radio.scan_delay = 10
        await asyncio.gather(*(self.manager.action({'action':'scan'}) for _ in range(4)))
        await asyncio.sleep(.01)
        self.assertEqual(self.radio.scan_calls, 1)
        await self.manager.action({'action':'stop-scan'})
        self.assertFalse(self.manager.status()['scanning'])

    async def test_scan_failure_is_visible_and_a_second_scan_recovers(self):
        self.radio.scan_error = True
        await self.scan()
        self.assertIn('开启电脑蓝牙', self.manager.scan_error)
        self.radio.scan_error = False
        await self.scan()
        self.assertFalse(self.manager.scan_error)

    async def test_unadvertised_heart_rate_device_connects_and_remembers(self):
        await self.scan();await self.connect('test-two')
        self.assertTrue(self.hub.connected)
        self.assertEqual(self.manager.state, 'waiting')
        self.radio.clients[-1].emit(82)
        self.assertEqual(self.hub.snapshot()['bpm'], 82)
        self.assertEqual(self.manager.state, 'connected')
        data = json.loads(self.path.read_text())
        self.assertEqual(data['selected'], 'test-two')
        self.assertTrue(data['auto_connect'])

    async def test_unsupported_device_is_not_remembered_or_retried(self):
        await self.scan();await self.connect('test-speaker')
        self.assertEqual(self.manager.state, 'unsupported')
        self.assertFalse(self.hub.connected)
        self.assertIn('标准心率服务', self.manager.error)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.radio.active, 0)

    async def test_switch_resets_person_baseline_stats_and_ignores_old_callbacks(self):
        await self.scan();await self.connect()
        old = self.radio.clients[-1]
        old.emit(82)
        self.hub.baseline.value = 80
        self.hub.base_bpm = 80
        await self.connect('test-two')
        self.assertIsNone(self.hub.base_bpm)
        self.assertEqual(self.hub.samples, 0)
        self.assertEqual(len(self.hub.history), 0)
        old.emit(99)
        self.assertIsNone(self.hub.bpm)
        self.radio.clients[-1].emit(72)
        self.assertEqual(self.hub.bpm, 72)
        self.assertEqual(self.radio.max_active, 1)

    async def test_unknown_selection_is_rejected_without_dropping_current_device(self):
        await self.scan();await self.connect()
        with self.assertRaises(ValueError):
            await self.manager.action({'action': 'connect', 'id': 'unknown'})
        self.assertTrue(self.hub.connected)
        self.assertEqual(self.radio.active, 1)

    async def test_repeated_connect_reuses_one_client(self):
        await self.scan()
        await asyncio.gather(*(self.manager.action({'action':'connect','id':device_id('test-one')}) for _ in range(4)))
        await until(lambda: self.manager.state == 'waiting')
        self.assertEqual(len(self.radio.clients), 1)

    async def test_manual_disconnect_persists_and_does_not_auto_select_other_devices(self):
        await self.scan();await self.connect()
        await self.manager.action({'action':'disconnect'})
        self.assertFalse(self.hub.connected)
        self.assertIsNone(self.hub.bpm)
        self.assertEqual(self.radio.active, 0)
        fresh = DeviceManager(self.hub, self.path, live.parse_bpm, scanner=self.radio, client_factory=self.radio.client)
        self.assertIsNone(fresh.target)
        self.assertEqual(fresh.known, ['test-one'])
        await fresh.close()

    async def test_forget_selected_device_disconnects_and_removes_memory(self):
        await self.scan();await self.connect()
        await self.manager.action({'action':'forget','id':device_id('test-one')})
        self.assertFalse(self.hub.connected)
        self.assertEqual(json.loads(self.path.read_text())['addresses'], [])
        self.assertIsNone(self.manager.target)

    async def test_old_addresses_file_migrates_without_losing_history(self):
        self.path.write_text(json.dumps({'addresses':['test-one','test-two']}))
        fresh = DeviceManager(self.hub, self.path, live.parse_bpm, scanner=self.radio, client_factory=self.radio.client)
        self.assertEqual(fresh.target, 'test-one')
        self.assertEqual(fresh.known, ['test-one','test-two'])
        await fresh.close()

    async def test_scanning_while_connected_keeps_readings_and_one_client(self):
        await self.scan();await self.connect()
        current = self.radio.clients[-1]
        await self.scan();current.emit(81)
        self.assertTrue(self.hub.connected)
        self.assertEqual(self.hub.bpm, 81)
        self.assertEqual(self.radio.active, 1)

    async def test_malformed_notifications_do_not_become_heart_rate(self):
        await self.scan();await self.connect()
        self.radio.clients[-1].callback(None, bytearray())
        self.assertIsNone(self.hub.bpm)
        self.assertEqual(self.hub.samples, 0)

    async def test_connection_error_retries_only_selected_source(self):
        await self.scan();self.radio.connect_error = True
        await self.connect()
        self.assertEqual(self.manager.state, 'retrying')
        self.assertIn('所选设备', self.manager.error)
        self.assertEqual(self.radio.scan_calls, 1)
        self.assertFalse(self.path.exists())

    async def test_persistence_failure_is_visible_and_does_not_fake_disconnect(self):
        self.manager.path = Path(self.tmp.name) / 'missing' / 'devices.json'
        await self.scan();await self.connect()
        self.assertTrue(self.hub.connected)
        self.assertIn('记住设备失败', self.manager.storage_error)

    async def test_device_api_guards_and_public_stream_has_no_device_identity(self):
        stop = asyncio.Event()
        rt = RuntimeControl(self.tmp.name, '', stop, self.hub.publish)
        self.hub.devices = self.manager
        async with TestClient(TestServer(live.build_app(self.hub, rt))) as client:
            r = await client.post('/control/devices', json={'action':'scan'})
            self.assertEqual(r.status, 403)
            r = await client.get('/control/devices', headers={'Origin':'https://unrelated.invalid'})
            self.assertEqual(r.status, 403)
            headers = {'X-Control-Token':rt.token}
            r = await client.post('/control/devices', headers=headers, json={'action':'scan'})
            self.assertEqual(r.status, 200)
            await self.manager.scan_task
            r = await client.get('/control/devices')
            data = await r.json();self.assertEqual(len(data['devices']), 3)
            self.assertNotIn('test-one', json.dumps(data))
            public = await (await client.get('/hr')).json()
            self.assertNotIn('devices', public)
            self.assertNotIn('test-one', json.dumps(public))
            for body in [[], {'action':'bad'}, {'action':'connect','id':'bad'}]:
                r = await client.post('/control/devices',headers=headers,json=body)
                self.assertEqual(r.status, 400)
            r = await client.get('/devices',allow_redirects=False)
            self.assertEqual(r.headers['Location'], '/console#devices')
        await rt.close()


if __name__ == '__main__':
    unittest.main()
