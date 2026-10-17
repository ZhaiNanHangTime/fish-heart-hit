import json,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hr_visual as visual
from hr_config import DEFAULT_PARAMS
from aiohttp.test_utils import TestClient,TestServer
import heartrate_live as live

class VisualTests(unittest.TestCase):
    def test_width_only_changes_fish_not_height_digits_or_canvas(self):
        p={**DEFAULT_PARAMS,'skin':'xianyu','fishScale':1.3,'fishWidth':1}
        original=visual.layout(640,280,p)
        narrow=visual.layout(640,280,{**p,'fishWidth':.75})
        wide=visual.layout(640,280,{**p,'fishWidth':1.25})
        self.assertLess(narrow['sprite_rect'][2],original['sprite_rect'][2])
        self.assertGreater(wide['sprite_rect'][2],original['sprite_rect'][2])
        for changed in [narrow,wide]:
            self.assertEqual(changed['sprite_rect'][3],original['sprite_rect'][3])
            for key in ['digit_origin','digit_size','width','height','trace_y','trace_amp']:
                self.assertEqual(changed[key],original[key])

    def test_exact_sprite_dimensions_and_original_pixel_samples(self):
        for name in visual.FRAMES:
            sw,sh,source,*_=visual._rgba(name)
            for width,height in [(95,63),(144,96),(369,246)]:
                w,h,rows=visual.decode_rgba(visual.sprite_png(name,width,height))
                self.assertEqual((w,h),(width,height))
                for x,y in [(0,0),(width//2,height//2),(width-1,height-1),(width//3,height*2//3)]:
                    sx=int((x+.5)*sw/width);sy=int((y+.5)*sh/height)
                    self.assertEqual(rows[y][x*4:x*4+4],source[sy][sx*4:sx*4+4])

    def test_layout_fits_odd_dimensions_and_large_scale(self):
        for size in [(240,104),(211,119),(416,136),(640,280),(960,420)]:
            for scale in [.5,1.3,4]:
                for mode in ['lower','overlay']:
                    v=visual.layout(*size,{**DEFAULT_PARAMS,'skin':'xianyu','fishScale':scale,'fishWidth':1,'traceLayout':mode})
                    x,y,w,h=v['sprite_rect']
                    self.assertEqual(w,(h*3+1)//2)
                    self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                    self.assertLessEqual(x+w+v['unit']*3,v['digit_origin'][0])
                    self.assertLessEqual(y+h,size[1])

class RenderApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_layout_and_sprite_endpoints_share_exact_native_bytes(self):
        client=TestClient(TestServer(live.build_app(live.Hub(None,None,12,600))))
        await client.start_server()
        try:
            params={**DEFAULT_PARAMS,'skin':'xianyu','fishScale':1.3}
            query={'width':211,'height':119,'skin':'xianyu','fishScale':1.3,'target':'hud'}
            response=await client.get('/render/layout',params=query)
            result=await response.json();self.assertEqual(result,visual.layout(211,119,params))
            _,_,w,h=result['sprite_rect']
            response=await client.get('/render/xianyu/idle.png',params={'width':w,'height':h})
            self.assertEqual(response.status,200);self.assertEqual(await response.read(),visual.sprite_png('idle',w,h))
            for path in ['/render/layout?width=0&height=100','/render/xianyu/no.png?width=96&height=64','/render/xianyu/idle.png?width=96&height=999999','/render/xianyu/idle.png?width=0&height=100']:
                response=await client.get(path);self.assertEqual(response.status,400,path)
        finally:await client.close()
