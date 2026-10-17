"""Own the HUD child process; never match or kill unrelated Python processes."""
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

APP_ID = "fish-heart-hit"
CONTROL_PROTOCOL = 2

def root_id(root):
    return hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:16]

class RuntimeControl:
    def __init__(self, root, api, stop, on_change=lambda: None, spawn=subprocess.Popen):
        self.root, self.api, self.stop = Path(root), api, stop
        self.on_change, self.spawn = on_change, spawn
        self.token = secrets.token_urlsafe(24)
        self.session_id = secrets.token_hex(8)
        self.child = None
        self.error = ""
        self.lock = asyncio.Lock()
        self.closing = False
        self.editing = False
        self.panel = {'id':0,'target':'hud-size'}

    def status(self):
        alive = self.child is not None and self.child.poll() is None
        if self.child is not None and not alive and self.child.returncode:
            self.error = "悬浮窗已退出，请查看 runtime/hud.log 后重试"
        return {"available": True, "hud": alive, "error": self.error,
                "stopping": self.closing, "protocol": CONTROL_PROTOCOL,
                "hud_editing":self.editing and alive,"panel":self.panel,"session_id":self.session_id}

    def request_panel(self,target):
        if target not in ('hud-size','effects'):raise ValueError('无效面板')
        self.panel={'id':self.panel['id']+1,'target':target}
        self.on_change()

    async def edit_hud(self,editing):
        if editing:await self.set_hud(True)
        async with self.lock:
            if self.closing:raise ValueError('本次运行正在结束')
            if self.child is None or self.child.poll() is not None:
                self.editing=False
            else:
                try:
                    self.child.stdin.write((json.dumps({'edit':editing})+'\n').encode())
                    self.child.stdin.flush();self.editing=editing
                except (OSError,ValueError):
                    self.error='悬浮窗未能接收边界设置，请重新显示后重试';self.editing=False
            self.on_change()
            return self.status()

    async def set_hud(self, visible):
        async with self.lock:
            if self.closing:
                raise ValueError("本次运行正在结束")
            alive = self.child is not None and self.child.poll() is None
            if visible and not alive:
                scale = 3
                try:
                    value = json.loads((self.root / 'hud.json').read_text(encoding='utf-8')).get('scale')
                    if value in (2,3,4,5): scale = value
                except (OSError, ValueError, TypeError):
                    pass
                folder = self.root / 'runtime'
                folder.mkdir(exist_ok=True)
                with (folder / 'hud.log').open('ab') as output:
                    self.child = self.spawn(
                        [sys.executable, str(self.root/'heartrate_hud.py'), '--api', self.api+'/hr',
                         '--scale', str(scale), '--managed'], cwd=str(self.root), stdin=subprocess.PIPE,
                        stdout=output, stderr=output,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.error = ""
                # Report early startup failure instead of claiming the HUD is visible.
                await asyncio.sleep(.3)
            elif not visible and alive:
                await self._close_child()
            self.on_change()
            return self.status()

    async def _close_child(self):
        child = self.child
        if child is None: return
        try:
            if child.poll() is None:
                try:
                    child.stdin.write(b'stop\n')
                    child.stdin.flush()
                except (OSError, AttributeError):
                    pass
                try:
                    await asyncio.to_thread(child.wait, timeout=3)
                except subprocess.TimeoutExpired:
                    child.terminate()  # only the Popen handle we own
                    await asyncio.to_thread(child.wait, timeout=3)
        finally:
            if child.stdin: child.stdin.close()
            self.child = None
            self.editing = False

    async def close(self):
        async with self.lock:
            self.closing = True
            await self._close_child()

    def request_shutdown(self):
        self.closing = True
        self.on_change()
        asyncio.get_running_loop().call_later(.25, self.stop.set)
