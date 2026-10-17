"""One layout and exact nearest-neighbour PNG resizer for desktop and browser.

No screen capture, Bluetooth access, persistence, or optional imaging libraries.
"""
import binascii
import json
import math
import struct
import zlib
from functools import lru_cache
from pathlib import Path
from hr_config import DEFAULT_PARAMS

ASSETS = Path(__file__).resolve().parent/'web/assets/skins/xianyu'
FRAMES = ('idle','alert_low','alert_mid','tense','high','charge','burst','recover')

def pixel(value):
    return math.floor(value+.5)

def layout(width, height, params, target='hud'):
    w,h=pixel(width),pixel(height)
    if not 160<=w<=3840 or not 60<=h<=2160 or target not in ('hud','obs'):
        raise ValueError('画布尺寸超出范围')
    skin=params.get('skin','fish');lower=params.get('traceLayout')=='lower'
    sw,sh={'xianyu':(24,16),'ghost':(14,14),'fish':(18,16)}[skin]
    unit=max(1,min(pixel(h/(34 if target=='hud' else 1/.030)),(w-8)//68))
    pad=unit+2 if target=='hud' else 8
    dot=unit*2 if target=='hud' else max(1,min(pixel(h/16),w//30))
    number_x=w-pad*2-12*dot
    room_w=max(1,number_x-pad*2-3*unit)
    factor=min(params.get('fishScale',1),room_w/(sw*unit),h*(.58 if lower else .90)/(sh*unit))
    cy=h*(.32 if lower else .5)
    old_x=7.2*unit if target=='hud' else pad+28
    width_ratio=params.get('fishWidth',DEFAULT_PARAMS['fishWidth']) if skin=='xianyu' else 1
    width_fitted=False
    if skin=='xianyu':
        ih=max(1,math.floor(16*unit*factor))
        desired_width=pixel(ih*1.5*width_ratio)
        iw=max(1,min(desired_width,math.floor(room_w)))
        width_fitted=iw<desired_width
        ix=pixel(max(pad,min(old_x+12*unit-iw/2,number_x-pad-3*unit-iw)))
        iy=pixel(cy-ih/2+unit*.5)
        fish_origin=[pixel(ix+iw/2-12*unit),pixel(cy-13*unit/2+unit*.5)]
    else:
        ih=sh*unit*factor;iw=sw*unit*factor
        ix=max(pad,min(old_x,number_x-pad-3*unit-iw));iy=cy-ih/2+unit*.5
        fish_origin=[pixel(ix),pixel(iy)]
    return dict(width=w,height=h,target=target,skin=skin,traceLayout=params.get('traceLayout','overlay'),unit=unit,pad=pad,dot=dot,
                character_scale=factor,requested_scale=params.get('fishScale',1),
                width_ratio=width_ratio,width_fitted=width_fitted,
                fitted=factor+1e-6<params.get('fishScale',1) or width_fitted,
                fish_origin=fish_origin,sprite_rect=[ix,iy,iw,ih],
                digit_origin=[number_x,pixel(cy-5*dot/2)],digit_size=[12*dot,5*dot],
                trace_y=h*(.78 if lower else .5),trace_amp=h*(.15 if lower else .44),
                status_rect=[w-pad-max(2,pixel(h*.03))*2,pad,max(2,pixel(h*.03))*2,max(2,pixel(h*.03))*2])

def _paeth(a,b,c):
    p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
    return a if pa<=pb and pa<=pc else b if pb<=pc else c

@lru_cache(maxsize=8)
def _rgba(frame):
    if frame not in FRAMES:raise ValueError('未知状态图')
    source=(ASSETS/(frame+'.png')).read_bytes()
    w,h,rows=decode_rgba(source)
    meta=json.loads((ASSETS/'frames.json').read_text(encoding='utf-8'))
    return w,h,rows,meta['canvas'],[meta['anchor'][i]-meta['frames'][frame]['anchor'][i] for i in range(2)]

def decode_rgba(source):
    if source[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('无效PNG')
    pos=8;payload=[]
    while pos<len(source):
        size=struct.unpack_from('>I',source,pos)[0];kind=source[pos+4:pos+8];data=source[pos+8:pos+8+size];pos+=size+12
        if kind==b'IHDR':
            w,h,depth,color,comp,filt,interlace=struct.unpack('>IIBBBBB',data)
            if (depth,color,comp,filt,interlace)!=(8,6,0,0,0):raise ValueError('需8位非交错RGBA PNG')
        if kind==b'IDAT':payload.append(data)
        if kind==b'IEND':break
    raw=zlib.decompress(b''.join(payload));stride=w*4;rows=[];prior=bytes(stride)
    if len(raw)!=(stride+1)*h:raise ValueError('PNG行长度错误')
    for y in range(h):
        start=y*(stride+1);kind=raw[start];line=bytearray(raw[start+1:start+1+stride])
        if kind not in range(5):raise ValueError('未知PNG过滤器')
        for x in range(stride) if kind else ():
            a=line[x-4] if x>=4 else 0;b=prior[x];c=prior[x-4] if x>=4 else 0
            extra=a if kind==1 else b if kind==2 else (a+b)//2 if kind==3 else _paeth(a,b,c)
            line[x]=(line[x]+extra)&255
        rows.append(bytes(line));prior=line
    return w,h,rows

def _chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)

@lru_cache(maxsize=96)
def sprite_png(frame,width,height):
    if type(width) is not int or type(height) is not int or not 1<=width<=3840 or not 1<=height<=2160:
        raise ValueError('无效图像尺寸')
    w,h,rows,canvas,offset=_rgba(frame)
    xs=[min(canvas[0]-1,math.floor((x+.5)*canvas[0]/width))-offset[0] for x in range(width)]
    output=[]
    for y in range(height):
        sy=min(canvas[1]-1,math.floor((y+.5)*canvas[1]/height))-offset[1]
        row=rows[sy] if 0<=sy<h else None
        output.append(b'\0'+b''.join(row[x*4:x*4+4] if row is not None and 0<=x<w else b'\0'*4 for x in xs))
    return b'\x89PNG\r\n\x1a\n'+_chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+_chunk(b'IDAT',zlib.compress(b''.join(output),6))+_chunk(b'IEND',b'')
