"""LOCAL TEST FIXTURE ONLY. No BLE, no CSV, no personal files."""
import sys
import tempfile
import atexit
import asyncio
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import heartrate_live as live
from aiohttp import web
test_dir = tempfile.TemporaryDirectory(prefix='fish-heart-test-')
atexit.register(test_dir.cleanup)
live.PARAMS_FILE = Path(test_dir.name) / 'params.json'
class TestHub(live.Hub):
    def snapshot(self): return {**super().snapshot(),'synthetic':True}
hub = TestHub(None, None, 12, 600)
hub.connected = True
hub.baseline.value = 72.
hub.base_bpm = 72.
class TestRuntime:
    token='synthetic-control-token'
    def __init__(self): self.visible=False;self.closing=False;self.editing=False;self.panel={'id':0,'target':'hud-size'};self.session_id='fixture-session'
    def status(self): return {'available':True,'hud':self.visible,'error':'','stopping':self.closing,'protocol':2,'hud_editing':self.editing,'panel':self.panel,'session_id':self.session_id}
    def request_panel(self,target):self.panel={'id':self.panel['id']+1,'target':target};hub.publish()
    async def edit_hud(self,editing):self.visible=self.visible or editing;self.editing=editing;hub.publish();return self.status()
    async def set_hud(self,visible): self.visible=visible;hub.publish();return self.status()
    def request_shutdown(self): self.closing=True;self.visible=False;hub.publish()
runtime=TestRuntime()
app = live.build_app(hub,runtime)
reading = 72
silent = False
event_transports=set()

@web.middleware
async def track_test_streams(request,handler):
    transport=request.transport if request.path=='/events' else None
    if transport:event_transports.add(transport)
    try:return await handler(request)
    finally:
        if transport:event_transports.discard(transport)

app.middlewares.append(track_test_streams)

async def control(req):
    global reading,silent
    data = await req.json()
    if data.get('new_session'):
        runtime.session_id+='-new';runtime.closing=False;runtime.visible=False;runtime.editing=False;runtime.panel={'id':0,'target':'hud-size'}
    if data.get('disconnect_streams'):
        for transport in list(event_transports):transport.close()
    silent=data.get('silent',False)
    if 'base' in data:
        hub.baseline = live.Baseline()
        for t in range(601): hub.baseline.add(time.time()-600+t,data['base'])
        hub.base_bpm = hub.baseline.value
    reading = data.get('bpm', 72)
    hub.connected = data.get('connected', True)
    if reading is not None:
        hub.set_bpm(reading)
    else:
        hub.bpm = None
        hub.publish()
    return web.json_response({'synthetic': True})

async def loop(app):
    async def tick():
        while True:
            if silent:
                await asyncio.sleep(1)
                continue
            if reading is not None and hub.connected:
                hub.set_bpm(reading)
            else:
                hub.publish()
            await asyncio.sleep(1)
    task = asyncio.create_task(tick())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app.router.add_post('/__test', control)
app.cleanup_ctx.append(loop)
web.run_app(app, host='127.0.0.1', port=18766, print=None)
