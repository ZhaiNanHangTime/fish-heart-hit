"""Export actual Tk curve coordinates, stroke sizes and endpoint for browser parity."""
from pathlib import Path
import json,math,os,sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import heartrate_hud as hud
from hr_visual import trace_series

samples=[[i,72+6*math.sin(i/18)+2*math.cos(i/3)] for i in range(8*3600)]
class Feed:
    def __init__(self,*args):
        self.data={'bpm':72,'base':72,'connected':True,'age':0,'params':dict(hud.DEFAULT_PARAMS,skin='xianyu',fxWarmth=False,fxKick=False),'history':{'samples':samples},'recent':{},'stats':{}}
    def latest(self):return self.data
    def close(self):pass
    def wait_closed(self,*args):pass

out=Path(os.environ.get('EVIDENCE_DIR','test-evidence/trace'));out.mkdir(parents=True,exist_ok=True)
records=[]
with patch.object(hud,'SnapshotClient',Feed),patch.object(hud.HeartHud,'_restore_position',lambda _:None):
    window=hud.HeartHud('http://127.0.0.1:18769/hr',3,opaque=True);window.root.withdraw()
    try:
        for size in [(381,95),(640,280)]:
            for mode in ['overlay','lower']:
                for seconds in [90,180,300,600]:
                    window.stream.data['params'].update(hudWidth=size[0],hudHeight=size[1],traceLayout=mode,traceSeconds=seconds)
                    series=trace_series(samples,seconds);window.stream.data['trace']=series
                    window._tick();window._draw_trace()
                    coords=window.canvas.coords(window.trace)
                    expected=[value for x,y in series['points'] for value in (1+x*(window.w-2),window.center_y-y*window.amp)]
                    assert coords==expected
                    assert coords[-2]==size[0]-1
                    assert window.canvas.coords(window.trace_shadow)==coords
                    records.append({'width':size[0],'height':size[1],'traceLayout':mode,'seconds':seconds,'series':series,'coords':coords,'dot':window.canvas.coords(window.trace_dot),'stroke':float(window.canvas.itemcget(window.trace,'width')),'shadow_stroke':float(window.canvas.itemcget(window.trace_shadow,'width'))})
        window.history=[];window.state['trace']=trace_series([],180);hud.P['traceSeconds']=180;window._draw_trace()
        assert window.canvas.itemcget(window.trace,'state')=='hidden'
        assert window.canvas.itemcget(window.trace_shadow,'state')=='hidden'
        assert window.canvas.itemcget(window.trace_dot,'state')=='hidden'
        (out/'native-trace.json').write_text(json.dumps({'samples':samples,'cases':records}),encoding='utf-8')
        print(json.dumps({'native_cases':len(records),'long_history_hours':8,'curve_coordinates':'PASS','last_point_connected':'PASS','empty_trace_hidden':'PASS','live_service_accessed':False}))
    finally:window.root.destroy()
