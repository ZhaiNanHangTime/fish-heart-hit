"""One selected BLE heart-rate source, with local visual discovery and controls."""
import asyncio
import contextlib
import hashlib
import json
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

HR_MEASUREMENT = '00002a37-0000-1000-8000-00805f9b34fb'
BATTERY_LEVEL = '00002a19-0000-1000-8000-00805f9b34fb'


class UnsupportedDevice(Exception):
    pass


def device_id(address):
    return hashlib.sha256(address.casefold().encode()).hexdigest()[:20]


class DeviceManager:
    def __init__(self, hub, path, parse_bpm, address=None, name=None,
                 scanner=BleakScanner, client_factory=BleakClient, on_switch=None):
        self.hub, self.path, self.parse_bpm = hub, Path(path), parse_bpm
        self.scanner, self.client_factory, self.on_switch = scanner, client_factory, on_switch
        self.name_filter = name
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, list):
            data = {'addresses': data}
        if not isinstance(data, dict):
            data = {}
        values = data.get('addresses', [])
        self.known = list(dict.fromkeys(a for a in values if isinstance(a, str) and 0 < len(a) <= 128))[:5] if isinstance(values, list) else []
        self.names = {k: v[:120] for k, v in data.get('names', {}).items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data.get('names'), dict) else {}
        self.auto_connect = data.get('auto_connect', True) is True
        saved = data.get('selected')
        self.target = address or (None if name or not self.auto_connect else saved if saved in self.known else next(iter(self.known), None))
        if address:
            self.auto_connect = True
        self.devices = {}
        self.connection_task = self.scan_task = None
        self.state, self.error, self.scan_error, self.storage_error = 'idle', '', '', ''
        self.scanned_at, self.generation, self.revision = None, 0, 0
        self.closing = False
        self.radio_lock, self.action_lock = asyncio.Lock(), asyncio.Lock()

    def changed(self):
        self.revision += 1
        self.hub.publish()

    def _save(self):
        data = {'addresses': self.known, 'selected': self.target if self.target in self.known else None,
                'auto_connect': self.auto_connect, 'names': {a: self.names.get(a, '') for a in self.known}}
        try:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(self.path)
            self.storage_error = ''
        except OSError:
            self.storage_error = '设备已可操作，但记住设备失败；请检查目录写入权限。'

    def _addresses(self):
        return set(self.devices) | set(self.known) | ({self.target} if self.target else set())

    def _resolve(self, key):
        for address in self._addresses():
            if device_id(address) == key:
                return address
        raise ValueError('设备不在当前列表中，请重新扫描。')

    def status(self):
        rows = []
        for address in self._addresses():
            found = self.devices.get(address, {})
            rows.append({'id': device_id(address), 'name': found.get('name') or self.names.get(address) or '未命名蓝牙设备',
                         'suffix': address.replace(':', '').replace('-', '')[-4:], 'rssi': found.get('rssi'),
                         'heart_rate': found.get('heart_rate', False), 'seen': address in self.devices,
                         'remembered': address in self.known, 'selected': address == self.target})
        rows.sort(key=lambda row: (not row['selected'], not row['heart_rate'], not row['remembered'], -(row['rssi'] if row['rssi'] is not None else -999), row['id']))
        return {'available': True, 'revision': self.revision, 'scanning': bool(self.scan_task and not self.scan_task.done()),
                'state': self.state, 'error': self.error, 'scan_error': self.scan_error, 'storage_error': self.storage_error,
                'scanned_at': self.scanned_at, 'auto_connect': self.auto_connect, 'devices': rows,
                'selected_id': device_id(self.target) if self.target else None}

    async def _cancel(self, task):
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError as exc:
                raise ValueError('蓝牙仍在释放连接，请稍后重试。') from exc

    def _clear_reading(self):
        self.hub.connected = False
        self.hub.bpm = None
        self.hub.updated_at = 0
        self.hub.battery = None
        self.hub.battery_at = 0

    async def start_scan(self):
        if self.scan_task and not self.scan_task.done():
            return
        self.scan_error = ''
        self.scan_task = asyncio.create_task(self._scan(), name='visual-ble-scan')
        self.changed()

    async def _scan(self):
        try:
            async with self.radio_lock:
                found = await asyncio.wait_for(self.scanner.discover(timeout=8.0, return_adv=True), timeout=15)
            devices = {}
            for address, (device, adv) in found.items():
                uuids = [str(u).lower() for u in (adv.service_uuids or [])]
                devices[address] = {'device': device, 'name': (adv.local_name or device.name or '')[:120],
                                    'rssi': adv.rssi, 'heart_rate': any(u in ('180d', '0000180d-0000-1000-8000-00805f9b34fb') for u in uuids)}
            self.devices = devices
            self.scanned_at = time.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.scan_error = '扫描失败：请开启电脑蓝牙，确认蓝牙适配器可用，再重新扫描。'
        finally:
            # status() is read after this task finishes, so scanning never sticks on.
            self.changed()

    async def connect(self, key):
        address = self._resolve(key)
        if address == self.target and self.connection_task and not self.connection_task.done():
            return
        await self._cancel(self.scan_task)
        self.generation += 1
        await self._cancel(self.connection_task)
        previous = self.target
        self.target, self.auto_connect = address, True
        self._clear_reading()
        if previous != address:
            self.hub.visual_stage = 0
            self.hub.reset_session()
            if self.on_switch:
                self.on_switch()
        self.state, self.error = 'connecting', ''
        self.connection_task = asyncio.create_task(self._connection_loop(address, self.generation), name='selected-ble-device')
        self.changed()

    async def disconnect(self):
        self.generation += 1
        await self._cancel(self.connection_task)
        self.connection_task = None
        self._clear_reading()
        self.state, self.error, self.auto_connect = 'idle', '', False
        self._save()
        self.changed()

    async def action(self, body):
        if not isinstance(body, dict):
            raise ValueError('无效的设备操作。')
        async with self.action_lock:
            if self.closing:
                raise ValueError('本次运行正在结束。')
            action = body.get('action')
            if action == 'scan':
                await self.start_scan()
            elif action == 'stop-scan':
                await self._cancel(self.scan_task)
                self.changed()
            elif action == 'connect':
                await self.connect(body.get('id'))
            elif action == 'disconnect':
                await self.disconnect()
            elif action == 'forget':
                address = self._resolve(body.get('id'))
                if address == self.target:
                    await self.disconnect()
                    self.target = None
                self.known = [a for a in self.known if a != address]
                self.names.pop(address, None)
                self._save()
                self.changed()
            else:
                raise ValueError('无效的设备操作。')
        return self.status()

    async def _connection_loop(self, address, generation):
        backoff = 2
        while not self.closing and generation == self.generation:
            try:
                self.state = 'connecting'
                self.changed()
                device = self.devices.get(address, {}).get('device')
                if device is None:
                    async with self.radio_lock:
                        device = await asyncio.wait_for(self.scanner.find_device_by_address(address, timeout=8.0), timeout=12)
                if device is None:
                    raise TimeoutError('not advertising')
                async with self.client_factory(device, timeout=20.0) as client:
                    characteristic = client.services.get_characteristic(HR_MEASUREMENT)
                    if characteristic is None or not ({'notify', 'indicate'} & set(characteristic.properties)):
                        raise UnsupportedDevice()

                    def on_data(_sender, data):
                        if generation != self.generation or self.closing:
                            return
                        try:
                            before = self.hub.updated_at
                            self.hub.set_bpm(self.parse_bpm(bytes(data)))
                            if self.hub.updated_at != before:
                                self.state, self.error = 'connected', ''
                        except (IndexError, ValueError, TypeError):
                            pass

                    self.state = 'waiting'
                    await asyncio.wait_for(client.start_notify(HR_MEASUREMENT, on_data), timeout=12)
                    if generation != self.generation:
                        return
                    self.hub.connected = True
                    self.state = 'connected' if self.hub.bpm is not None else 'waiting'
                    self.error, backoff = '', 2
                    self.known = [address] + [a for a in self.known if a != address][:4]
                    self.names[address] = self.devices.get(address, {}).get('name') or device.name or self.names.get(address, '')
                    self._save()
                    self.changed()
                    last_battery = 0
                    while client.is_connected and generation == self.generation and not self.closing:
                        if time.monotonic() - last_battery >= 300:
                            last_battery = time.monotonic()
                            with contextlib.suppress(Exception):
                                data = await asyncio.wait_for(client.read_gatt_char(BATTERY_LEVEL), timeout=4)
                                if data:
                                    self.hub.set_battery(data[0])
                        await asyncio.sleep(.5)
            except asyncio.CancelledError:
                raise
            except UnsupportedDevice:
                self.state = 'unsupported'
                self.error = '该设备没有可订阅的标准心率服务。请在手表中开启心率广播，再重新连接；普通蓝牙配对不等于心率广播。'
                break
            except Exception:
                self.error = '连接未成功，正在重试所选设备。请靠近电脑、开启心率广播，并检查是否被手机等设备占用。'
            finally:
                if generation == self.generation:
                    self._clear_reading()
                    self.changed()
            if self.closing or generation != self.generation:
                break
            self.state = 'retrying'
            self.changed()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15)

    async def run(self, stop):
        try:
            if self.target:
                await self.connect(device_id(self.target))
            elif self.name_filter:
                await self.start_scan()
                await self.scan_task
                matches = [a for a, row in self.devices.items() if self.name_filter.casefold() in row['name'].casefold()]
                if len(matches) == 1:
                    await self.connect(device_id(matches[0]))
                else:
                    self.error = '按名字找到多台或未找到设备，请在总控扫描列表中选择。'
                    self.changed()
            await stop.wait()
        finally:
            await self.close()

    async def close(self):
        self.closing = True
        self.generation += 1
        await self._cancel(self.scan_task)
        await self._cancel(self.connection_task)
        self._clear_reading()
