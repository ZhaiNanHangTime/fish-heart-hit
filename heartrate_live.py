"""Heart-rate bridge for live streaming — pixel-art overlay + session stats.

Reads a standard BLE heart-rate device (GATT 0x180D / 0x2A37, e.g. BLE 心率设备
in "heart rate broadcast" mode) plus its battery level (0x180F / 0x2A19),
auto-reconnects forever, keeps a rolling history and session statistics, and
optionally logs every reading to CSV.

HTTP endpoints
    /           pixel-art widget  (use this in the OBS browser source)
    /plain      big number only, transparent background
    /hr         JSON snapshot (bpm / stats / zone / battery)
    /bpm        plain text bpm
    /events     Server-Sent Events stream of the same snapshot
    /history    rolling samples for custom drawing
    /reset      reset session statistics

Usage
    python heartrate_live.py                        # 自动找心率设备（扫描 + GATT 探测）
    python heartrate_live.py --name Amazfit         # 多台 BLE 设备时按名字找
    python heartrate_live.py --address AA:BB:CC:DD:EE:FF --port 8080
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import json
import logging
import time
from collections import deque
from pathlib import Path

from aiohttp import web
from hr_config import DEFAULT_PARAMS, GROUPS, merge_params
from hr_baseline import Baseline
from hr_runtime import RuntimeControl, APP_ID, CONTROL_PROTOCOL, root_id
from hr_visual import layout as visual_layout, sprite_png, FRAMES, trace_series
from hr_devices import DeviceManager
from hr_recording import ActivityRecorder, ACTIVITIES, describe_log
from bleak import BleakClient, BleakScanner

HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
DEFAULT_ADDRESS = None        # 留空 = 自动扫描带心率广播的设备（不写死任何人的手环）
HERE = Path(__file__).resolve().parent
PARAMS_FILE = HERE / "params.json"
DEVICES_FILE = HERE / "devices.json"      # 记住连成功过的心率设备（已 gitignore）


def load_known_devices() -> list[str]:
    """读取历史上连接成功过的心率设备地址（最近成功的排最前）。"""
    if not DEVICES_FILE.exists():
        return []
    try:
        data = json.loads(DEVICES_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):
        data = data.get("addresses", [])
    return [str(a) for a in data if a]


def remember_device(address: str) -> None:
    """把地址记到 devices.json 最前面（去重、最多留 5 个）。"""
    if not address:
        return
    known = [a for a in load_known_devices() if a.upper() != address.upper()]
    known.insert(0, address)
    try:
        DEVICES_FILE.write_text(json.dumps({"addresses": known[:5]}, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        log.info("已记住心率设备地址：%s（下次启动会先直连它）", address)
    except Exception as exc:  # noqa: BLE001
        log.warning("写入 %s 失败：%s", DEVICES_FILE.name, exc)

def load_params() -> dict:
    params = dict(DEFAULT_PARAMS)
    if PARAMS_FILE.exists():
        try:
            params = merge_params(params, json.loads(PARAMS_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            logging.getLogger("hr").warning("参数文件无效，使用默认值：%s", exc)
    return params


def save_params(values: dict, base=None) -> dict:
    params = merge_params(base or load_params(), values)
    temporary = PARAMS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PARAMS_FILE)
    return params


log = logging.getLogger("hr")


def parse_bpm(data: bytes) -> int:
    """Decode Heart Rate Measurement (flags bit0 picks uint8 vs uint16)."""
    return int.from_bytes(data[1:3], "little") if data[0] & 0x01 else data[1]


class Hub:
    """Live state: current bpm, session stats, rolling history, battery."""

    def __init__(self, warn: float, danger: float, stale_after: float, history_len: int) -> None:
        self.bpm: int | None = None
        self.updated_at: float = 0.0
        self.connected = False
        self.params = merge_params(load_params(), {
            **({"warn": warn} if warn is not None else {}),
            **({"danger": danger} if danger is not None else {}),
        })
        self.warn = self.params["warn"]
        self.danger = self.params["danger"]
        self.params_version = time.time_ns() // 1_000_000
        self.revision = 0
        self.visual_stage = 0
        self.runtime = None
        self.baseline = Baseline()
        self.stale_after = stale_after

        self.history: deque[tuple[float, int]] = deque(maxlen=history_len)
        self.session_started = time.time()
        self.samples = 0
        self.total = 0
        self.minimum: int | None = None
        self.maximum: int | None = None

        self.battery: int | None = None
        self.battery_at: float = 0.0
        self.base_bpm: float | None = None  # rolling P25, tau=60s

        self.queues: set[asyncio.Queue] = set()
        self.recording = ActivityRecorder()
        self.log_directory = HERE / 'logs'

    # ---------- data intake ----------

    def start_csv(self, directory: Path) -> Path:
        self.log_directory = Path(directory)
        return self.recording.start(directory, self.params)

    def close_csv(self) -> None:
        try:
            self.recording.close()
        except OSError:
            log.exception('记录结束信息写入失败，已有CSV保留')

    def set_bpm(self, bpm: int) -> None:
        if not 20 <= bpm <= 250:  # ignore obvious garbage
            return
        now = time.time()
        self.bpm = bpm
        self.updated_at = now
        self.history.append((now, bpm))
        self.baseline.add(now, bpm)
        self.base_bpm = self.baseline.value
        self.samples += 1
        self.total += bpm
        self.minimum = bpm if self.minimum is None else min(self.minimum, bpm)
        self.maximum = bpm if self.maximum is None else max(self.maximum, bpm)
        self.recording.write(now, bpm, self.base_bpm, self.params_version)
        self.publish()

    def set_battery(self, level: int) -> None:
        self.battery = level
        self.battery_at = time.time()
        self.publish()

    def reset_session(self) -> None:
        self.session_started = time.time()
        self.samples = 0
        self.total = 0
        self.minimum = None
        self.maximum = None
        self.history.clear()
        self.baseline = Baseline()
        self.base_bpm = None
        self.publish()

    # ---------- state export ----------

    def zone(self) -> str:
        snap = self.snapshot()
        if snap["bpm"] is None:
            return "idle"
        if snap["bpm"] >= self.danger:
            return "danger"
        if snap["bpm"] >= self.warn:
            return "warn"
        return "rest"

    def calibrate_now(self) -> dict:
        ok, message = self.baseline.calibrate(time.time())
        self.base_bpm = self.baseline.value
        self.publish()
        return {"ok": ok, "message": message, "base": self.base_bpm}

    def recent_stats(self, window: float = 600.0) -> dict:
        """最近 window 秒的统计：min / avg / max / p90。

        用 P90（第 90 百分位）当红色阈值的输入，而不是最大值 ——
        既反映"你最近的强度水平"，又不会被一次偶发尖峰锁死。
        峰值按要求不做任何滤波，直接取真实值。
        """
        if not self.history:
            return {}
        cutoff = time.time() - window
        vals = sorted(v for t, v in self.history if t >= cutoff)
        if not vals:
            return {}
        n = len(vals)
        return {
            "min": vals[0],
            "max": vals[-1],
            "avg": round(sum(vals) / n),
            "p90": vals[min(n - 1, int(n * 0.9))],
            "p50": vals[min(n - 1, int(n * 0.5))],
            "p25": vals[min(n - 1, int(n * 0.25))],
            "samples": n,
            "window": window,
        }

    def snapshot(self) -> dict:
        self.warn, self.danger = self.params["warn"], self.params["danger"]
        age = (time.time() - self.updated_at) if self.updated_at else None
        live = (self.bpm is not None and age is not None
                and age < min(self.stale_after, self.params["offlineAfter"]))
        bpm = self.bpm if live else None
        if bpm is None:
            zone = "idle"
        elif bpm >= self.danger:
            zone = "danger"
        elif bpm >= self.warn:
            zone = "warn"
        else:
            zone = "rest"
        # One live Schmitt state for every renderer, including newly opened windows.
        if bpm is None or not self.connected:
            self.visual_stage = 0
        else:
            delta = bpm - (self.base_bpm if self.base_bpm is not None else 70)
            while self.visual_stage < 5 and delta >= (self.visual_stage+1)*4+2:
                self.visual_stage += 1
            while self.visual_stage > 0 and delta < self.visual_stage*4-2:
                self.visual_stage -= 1
        return {
            "bpm": bpm,
            "connected": self.connected,
            "age": round(age, 1) if age is not None else None,
            "zone": zone,
            "stats": {
                "min": self.minimum,
                "max": self.maximum,
                "avg": round(self.total / self.samples) if self.samples else None,
                "samples": self.samples,
                "elapsed": round(time.time() - self.session_started),
            },
            "battery": self.battery,
            "base": self.base_bpm,
            "skin": self.params["skin"],
            "params": dict(self.params),
            "params_version": self.params_version,
            "revision": self.revision,
            "recording": self.recording.status(),
            "baseline": self.baseline.status(time.time()),
            "history": {"samples": [[round(t - self.session_started, 2), v] for t, v in self.history]},
            "trace": trace_series([[round(t-self.session_started, 2),v] for t,v in self.history],
                                  self.params['traceSeconds']),
            "visual_stage": self.visual_stage,
            "runtime": self.runtime.status() if self.runtime else {"available":False,"hud":False},
            "recent": self.recent_stats(),
            "warn": self.warn,
            "danger": self.danger,
        }

    def publish(self) -> None:
        self.revision += 1
        snap = self.snapshot()
        for queue in list(self.queues):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(snap)


async def read_battery(client: BleakClient, hub: Hub) -> None:
    try:
        data = bytes(await client.read_gatt_char(BATTERY_LEVEL))
        if data:
            hub.set_battery(data[0])
            log.info("battery = %d%%", data[0])
    except Exception as exc:  # noqa: BLE001
        log.debug("battery read failed: %s", exc)


async def ble_loop(hub: Hub, address: str | None, stop: asyncio.Event,
                   name: str | None = None, attempts: int = 1) -> None:
    """The visual manager owns a single selected connection and its reconnects."""
    if not getattr(hub, 'devices', None):
        hub.devices = DeviceManager(hub, DEVICES_FILE, parse_bpm, address, name)
    await hub.devices.run(stop)


FALLBACK_PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>Heart Rate</title></head><body style="background:transparent;color:#fff;
font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<span id="v" style="font-size:64px;color:#ff5a3c">--</span>
<script>const es=new EventSource('/events');
es.onmessage=e=>{const s=JSON.parse(e.data);document.getElementById('v').textContent=s.bpm??'--';};</script>
</body></html>"""


def build_app(hub: Hub, runtime=None) -> web.Application:
    hub.runtime = runtime
    async def index(_request: web.Request) -> web.Response:
        page = HERE / "web" / "pixel.html"
        if page.exists():
            return web.Response(text=page.read_text(encoding="utf-8"),
                                content_type="text/html", charset="utf-8")
        return web.Response(text=FALLBACK_PAGE, content_type="text/html", charset="utf-8")

    async def effects(_request: web.Request) -> web.Response:
        """Local-only visual sandbox. The iframe uses demo=1, never the BLE stream."""
        raise web.HTTPFound("/console#effects")

    async def plain(_request: web.Request) -> web.Response:
        page = HERE / "web" / "plain.html"
        html = page.read_text(encoding="utf-8") if page.exists() else FALLBACK_PAGE
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def tune(_request: web.Request) -> web.Response:
        page = HERE / "web" / "tune.html"
        if page.exists():
            return web.Response(text=page.read_text(encoding="utf-8"),
                                content_type="text/html", charset="utf-8")
        return web.Response(text="tune page missing", status=404)

    async def params_get(_request: web.Request) -> web.Response:
        return web.json_response(hub.params)

    async def params_post(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            saved = save_params(body, hub.params)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        hub.params = saved
        hub.params_version += 1
        hub.publish()  # configuration changes reach idle/disconnected clients immediately
        return web.json_response(saved, headers={"X-Params-Version": str(hub.params_version)})

    async def schema(_request):
        return web.json_response({"defaults": DEFAULT_PARAMS, "groups": GROUPS})

    async def live_js(_request):
        return web.FileResponse(HERE / "web" / "live.js")

    async def control_js(_request):
        return web.FileResponse(HERE/"web/control.js")

    async def devices_js(_request):
        return web.FileResponse(HERE/"web/devices.js")

    async def control_css(_request):
        return web.FileResponse(HERE/"web/control.css")

    async def studio_theme(_request):
        return web.FileResponse(HERE/"web/studio-theme.css")

    async def monitor(_request):
        return web.FileResponse(HERE / "web" / "monitor.html")

    async def theme(_request: web.Request) -> web.Response:
        """共享主题样式（各页面统一视觉）。"""
        path = HERE / "web" / "theme.css"
        if path.exists():
            return web.Response(text=path.read_text(encoding="utf-8"),
                                content_type="text/css", charset="utf-8")
        return web.Response(status=404)

    async def console(_request: web.Request) -> web.Response:
        page = HERE / "web" / "console.html"
        if page.exists():
            return web.Response(text=page.read_text(encoding="utf-8"),
                                content_type="text/html", charset="utf-8")
        return web.Response(text="console page missing", status=404)

    async def test_bench(_request: web.Request) -> web.Response:
        """验收台：精确驱动心率看动画（页面内嵌 ?test=1 的叠层）。"""
        page = HERE / "web" / "test.html"
        if page.exists():
            return web.Response(text=page.read_text(encoding="utf-8"),
                                content_type="text/html", charset="utf-8")
        return web.Response(text="test page missing", status=404)

    async def logs_list(_request: web.Request) -> web.Response:
        """列出历史心率记录。"""
        activity = _request.query.get('activity', 'all')
        if activity != 'all' and activity not in ACTIVITIES:
            return web.json_response({'error': '无效记录类型'}, status=400)
        logs_dir = hub.log_directory
        items = []
        for f in sorted(logs_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                info = describe_log(f)
            except Exception:  # noqa: BLE001
                info = {'samples': 0, 'activity': 'unmarked', 'game': ''}
            if activity != 'all' and info['activity'] != activity:
                continue
            items.append({"name": f.name, **info,
                          "kb": round(f.stat().st_size / 1024, 1),
                          "mtime": f.stat().st_mtime})
            if len(items) >= 60:
                break
        return web.json_response(items)

    async def replay(request: web.Request) -> web.Response:
        """对某份真实记录跑一遍当前参数，返回三个验收指标。"""
        name = request.query.get("file", "")
        logs_dir = hub.log_directory.resolve()
        try:
            path = (logs_dir / name).resolve()
            path.relative_to(logs_dir)          # 防目录穿越
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "bad path"}, status=400)
        if not path.is_file() or path.suffix.lower() != ".csv":
            return web.json_response({"error": "CSV file not found"}, status=404)

        rows = []
        with path.open(encoding="utf-8-sig") as fh:
            for rec in csv.DictReader(fh):
                try:
                    rows.append((float(rec["timestamp"]), int(rec["bpm"])))
                except Exception:  # noqa: BLE001
                    continue
        if len(rows) < 10:
            return web.json_response({"error": "样本太少"}, status=400)
        rows.sort()

        import replay_check as rc
        res = rc.replay(rows, params=hub.params)
        dur = max(0.1, (rows[-1][0] - rows[0][0]) / 60.0)
        vals = [v for _t, v in rows]
        return web.json_response({
            "file": name, "samples": len(rows), "minutes": round(dur, 1),
            "min": min(vals), "avg": sum(vals) // len(vals), "max": max(vals),
            "red": res["red"], "false_red": res["false_red"], "burst": res["burst"],
            "red_per10": round(res["red"] * 10 / dur, 1),
            "burst_per10": round(res["burst"] * 10 / dur, 1),
            "anchorB": round(res["anchors"]["B"]), "anchorR": round(res["anchors"]["R"]),
        })

    async def calibrate(_request: web.Request) -> web.Response:
        """手动校准基准：用最近 60 秒的平静水平重设 B。"""
        result = hub.calibrate_now()
        return web.json_response(result, status=200 if result["ok"] else 409)

    async def hr(_request: web.Request) -> web.Response:
        return web.json_response(hub.snapshot())

    async def bpm(_request: web.Request) -> web.Response:
        snap = hub.snapshot()
        return web.Response(text=str(snap["bpm"] if snap["bpm"] is not None else "--"))

    async def history(_request: web.Request) -> web.Response:
        base = hub.history[0][0] if hub.history else time.time()
        return web.json_response({
            "warn": hub.warn,
            "danger": hub.danger,
            "samples": [[round(t - base, 2), v] for t, v in hub.history],
        })

    async def reset(_request: web.Request) -> web.Response:
        hub.reset_session()
        return web.json_response({"ok": True})

    async def render_layout(request):
        try:
            values={key:request.query[key] for key in ('skin','traceLayout') if key in request.query}
            if 'fishScale' in request.query:values['fishScale']=float(request.query['fishScale'])
            if 'fishWidth' in request.query:values['fishWidth']=float(request.query['fishWidth'])
            params=merge_params(hub.params,values)
            result=visual_layout(float(request.query['width']),float(request.query['height']),params,request.query.get('target','hud'))
            return web.json_response(result,headers={'Cache-Control':'no-store'})
        except (ValueError,TypeError,KeyError,OverflowError):
            return web.json_response({'error':'无效画布参数'},status=400)

    async def render_sprite(request):
        try:
            frame=request.match_info['frame']
            if frame not in FRAMES:raise ValueError('未知状态')
            width,height=int(request.query['width']),int(request.query['height'])
            data=await asyncio.to_thread(sprite_png,frame,width,height)
            return web.Response(body=data,content_type='image/png',headers={'Cache-Control':'public, max-age=3600'})
        except (ValueError,TypeError,KeyError):
            return web.json_response({'error':'无效素材参数'},status=400)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "connected": hub.connected,
            "app":APP_ID, "control_protocol":CONTROL_PROTOCOL, "root_id":root_id(HERE)})

    def require_control(request, mutation=False):
        if runtime is None:
            raise web.HTTPServiceUnavailable(text="总控未启用")
        if request.remote not in ("127.0.0.1", "::1"):
            raise web.HTTPForbidden()
        origin = request.headers.get("Origin")
        if origin and origin != str(request.url.origin()):
            raise web.HTTPForbidden()
        if mutation and request.headers.get("X-Control-Token") != runtime.token:
            raise web.HTTPForbidden()

    async def control_get(request):
        require_control(request)
        return web.json_response({**runtime.status(), "token":runtime.token},headers={"Cache-Control":"no-store"})

    async def control_recording(request):
        require_control(request, request.method == 'POST')
        if request.method == 'GET':
            return web.json_response(hub.recording.status(), headers={'Cache-Control': 'no-store'})
        if runtime.status().get('stopping'):
            return web.json_response({'error': '本次运行正在结束。'}, status=409)
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get('activity'), str):
                raise ValueError('无效记录操作')
            result = hub.recording.change(body['activity'], body.get('game', ''), hub.params,
                                          body.get('expected_segment'))
            hub.publish()
            return web.json_response(result)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        except RuntimeError as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except OSError:
            return web.json_response({'error': '无法创建或结束记录，请检查磁盘空间和目录权限；未切换标签。'}, status=503)

    async def control_devices(request):
        require_control(request, request.method == 'POST')
        manager = getattr(hub, 'devices', None)
        if manager is None:
            return web.json_response({'available': False, 'error': '请通过新版一键入口重启服务以启用蓝牙管理。'}, status=503)
        if request.method == 'GET':
            return web.json_response(manager.status(), headers={'Cache-Control': 'no-store'})
        if runtime.status().get('stopping'):
            return web.json_response({'error': '本次运行正在结束。'}, status=409)
        try:
            result = await manager.action(await request.json())
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)

    async def devices_page(request):
        raise web.HTTPFound('/console#devices')

    async def control_hud(request):
        require_control(request,True)
        try:
            body=await request.json()
            if not isinstance(body,dict) or type(body.get("visible")) is not bool:
                raise ValueError("visible必须为布尔值")
            result=await runtime.set_hud(body["visible"])
        except (ValueError,TypeError) as exc:
            return web.json_response({"error":str(exc)},status=400)
        return web.json_response(result)

    async def control_shutdown(request):
        require_control(request,True)
        runtime.request_shutdown()
        return web.json_response({"ok":True})

    async def control_panel(request):
        require_control(request,True)
        try:
            runtime.request_panel((await request.json()).get('target'))
            return web.json_response(runtime.status())
        except (ValueError,TypeError,AttributeError):
            return web.json_response({'error':'无效面板'},status=400)

    async def control_edit(request):
        require_control(request,True)
        try:
            editing=(await request.json()).get('editing')
            if type(editing) is not bool:raise ValueError('editing必须为布尔值')
            return web.json_response(await runtime.edit_hud(editing))
        except (ValueError,TypeError,AttributeError):
            return web.json_response({'error':'无效边界设置'},status=400)

    async def events(request: web.Request) -> web.StreamResponse:
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        hub.queues.add(queue)
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        })
        await response.prepare(request)
        try:
            await response.write(f"data: {json.dumps(hub.snapshot())}\n\n".encode())
            while True:
                try:
                    snap = await asyncio.wait_for(queue.get(),timeout=2)
                except asyncio.TimeoutError:
                    if request.transport is None or request.transport.is_closing(): break
                    snap=hub.snapshot()  # Service heartbeat remains live without a BLE reading.
                await response.write(f"data: {json.dumps(snap)}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            hub.queues.discard(queue)
        return response

    @web.middleware
    async def local_mutations(request, handler):
        if request.method == "POST":
            origin=request.headers.get("Origin")
            if origin and origin != str(request.url.origin()):
                raise web.HTTPForbidden()
        return await handler(request)

    app = web.Application(middlewares=[local_mutations])
    app.router.add_get("/", index)
    app.router.add_get("/pixel.html", index)
    app.router.add_get("/monitor", monitor)
    app.router.add_get("/live.js", live_js)
    app.router.add_get("/control.js",control_js)
    app.router.add_get("/devices.js",devices_js)
    app.router.add_get("/control.css",control_css)
    app.router.add_get("/studio-theme.css",studio_theme)
    app.router.add_get("/params/schema", schema)
    app.router.add_get("/plain", plain)
    app.router.add_get("/effects", effects)
    app.router.add_get("/tune", tune)
    app.router.add_get("/console", console)
    app.router.add_get("/devices", devices_page)
    app.router.add_get("/control/devices", control_devices)
    app.router.add_post("/control/devices", control_devices)
    app.router.add_get("/test", test_bench)
    app.router.add_get("/theme.css", theme)
    assets_dir = HERE / 'web' / 'assets'
    if assets_dir.is_dir():
        app.router.add_static('/assets', assets_dir)
    else:
        log.warning('assets 目录缺失，图片皮肤不可用：%s', assets_dir)
    app.router.add_get("/logs", logs_list)
    app.router.add_get("/replay", replay)
    app.router.add_post("/calibrate", calibrate)
    app.router.add_get("/calibrate", calibrate)
    app.router.add_get("/hr", hr)
    app.router.add_get("/params", params_get)
    app.router.add_post("/params", params_post)
    app.router.add_get("/bpm", bpm)
    app.router.add_get("/events", events)
    app.router.add_get("/history", history)
    app.router.add_get("/reset", reset)
    app.router.add_post("/reset", reset)
    app.router.add_get("/health", health)
    app.router.add_get('/render/layout',render_layout)
    app.router.add_get('/render/xianyu/{frame}.png',render_sprite)
    app.router.add_get("/control",control_get)
    app.router.add_get('/control/recording', control_recording)
    app.router.add_post('/control/recording', control_recording)
    app.router.add_post("/control/hud",control_hud)
    app.router.add_post("/control/shutdown",control_shutdown)
    app.router.add_post('/control/panel',control_panel)
    app.router.add_post('/control/hud-edit',control_edit)
    return app


async def main_async(args: argparse.Namespace) -> None:
    hub = Hub(warn=args.warn, danger=args.danger, stale_after=args.stale_after,
              history_len=args.history)
    if not args.no_csv:
        path = hub.start_csv(Path(args.csv_dir))
        log.info("logging to %s", path)

    address = args.address
    stop = asyncio.Event()

    async def periodic_publish() -> None:
        while not stop.is_set():
            await asyncio.sleep(1.0)
            hub.publish()

    def new_device_session():
        # Keep different sources out of the same raw CSV; preserve all older files.
        if not args.no_csv:
            # A different wearer's data must not inherit an active game label.
            hub.recording._rotate('unmarked', '', hub.params, 'device_changed')

    hub.devices = DeviceManager(hub, DEVICES_FILE, parse_bpm, address, args.name,
                                on_switch=new_device_session)
    runtime = RuntimeControl(HERE, f"http://127.0.0.1:{args.port}",stop,hub.publish)
    runner = web.AppRunner(build_app(hub,runtime), shutdown_timeout=1)
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    log.info("web server on http://%s:%d/   (OBS browser source)", args.host, args.port)

    tasks = [
        asyncio.create_task(ble_loop(hub, address, stop, args.name, args.scan_attempts), name="ble"),
        asyncio.create_task(periodic_publish(), name="publish"),
    ]
    try:
        await stop.wait()
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await hub.devices.close()
        await runtime.close()
        hub.close_csv()
        await runner.cleanup()


async def find_hr_by_gatt(address: str, timeout: float = 8.0) -> bool:
    """连上去看设备有没有暴露标准心率服务 (0x180D)。

    为什么要这么绕：实测（Amazfit Pop Pro、华为手环）**广播包里根本不带 0x180D**，
    所以"从广播 UUID 里找心率设备"这条路在真机上不可靠，必须问 GATT。
    """
    try:
        from bleak import BleakClient
    except ImportError:
        return False
    try:
        async with BleakClient(address, timeout=timeout) as client:
            for service in client.services:
                if str(service.uuid).lower().startswith("0000180d"):
                    return True
    except Exception as exc:  # noqa: BLE001
        log.debug("GATT 探测 %s 失败：%s", address, exc)
    return False


async def scan_for_heart_rate(timeout: float = 8.0, name: str | None = None,
                              max_probe: int = 6, attempts: int = 1,
                              gap: float = 10.0) -> str | None:
    """找一个能用的心率设备地址，返回 None 表示多轮之后仍没找到。

    为什么要多轮：实测这块手环只在有限时间窗内广播（空闲 90 秒都没出现在扫描里），
    单轮 8 秒必然经常扑空，所以默认 5 轮、轮间等 10 秒。

    每轮两阶段（顺序有讲究）：
        0) 先试历史成功地址（devices.json）—— 最快
        A) 再看广播里显式声明了心率服务 0x180D 的设备 —— 快（不是所有设备都这样）
        B) 最后对信号最强的几台依次做 GATT 探测 —— 慢，但真机上往往只有这条路走得通
    给了 --name 就只探测名字匹配的设备，避免去连一堆陌生 BLE 设备。
    """
    from bleak import BleakScanner

    for attempt in range(1, max(1, attempts) + 1):
        result = await _scan_once(timeout, name, max_probe, attempt, attempts)
        if result:
            return result
        if attempt < attempts:
            log.info("%d/%d 轮没找到，等 %.0f 秒再试（可以现在唤醒手环/重新开「心率广播」）…",
                     attempt, attempts, gap)
            await asyncio.sleep(gap)
    return None


async def _scan_once(timeout: float, name: str | None, max_probe: int,
                     attempt: int, attempts: int) -> str | None:
    """单轮扫描：直连记忆地址 → 广播声明 → GATT 探测。"""
    from bleak import BleakScanner

    # 0) 先试历史成功地址：手环可能只在某个时间窗广播，直连是唯一快的路径
    for known in ([] if name else load_known_devices()):
        if await find_hr_by_gatt(known, timeout=6.0):
            log.info("直连上次成功过的设备：%s", known)
            return known
        log.info("历史地址 %s 这次没连上，继续扫描", known)

    log.info("第 %d/%d 轮：扫描 BLE 广播（%.0f 秒）%s…", attempt, attempts, timeout,
             f"，名字过滤：{name}" if name else "")
    try:
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except Exception as exc:  # noqa: BLE001
        log.error("扫描失败：%s", exc)
        return None

    exact: list[str] = []
    candidates: list[tuple[float, str, str | None]] = []

    for address, (device, adv) in devices.items():
        dev_name = device.name or adv.local_name
        uuids = [str(u).lower() for u in (adv.service_uuids or [])]
        if any("180d" in u for u in uuids):
            log.info("广播即声明心率服务：%s (%s)", dev_name or "?", address)
            exact.append(address)
        if name:
            if dev_name and name.lower() in dev_name.lower():
                candidates.append((adv.rssi or -999, address, dev_name))
        else:
            candidates.append((adv.rssi or -999, address, dev_name))

    if not exact and not candidates:
        log.warning("附近没有可探测的 BLE 设备")
        return None

    # 先 GATT 探测 A 阶段命中的（信号强的优先），再退到"名字匹配但没声明服务"的
    candidates.sort(key=lambda row: -row[0])
    probe_order: list[tuple[float, str, str | None]] = []
    seen: set[str] = set()
    for address in exact:
        seen.add(address)
        probe_order.append((0.0, address, None))
    for row in candidates:
        if row[1] not in seen:
            seen.add(row[1])
            probe_order.append(row)

    if not exact:
        log.info("没有设备在广播里声明 0x180D，改为逐台连上探测 GATT（最多 %d 台）…", max_probe)
    for rssi, address, dev_name in probe_order[:max_probe + len(exact)]:
        if await find_hr_by_gatt(address):
            log.info("发现心率设备：%s (%s)", dev_name or "?", address)
            remember_device(address)
            return address
        log.info("  %s (%s) 没有心率服务，跳过", dev_name or "?", address)

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="BLE heart rate -> pixel-art web overlay")
    parser.add_argument("--address", default=DEFAULT_ADDRESS,
                        help="BLE 地址（如 AA:BB:CC:DD:EE:FF）；留空则自动扫描 + GATT 探测")
    parser.add_argument("--name", default=None,
                        help="按设备名（子串匹配）自动找设备，用于多台 BLE 设备的环境")
    parser.add_argument("--scan-attempts", type=int, default=3,
                        help="自动扫描的轮数（每轮约 40 秒；手环广播时间窗短时可调大）")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--warn", type=float, default=None, help="bpm for 'fast' state")
    parser.add_argument("--danger", type=float, default=None, help="bpm for 'alarm' state")
    parser.add_argument("--stale-after", type=float, default=12.0)
    parser.add_argument("--history", type=int, default=600, help="rolling samples to keep")
    parser.add_argument("--csv-dir", default=str(HERE / "logs"))
    parser.add_argument("--no-csv", action="store_true")
    parser.add_argument("--forget", action="store_true",
                        help="清掉 devices.json 里记住的设备地址后退出")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.forget:
        DEVICES_FILE.unlink(missing_ok=True)
        print(f"已清除 {DEVICES_FILE}")
        return
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
