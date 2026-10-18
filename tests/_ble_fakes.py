"""Synthetic radio only, never imports or operates a computer's adapter."""
import asyncio
from types import SimpleNamespace

class Radio:
    def __init__(self):
        self.rows = {
            'test-one': ('演示手表', ['0000180d-0000-1000-8000-00805f9b34fb'], -45),
            'test-two': ('同名手表 <img src=x onerror=window.injected=1>', [], -65),
            'test-speaker': ('演示音箱', [], -55),
        }
        self.clients, self.finds = [], []
        self.scan_calls = 0
        self.scan_error = self.connect_error = False
        self.scan_delay = .02
        self.active = self.max_active = 0
        self.auto_notify = False

    def device(self, address):
        return SimpleNamespace(address=address, name=self.rows[address][0])

    async def discover(self, **kwargs):
        self.scan_calls += 1
        await asyncio.sleep(self.scan_delay)
        if self.scan_error:
            raise OSError('synthetic adapter unavailable')
        return {a: (self.device(a), SimpleNamespace(local_name=n, service_uuids=u, rssi=r)) for a, (n, u, r) in self.rows.items()}

    async def find_device_by_address(self, address, **kwargs):
        self.finds.append(address)
        await asyncio.sleep(.001)
        return self.device(address) if address in self.rows else None

    def client(self, device, **kwargs):
        radio = self
        class Client:
            def __init__(self):
                self.is_connected = False
                self.callback = None
                self.address = device.address
                self.services = SimpleNamespace(get_characteristic=lambda _: None if self.address == 'test-speaker' else SimpleNamespace(properties=['notify']))
            async def __aenter__(self):
                if radio.connect_error:
                    raise OSError('synthetic occupied device')
                self.is_connected = True
                radio.active += 1
                radio.max_active = max(radio.max_active, radio.active)
                radio.clients.append(self)
                return self
            async def __aexit__(self, *args):
                radio.active -= 1
                self.is_connected = False
            async def start_notify(self, uuid, callback):
                self.callback = callback
                if radio.auto_notify:
                    asyncio.get_running_loop().call_later(.1, self.emit, 78)
            def emit(self, bpm):
                self.callback(None, bytearray([0, bpm]))
            async def read_gatt_char(self, uuid):
                return bytes([85])
        return Client()
