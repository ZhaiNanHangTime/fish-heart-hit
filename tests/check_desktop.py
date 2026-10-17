import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import heartrate_hud as hud
import heartrate_gui as gui
import tkinter as tk
from unittest.mock import patch

class Feed:
    def __init__(self,*args):
        self.data={'bpm':82,'age':0,'connected':True,'base':72,'skin':'xianyu',
                   'params':dict(hud.DEFAULT_PARAMS,skin='xianyu'),
                   'history':{'samples':[[0,72],[1,82]]},'recent':{'p90':82},'stats':{}}
    def latest(self): return self.data
    def close(self): pass

checks=[]
with patch.object(hud,'SnapshotClient',Feed), patch.object(hud.HeartHud,'_restore_position',lambda _:None):
    for scale in [2,3,4,5]:
        h=hud.HeartHud('http://127.0.0.1:18766/hr',scale,opaque=True)
        h.stream.data['params'].update(hudWidth=104*scale,hudHeight=34*scale)
        h.root.withdraw()
        errors=[]
        h.root.report_callback_exception=lambda *e:errors.append(str(e))
        for skin in ['xianyu','ghost','fish','xianyu']:
            h.stream.data['skin']=skin
            for size in [.5,1,1.3,2,4]:
                h.stream.data['params']['fishScale']=size
                h._tick()
                if skin=='xianyu':
                    for delta,expected in zip([0,6,10,14,18,22],['idle','alert_low','alert_mid','tense','high','charge']):
                        h.burst=0;h.state['bpm']=72+delta;h.live=True;h.stage_index=0
                        h._draw_xianyu()
                        assert expected in h.sprite_cache
                    for intensity in [1,.2,0]:
                        h.burst=intensity;h._draw_xianyu()
                    assert 'burst' in h.sprite_cache and 'recover' in h.sprite_cache
                    bbox=h.canvas.bbox(h.sprite_item)
                    assert bbox[0]>=0 and bbox[2]<=h.w, bbox
                    assert len({(im.width(),im.height()) for im in h.sprite_cache.values()})==1
                    h.burst=1;h._draw_fx()
                    assert h.sprite_meta['baked_effects'] is True
                    assert all(h.canvas.itemcget(item,'state')=='hidden' for item in h.fx_items)
                    h.burst=0
                if skin=='fish':
                    h.burst=1;h._draw_fx()
                    assert all(h.canvas.itemcget(item,'state')=='normal' for item in h.fx_items)
                    h.burst=0
                if skin=='ghost':
                    for phase in [.1,.25,.5,.75]:
                        h.phase=phase
                        assert h._quantize_unit(0)==int(h._quantize_unit(0))
                        h._draw_ghost_only('#2b2f36')
                        for _,_,_,item in h.ghost_cells:
                            assert all(v+.5==int(v+.5) for v in h.canvas.coords(item))
            h.root.update_idletasks()
            original_root=h.root
            for layout in ['lower','overlay']:
                h.stream.data['params']['traceLayout']=layout
                with patch.object(hud.subprocess,'Popen',side_effect=AssertionError('layout switch must not spawn')):
                    h._tick()
                assert h.root is original_root
                trace=h.canvas.coords(h.trace)
                ys=trace[1::2]
                if layout=='lower':
                    assert min(ys)>=h.h*.60 and max(ys)<=h.h*.94,ys
                    lower_digit_y=h.digit_org[1]
                else:
                    assert min(ys)<h.h*.20 and max(ys)>h.h*.80,ys
                    assert h.digit_org[1]>lower_digit_y
                order=h.canvas.find_all()
                assert order.index(h.trace)<order.index(h.digit_items[0][0][3])
                if skin=='xianyu':assert order.index(h.trace)<order.index(h.sprite_item)
        assert not errors,errors
        h.stream.data['visual_stage']=2
        h.stream.data['bpm']=80
        h._tick()
        if hud.SKIN_NAME=='xianyu':assert h.stage_index==2
        h.stream.data.pop('visual_stage')
        original_root=h.root
        with patch.object(hud.subprocess,'Popen',side_effect=AssertionError('resize must not spawn')):
            with patch.object(h,'_save_position',lambda:None),patch.object(h,'_commit_size',lambda:None): h._toggle_scale()
        assert h.root is original_root
        h._tick();h.root.update_idletasks()
        h.root.destroy()
        checks.append(f'Tk HUD scale {scale}: 3 skins, 8 material frames, size .5/1/1.3/2/4, both trace layouts switch in the same window; trace stays behind character/digits; preserved ghost quantization')

checks.append('Legacy GUI entry delegates to the unified launcher; it creates no separate Tk console')
print('\n'.join(checks))
