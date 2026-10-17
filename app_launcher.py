"""Double-click entry: one service + one control window; HUD is opt-in."""
from __future__ import annotations
import argparse
import contextlib
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import Request, urlopen
from hr_runtime import APP_ID, CONTROL_PROTOCOL, root_id

HERE = Path(__file__).resolve().parent

class StartupBusy(Exception): pass

def health(base):
    try:
        with urlopen(base+'/health', timeout=1) as response:
            return json.loads(response.read())
    except (OSError, ValueError): return None

@contextlib.contextmanager
def startup_lock(root):
    folder = root/'runtime';folder.mkdir(exist_ok=True)
    stream = (folder/'launcher.lock').open('a+b')
    try:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc: raise StartupBusy() from exc
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally: stream.close()

def focus_control():
    if os.name != 'nt': return False
    found=[]
    callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    def visit(hwnd,_):
        text=ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd,text,512)
        if '咸鱼突刺 · 总控' in text.value:
            found.append(hwnd)
        return True
    ctypes.windll.user32.EnumWindows(callback(visit),0)
    if found:
        ctypes.windll.user32.ShowWindow(ctypes.c_void_p(found[0]),9)
        ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(found[0]))
    return bool(found)

def open_control(base):
    if focus_control(): return
    # An app window has one task and no extra console window. Fall back to default browser.
    candidates=[]
    if os.name=='nt':
        import winreg
        for name in ['chrome.exe','msedge.exe']:
            for registry in [winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE]:
                try:
                    with winreg.OpenKey(registry,r'Software\Microsoft\Windows\CurrentVersion\App Paths'+'\\'+name) as key:
                        candidates.append(winreg.QueryValue(key,None))
                except OSError: pass
    for candidate in candidates:
        if Path(candidate).is_file():
            subprocess.Popen([candidate,'--app='+base+'/console','--new-window'],
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return
    webbrowser.open(base+'/console',new=0)

def ensure_service(root, port=8080, timeout=15):
    base=f'http://127.0.0.1:{port}'
    current=health(base)
    if current:
        if current.get('app')==APP_ID and current.get('control_protocol')==CONTROL_PROTOCOL:
            # Reuse the same compatible service, including when a second release copy is clicked.
            return base
        raise RuntimeError(f'{port}端口仍由旧版程序使用。请先在旧目录双击停止脚本，关闭旧控制台，再重新打开本文件。原数据无需删除。')
    # A non-HTTP program may occupy the port. Never kill it or silently switch OBS to another port.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',port))==0:
            raise RuntimeError(f'{port}端口已被其他程序使用，请关闭占用程序后重试。')
    folder=root/'runtime';folder.mkdir(exist_ok=True)
    python=sys.executable
    if Path(python).name.lower()=='pythonw.exe': python=str(Path(python).with_name('python.exe'))
    with (folder/'service.log').open('ab') as output:
        child=subprocess.Popen([python,str(root/'heartrate_live.py'),'--port',str(port),'--history','2400'],
                               cwd=str(root),stdout=output,stderr=output,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        current=health(base)
        if current and current.get('root_id')==root_id(root) and current.get('control_protocol')==CONTROL_PROTOCOL:
            return base
        if child.poll() is not None:
            raise RuntimeError('服务启动失败。请运行“检查运行环境.bat”，并查看 runtime/service.log。')
        time.sleep(.15)
    # Clean only this attempted child; no half-started orphan service.
    if child.poll() is None:
        child.terminate();child.wait(timeout=5)
    raise RuntimeError('服务启动超时，已清理本次启动。请查看 runtime/service.log 后重试。')

def show_error(message):
    if os.name=='nt': ctypes.windll.user32.MessageBoxW(None,str(message),'咸鱼总控 · 启动提示',0x10)
    else: print(message,file=sys.stderr)

def show_panel(base,target):
    with urlopen(base+'/control',timeout=3) as response:
        token=json.loads(response.read())['token']
    request=Request(base+'/control/panel',data=json.dumps({'target':target}).encode(),
                    headers={'Content-Type':'application/json','X-Control-Token':token})
    with urlopen(request,timeout=3) as response:return json.loads(response.read())

def show_hud(base):
    with urlopen(base+'/control',timeout=3) as response:
        token=json.loads(response.read())['token']
    request=Request(base+'/control/hud',data=b'{"visible":true}',
                    headers={'Content-Type':'application/json','X-Control-Token':token})
    with urlopen(request,timeout=6) as response:
        state=json.loads(response.read())
    if not state.get('hud') or state.get('error'):
        raise RuntimeError(state.get('error') or '悬浮窗未能打开，请在总控中重试。')
    return state

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--stop',action='store_true')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--hud',action='store_true',help='同时打开受总控管理的桌面悬浮窗')
    parser.add_argument('--panel',choices=['hud-size','effects'],help='聚焦现有总控的可视化调整区')
    args=parser.parse_args()
    try:
        if args.check:
            for package in ['aiohttp','bleak','tkinter']:
                try: __import__(package)
                except ImportError:
                    raise RuntimeError('缺少依赖，请在此目录运行：python -m pip install -r requirements.txt')
            message='Python与运行依赖可用。\nPython：'+sys.executable+'\n正常使用请双击“一键打开咸鱼总控.vbs”。'
            if os.name=='nt':ctypes.windll.user32.MessageBoxW(None,message,'运行环境检查',0x40)
            else:print(message)
            return 0
        if args.stop:
            base=f'http://127.0.0.1:{args.port}'
            state=health(base)
            if not state: return 0
            if state.get('app')!=APP_ID or state.get('control_protocol')!=CONTROL_PROTOCOL:
                raise RuntimeError('该端口为旧版或其他服务，请使用它原目录的停止入口。')
            with urlopen(base+'/control') as response: token=json.loads(response.read())['token']
            req=Request(base+'/control/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Control-Token':token})
            with urlopen(req,timeout=4) as response: response.read()
            return 0
        with startup_lock(HERE):
            base=ensure_service(HERE,args.port)
            if args.panel: show_panel(base,args.panel)
            if not args.no_browser: open_control(base)
            if args.hud: show_hud(base)
        return 0
    except StartupBusy:
        focus_control()
        return 0
    except (OSError, RuntimeError) as exc:
        show_error(exc)
        return 1

if __name__=='__main__': raise SystemExit(main())
