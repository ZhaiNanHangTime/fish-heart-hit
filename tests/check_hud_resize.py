"""Real Tk pointer events + real isolated HTTP/SSE persistence; no Bluetooth or personal files."""
import asyncio,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestClient,TestServer
import heartrate_live as live
import heartrate_hud as hud

async def main():
    with tempfile.TemporaryDirectory(prefix='fish-resize-') as folder:
        temp=Path(folder)
        with patch.object(live,'PARAMS_FILE',temp/'params.json'),patch.object(hud,'SETTINGS',temp/'hud.json'):
            hub=live.Hub(None,None,12,600);hub.connected=True;hub.base_bpm=72;hub.baseline.value=72;hub.set_bpm(82)
            client=TestClient(TestServer(live.build_app(hub),shutdown_timeout=1));await client.start_server()
            window=hud.HeartHud(str(client.make_url('/hr')),3,opaque=True)
            window.root.geometry('+40+40')
            errors=[];window.root.report_callback_exception=lambda *exc:errors.append(str(exc))
            async def pump(predicate,timeout=5):
                deadline=asyncio.get_running_loop().time()+timeout
                while not predicate():
                    window.root.update();await asyncio.sleep(.01)
                    if asyncio.get_running_loop().time()>deadline:raise AssertionError('Timed out waiting for Tk/HTTP state')
                window.root.update()
            try:
                await pump(lambda:window.state.get('params_version'))
                original=window.root.winfo_id()
                assert (window.w,window.h)==(240,104)
                with patch.object(hud.subprocess,'Popen',side_effect=AssertionError('resize must not spawn')):
                    window._toggle_resize_mode();window.root.update()
                    window.canvas.event_generate('<Motion>',x=window.w-5,y=window.h-5)
                    assert window.canvas.cget('cursor')=='sizing'
                    window.canvas.event_generate('<ButtonPress-1>',x=window.w-5,y=window.h-5,rootx=400,rooty=300)
                    window.canvas.event_generate('<B1-Motion>',x=206,y=114,rootx=371,rooty=315)
                    assert (window.w,window.h)==(211,119),(window.w,window.h)
                    assert (hub.params['hudWidth'],hub.params['hudHeight'])==(240,104),'drag draft must not write until release'
                    window.canvas.event_generate('<ButtonRelease-1>',x=206,y=114,rootx=371,rooty=315)
                    await pump(lambda:hub.params['hudWidth']==211 and window.local_size is None)
                    saved=json.loads((temp/'params.json').read_text())
                    assert (saved['hudWidth'],saved['hudHeight'])==(211,119)
                    assert (saved['viewWidth'],saved['viewHeight'])==(520,170)
                    assert window.root.winfo_id()==original
                    print('PASS: actual pointer drag resizes immediately; release persists through HTTP/SSE; one Tk window; OBS dimensions unchanged')
                    await client.post('/params',json={'hudWidth':220,'hudHeight':100})
                    await pump(lambda:(window.w,window.h)==(220,100))
                    print('PASS: total-control size changes reach the same native window')
                    with patch.object(hud,'urlopen',side_effect=OSError('synthetic offline')):
                        window._resize_to(200,96);window._commit_size()
                        await pump(lambda:bool(window.size_error))
                        assert hub.params['hudWidth']==220
                    window._commit_size()
                    await pump(lambda:hub.params['hudWidth']==200 and window.local_size is None and not window.size_error)
                    print('PASS: failed save is visible and retry saves the requested size')
                    for size,expected in [((20,9999),(160,1080)),((9999,10),(1920,64)),((240,104),(240,104))]:
                        window._resize_to(*size)
                        assert (window.w,window.h)==expected
                        assert window.digit_org[0]>=0 and window.digit_org[0]+window.digit_w<=window.w
                    window.canvas.event_generate('<MouseWheel>',delta=120)
                    await pump(lambda:hub.params['hudWidth']==264 and window.local_size is None)
                    window._toggle_scale()
                    await pump(lambda:hub.params['hudWidth']==240 and window.local_size is None)
                    print('PASS: corner cursor, mouse-wheel zoom and double-click preset handler persist')
                    window._toggle_resize_mode()
                    assert window.canvas.itemcget(window.resize_border,'state')=='hidden'
                    print('PASS: independent width/height limits, whole-pixel layout and resize controls hidden after editing')
                    # Actual HUD controls write partial shared parameters, received by a second output client.
                    mirror=hud.SnapshotClient(str(client.make_url('/')).rstrip('/'))
                    try:
                        with patch.object(hud.subprocess,'Popen') as opener:
                            window._open_adjustments()
                            assert '--panel' in opener.call_args[0][0] and 'hud-size' in opener.call_args[0][0]
                        window._commit_appearance({'skin':'ghost'})
                        await pump(lambda:hub.params['skin']=='ghost' and hud.SKIN_NAME=='ghost' and mirror.latest().get('params',{}).get('skin')=='ghost')
                        window._commit_appearance({'fishScale':4})
                        await pump(lambda:hub.params['fishScale']==4 and hud.P['fishScale']==4 and mirror.latest().get('params',{}).get('fishScale')==4)
                        assert (hub.params['viewWidth'],hub.params['viewHeight'])==(520,170)
                        window._resize_to(640,280);window._commit_size()
                        await pump(lambda:hub.params['hudWidth']==640 and window.local_size is None)
                        window._commit_appearance({'skin':'xianyu'})
                        await pump(lambda:hud.SKIN_NAME=='xianyu' and mirror.latest().get('params',{}).get('skin')=='xianyu')
                        assert window.root.winfo_id()==original
                        window.burst=1;window._draw_xianyu()
                        box=window.canvas.bbox(window.sprite_item)
                        assert box[0]>=0 and box[1]>=0 and box[2]<=window.digit_org[0] and box[3]<=window.h,box
                        assert window.sprite_cache['burst'].height()>100
                        await client.post('/params',json={'skin':'fish','fishScale':2})
                        await pump(lambda:hud.SKIN_NAME=='fish' and hud.P['fishScale']==2)
                        with patch.object(hud,'urlopen',side_effect=OSError('synthetic shared save failure')):
                            window._commit_appearance({'skin':'ghost'})
                            await pump(lambda:bool(window.appearance_error))
                        assert hub.params['skin']=='fish'
                        window._commit_appearance({'skin':'ghost'})
                        await pump(lambda:hub.params['skin']=='ghost' and not window.appearance_error)
                        window.commands.put({'edit':True});window._tick()
                        assert window.resize_mode
                        window.commands.put({'edit':False});window._tick()
                        assert not window.resize_mode
                        print('PASS: native shared appearance HTTP; second SSE output follows skin/scale; visual-adjust shortcut uses one launcher; remote border commands; failure/retry; exact-size sprite fits')
                    finally:
                        mirror.close();await asyncio.to_thread(mirror.wait_closed,2)
                assert not errors,errors
            finally:
                window._quit();hub.publish();await client.close()
                await asyncio.to_thread(window.stream.wait_closed,2)
                if window.size_worker:await asyncio.to_thread(window.size_worker.join,2)
                assert not window.stream._thread.is_alive()
    print('Native interactive HUD checks complete; synthetic data only.')

if __name__=='__main__':asyncio.run(main())
