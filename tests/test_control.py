import asyncio
import contextlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestClient,TestServer
import heartrate_live as live
from hr_runtime import RuntimeControl,root_id
import app_launcher as launcher

class Child:
    def __init__(self):self.stdin=io.BytesIO();self.returncode=None;self.terminated=False;self.received=b''
    def poll(self):return self.returncode
    def wait(self,timeout=None):self.received=self.stdin.getvalue();self.returncode=0;return 0
    def terminate(self):self.terminated=True;self.returncode=-15

class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.patch=patch.object(live,'PARAMS_FILE',self.root/'params.json');self.patch.start()
        self.hub=live.Hub(None,None,12,600);self.stop=asyncio.Event();self.children=[]
        def spawn(*a,**kw):c=Child();self.children.append(c);return c
        self.runtime=RuntimeControl(self.root,'http://127.0.0.1:8080',self.stop,self.hub.publish,spawn=spawn)
        self.client=TestClient(TestServer(live.build_app(self.hub,self.runtime)));await self.client.start_server()
    async def asyncTearDown(self):
        await self.runtime.close();await self.client.close();self.patch.stop();self.folder.cleanup()
    async def test_repeated_hud_start_is_one_child_and_stop_is_graceful(self):
        self.assertFalse(self.runtime.status()['hud'])
        await asyncio.gather(self.runtime.set_hud(True),self.runtime.set_hud(True))
        self.assertEqual(len(self.children),1)
        self.assertTrue(self.runtime.status()['hud'])
        await self.runtime.set_hud(False)
        self.assertEqual(self.children[0].received,b'stop\n')
        self.assertFalse(self.children[0].terminated)
        self.assertFalse(self.runtime.status()['hud'])
    async def test_control_requires_token_and_same_origin(self):
        response=await self.client.post('/control/hud',json={'visible':True});self.assertEqual(response.status,403)
        response=await self.client.post('/params',headers={'Origin':'https://unrelated.invalid'},json={'skin':'ghost'});self.assertEqual(response.status,403)
        headers={'X-Control-Token':self.runtime.token,'Origin':'https://unrelated.invalid'}
        response=await self.client.post('/control/hud',headers=headers,json={'visible':True});self.assertEqual(response.status,403)
        response=await self.client.get('/control');data=await response.json();self.assertEqual(data['token'],self.runtime.token)
        headers={'X-Control-Token':data['token']}
        response=await self.client.post('/control/hud',headers=headers,json={'visible':'true'});self.assertEqual(response.status,400)
        response=await self.client.post('/control/hud',headers=headers,json={'visible':True});self.assertTrue((await response.json())['hud'])
        self.assertTrue(self.hub.snapshot()['runtime']['hud'])
    async def test_launcher_hud_uses_control_token_and_reuses_managed_child(self):
        base=str(self.client.make_url('')).rstrip('/')
        first=await asyncio.to_thread(launcher.show_hud,base)
        second=await asyncio.to_thread(launcher.show_hud,base)
        self.assertTrue(first['hud'] and second['hud'])
        self.assertEqual(len(self.children),1)
    async def test_shutdown_sets_event_and_closes_only_owned_child(self):
        await self.runtime.set_hud(True)
        response=await self.client.post('/control/shutdown',headers={'X-Control-Token':self.runtime.token},json={})
        self.assertEqual(response.status,200)
        await asyncio.wait_for(self.stop.wait(),1)
        await self.runtime.close()
        self.assertFalse(self.runtime.status()['hud'])
        self.assertEqual(len(self.children),1)
    async def test_effects_links_land_inside_total_control(self):
        response=await self.client.get('/effects',allow_redirects=False)
        self.assertEqual(response.status,302);self.assertEqual(response.headers['Location'],'/console#effects')
        response=await self.client.get('/replay?file=')
        self.assertEqual(response.status,404)
    async def test_live_stage_is_one_server_state_for_new_and_existing_clients(self):
        self.hub.connected=True;self.hub.base_bpm=72;self.hub.baseline.value=72
        self.hub.set_bpm(82)
        self.assertEqual(self.hub.snapshot()['visual_stage'],2)
        self.hub.set_bpm(80)
        # A newly opened client gets stage 2 instead of recomputing stage 1 at delta=8.
        data=await (await self.client.get('/hr')).json()
        self.assertEqual(data['visual_stage'],2)
        self.hub.connected=False
        self.assertEqual(self.hub.snapshot()['visual_stage'],0)

    async def test_health_identifies_control_protocol_and_installation(self):
        data=await (await self.client.get('/health')).json()
        self.assertEqual(data['app'],'fish-heart-hit');self.assertEqual(data['control_protocol'],2)
        self.assertEqual(data['root_id'],root_id(live.HERE))

    async def test_visual_panel_and_native_border_controls(self):
        headers={'X-Control-Token':self.runtime.token}
        denied=await self.client.post('/control/hud-edit',json={'editing':True});self.assertEqual(denied.status,403)
        response=await self.client.post('/control/panel',headers=headers,json={'target':'hud-size'})
        self.assertEqual((await response.json())['panel'],{'id':1,'target':'hud-size'})
        await self.client.post('/control/hud-edit',headers=headers,json={'editing':True})
        self.assertTrue(self.runtime.status()['hud_editing'])
        self.assertEqual(len(self.children),1)
        self.assertIn(b'"edit": true',self.children[0].stdin.getvalue())
        await self.client.post('/control/hud-edit',headers=headers,json={'editing':False})
        self.assertFalse(self.runtime.status()['hud_editing'])

class LauncherTests(unittest.TestCase):
    def test_hud_entry_opens_control_then_requests_managed_hud(self):
        calls=[]
        with patch.object(sys,'argv',['app_launcher.py','--hud']),patch.object(launcher,'startup_lock',return_value=contextlib.nullcontext()),patch.object(launcher,'ensure_service',return_value='http://127.0.0.1:8080'),patch.object(launcher,'open_control',side_effect=lambda base:calls.append('control')),patch.object(launcher,'show_hud',side_effect=lambda base:calls.append('hud')):
            self.assertEqual(launcher.main(),0)
        self.assertEqual(calls,['control','hud'])
    def test_reuse_compatible_service_never_spawns_again(self):
        with patch.object(launcher,'health',return_value={'app':'fish-heart-hit','control_protocol':2}),patch.object(launcher.subprocess,'Popen') as spawn:
            self.assertEqual(launcher.ensure_service(Path('.')),'http://127.0.0.1:8080')
            spawn.assert_not_called()
    def test_legacy_service_is_not_silently_killed_or_moved(self):
        with patch.object(launcher,'health',return_value={'ok':True}),patch.object(launcher.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'旧版'):launcher.ensure_service(Path('.'))
            spawn.assert_not_called()
    def test_real_startup_readiness_reuse_and_shutdown_with_synthetic_device(self):
        product=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='fish-launch-') as folder:
            root=Path(folder)
            # Exercise the actual launcher/server/stop lifecycle without any Bluetooth access.
            wrapper=f'''import sys,asyncio,argparse
from pathlib import Path
sys.path.insert(0,{str(product)!r})
import heartrate_live as live
live.HERE=Path(__file__).resolve().parent
live.PARAMS_FILE=live.HERE/'params.json'
async def fake_ble(hub,address,stop,*args):await stop.wait()
live.ble_loop=fake_ble
p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--history',type=int)
a=p.parse_args();a.warn=None;a.danger=None;a.stale_after=12;a.no_csv=True;a.address=None;a.name=None;a.scan_attempts=1;a.host='127.0.0.1'
asyncio.run(live.main_async(a))
'''
            (root/'heartrate_live.py').write_text(wrapper,encoding='utf-8')
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            real_spawn=subprocess.Popen;owned=[]
            def spawn(*a,**kw):child=real_spawn(*a,**kw);owned.append(child);return child
            try:
                with patch.object(launcher.subprocess,'Popen',side_effect=spawn):
                    base=launcher.ensure_service(root,port)
                    self.assertEqual(launcher.ensure_service(root,port),base)
                self.assertEqual(len(owned),1)
                from urllib.request import urlopen,Request
                with urlopen(base+'/control') as response:token=json.loads(response.read())['token']
                req=Request(base+'/control/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Control-Token':token})
                with urlopen(req) as response:self.assertEqual(response.status,200)
                self.assertEqual(owned[0].wait(timeout=8),0)
                self.assertIsNone(launcher.health(base))
            finally:
                for child in owned:
                    if child.poll() is None:child.terminate();child.wait(timeout=5)

if __name__=='__main__':unittest.main()
