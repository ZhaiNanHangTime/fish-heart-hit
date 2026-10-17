"""Isolated real Tk image exports, to compare against the browser canvas pixels."""
import hashlib,json,os,sys,tempfile
from itertools import product
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import heartrate_hud as hud
from hr_visual import decode_rgba

class Feed:
    def __init__(self,*args):
        self.data={'bpm':72,'base':72,'age':0,'connected':True,'skin':'xianyu','visual_stage':0,
                   'params':dict(hud.DEFAULT_PARAMS,skin='xianyu',fxWarmth=False,fxKick=False),
                   'history':{'samples':[]},'recent':{'p90':82},'stats':{}}
    def latest(self):return self.data
    def close(self):pass

out=Path(os.environ.get('EVIDENCE_DIR','work/control-evidence'));out.mkdir(parents=True,exist_ok=True)
records=[]
with tempfile.TemporaryDirectory() as folder,patch.object(hud,'SnapshotClient',Feed),patch.object(hud.HeartHud,'_restore_position',lambda _:None):
    window=hud.HeartHud('http://127.0.0.1:18766/hr',3,opaque=True);window.root.withdraw()
    try:
        for width,height in [(240,104),(211,119),(640,280)]:
            for scale in [1.3,4]:
                for trace,width_ratio in product(['overlay','lower'],[.75,1,1.25]):
                    window.stream.data['params'].update(hudWidth=width,hudHeight=height,fishScale=scale,traceLayout=trace,fishWidth=width_ratio)
                    window._tick()
                    for name,burst in [('idle',0),('burst',1),('recover',.2)]:
                        window.burst=burst;window._draw_xianyu()
                        image=window.sprite_cache[name];rect=window.visual['sprite_rect']
                        assert [image.width(),image.height()]==rect[2:]
                        path=Path(folder)/'native.png';image.write(str(path),format='png')
                        w,h,rows=decode_rgba(path.read_bytes());pixels=bytearray(b''.join(rows))
                        for i in range(0,len(pixels),4):
                            if pixels[i+3]==0:pixels[i:i+3]=b'\0'*3
                        records.append(dict(width=width,height=height,scale=scale,fishWidth=width_ratio,traceLayout=trace,frame=name,
                                            layout=window.visual,rgba_sha256=hashlib.sha256(pixels).hexdigest()))
        (out/'native-visual-parity.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'PASS: {len(records)} exact native Tk image exports, three canvas sizes, two scales and two trace layouts; recorded RGBA hashes and actual image dimensions')
    finally:window.root.destroy()
