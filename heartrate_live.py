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
from datetime import datetime
from pathlib import Path

from aiohttp import web
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

# 可调参数的默认值（与网页里的 P 对象保持一致）
DEFAULT_PARAMS = {
    "skin": "fish",              # 皮肤：fish（咸鱼）/ ghost（幽灵）/ xianyu（咸鱼突刺）
    "minGap": 22, "maxGap": 30, "p90Offset": 3, "anchorTau": 15,
    "yellowAt": 0.4, "orangeAt": 0.7,
    "attack": 2, "release": 6, "redHold": 2, "redDrop": 5, "offlineAfter": 5,
    "burstRise": 10, "burstAbove": 15, "burstWindow": 30, "burstCooldown": 30,
}


def load_params() -> dict:
    params = dict(DEFAULT_PARAMS)
    if PARAMS_FILE.exists():
        try:
            saved = json.loads(PARAMS_FILE.read_text(encoding="utf-8"))
            for k, v in (saved or {}).items():
                if k in params:
                    params[k] = v
        except Exception:  # noqa: BLE001
            pass
    return params


def save_params(values: dict) -> dict:
    params = load_params()
    for k, v in (values or {}).items():
        if k not in params:
            continue
        if isinstance(params[k], str):          # 皮肤这类字符串参数
            params[k] = str(v)
            continue
        try:
            params[k] = float(v)
        except (TypeError, ValueError):
            pass
    PARAMS_FILE.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    return params


_PARAMS_CACHE: dict = {"mtime": -1.0, "data": None}


def current_params() -> dict:
    """带 mtime 缓存的参数读取 —— 供 snapshot 每帧调用，不做无谓的文件 IO。"""
    try:
        mt = PARAMS_FILE.stat().st_mtime if PARAMS_FILE.exists() else 0.0
    except OSError:
        mt = 0.0
    if _PARAMS_CACHE["data"] is None or mt != _PARAMS_CACHE["mtime"]:
        _PARAMS_CACHE["mtime"] = mt
        _PARAMS_CACHE["data"] = load_params()
    return _PARAMS_CACHE["data"]

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
        self.warn = warn
        self.danger = danger
        self.stale_after = stale_after

        self.history: deque[tuple[float, int]] = deque(maxlen=history_len)
        self.session_started = time.time()
        self.samples = 0
        self.total = 0
        self.minimum: int | None = None
        self.maximum: int | None = None

        self.battery: int | None = None
        self.battery_at: float = 0.0
        self.base_bpm: int | None = None      # 开播头 3 分钟锁定的个人平静基准

        self.queues: set[asyncio.Queue] = set()
        self.csv_writer = None
        self.csv_file = None

    # ---------- data intake ----------

    def start_csv(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"heart-rate-{datetime.now():%Y%m%d-%H%M%S}.csv"
        self.csv_file = path.open("w", newline="", encoding="utf-8-sig")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["timestamp", "iso_time", "bpm"])
        return path

    def close_csv(self) -> None:
        if self.csv_file:
            with contextlib.suppress(Exception):
                self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None

    def set_bpm(self, bpm: int) -> None:
        if not 20 <= bpm <= 250:  # ignore obvious garbage
            return
        now = time.time()
        self.bpm = bpm
        self.updated_at = now
        self.history.append((now, bpm))
        self.samples += 1
        self.total += bpm
        self.minimum = bpm if self.minimum is None else min(self.minimum, bpm)
        self.maximum = bpm if self.maximum is None else max(self.maximum, bpm)
        if self.csv_writer:
            with contextlib.suppress(Exception):
                self.csv_writer.writerow([f"{now:.3f}", datetime.now().isoformat(timespec="seconds"), bpm])
                self.csv_file.flush()
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

    def calibrate_base(self) -> None:
        """开播头 3 分钟锁定个人平静基准，之后不再随整场最低值漂移。

        为什么必须在开播时锁定：如果 B 用「全场累计的 min/avg」，
        那么开播初期样本少、min 偏高 → B 偏高 → R 被顶到很高；
        等你后来跑出低点，B 才降下来，但那时 R 已经错过你的高峰了。
        （真实数据里出现过 R 高达 114、而本人峰值只有 104 的情况）
        """
        if self.base_bpm is not None:
            return
        now = time.time()
        if now - self.session_started < 180 or len(self.history) < 30:
            return
        vals = sorted(v for _t, v in self.history)
        self.base_bpm = vals[max(0, int(len(vals) * 0.10))]   # 10 分位 ≈ 刚坐下的平静水平

    def calibrate_now(self, window: float = 60.0) -> None:
        """手动校准：用最近 60 秒的 25 分位当基准（点按钮时应当刚坐下平静）。"""
        cutoff = time.time() - window
        vals = sorted(v for t, v in self.history if t >= cutoff)
        if len(vals) < 10:                       # 样本不够就用最近的全部
            vals = sorted(v for _t, v in self.history)[-60:]
        if not vals:
            return
        self.base_bpm = vals[max(0, int(len(vals) * 0.25))]

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
            "samples": n,
            "window": window,
        }

    def snapshot(self) -> dict:
        self.calibrate_base()
        age = (time.time() - self.updated_at) if self.updated_at else None
        live = self.bpm is not None and age is not None and age < self.stale_after
        bpm = self.bpm if live else None
        if bpm is None:
            zone = "idle"
        elif bpm >= self.danger:
            zone = "danger"
        elif bpm >= self.warn:
            zone = "warn"
        else:
            zone = "rest"
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
            "skin": current_params().get("skin", "fish"),
            "recent": self.recent_stats(),
            "warn": self.warn,
            "danger": self.danger,
        }

    def publish(self) -> None:
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


async def ble_loop(hub: Hub, address: str | None, stop: asyncio.Event) -> None:
    """Keep the heart-rate subscription alive forever.

    address 为 None（或设备找不到）时会重新扫描，因此不依赖写死的地址，
    也容忍 macOS 每次连接都换随机地址的行为。
    """
    holder = {"addr": address or next(iter(load_known_devices()), None)}
    backoff = 2.0
    while not stop.is_set():
        try:
            addr = holder["addr"]
            device = await BleakScanner.find_device_by_address(addr, timeout=15.0) if addr else None
            if device is None:
                if addr:
                    log.warning("device not advertising; rescanning in %.0fs", backoff)
                else:
                    log.info("no address yet; scanning for a heart-rate broadcaster…")
                hub.connected = False
                hub.publish()
                found = await scan_for_heart_rate()
                if found is None:
                    log.warning("no heart-rate device found; retry in %.0fs", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.6, 30.0)
                    continue
                if found != holder["addr"]:
                    log.info("using address %s", found)
                    holder["addr"] = found
                device = await BleakScanner.find_device_by_address(holder["addr"], timeout=15.0)
                if device is None:
                    log.warning("device vanished right after scan; retry in %.0fs", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.6, 30.0)
                    continue
                backoff = 2.0
            else:
                async with BleakClient(device, timeout=25.0) as client:
                    hub.connected = True
                    backoff = 2.0
                    log.info("connected to %s", device.address)
                    remember_device(device.address)
                    await read_battery(client, hub)

                    def on_data(_sender, data: bytearray) -> None:
                        try:
                            hub.set_bpm(parse_bpm(bytes(data)))
                        except Exception as exc:  # noqa: BLE001
                            log.debug("bad notification: %s", exc)

                    await client.start_notify(HR_MEASUREMENT, on_data)
                    log.info("subscribed to heart-rate notifications")
                    last_battery = time.time()
                    while client.is_connected and not stop.is_set():
                        await asyncio.sleep(1.0)
                        if time.time() - last_battery > 300:
                            last_battery = time.time()
                            await read_battery(client, hub)
                    with contextlib.suppress(Exception):
                        await client.stop_notify(HR_MEASUREMENT)
        except Exception as exc:  # noqa: BLE001
            log.warning("BLE error: %s: %s", type(exc).__name__, exc)

        hub.connected = False
        hub.publish()
        if stop.is_set():
            break
        log.info("link down; retrying in %.0fs", backoff)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        backoff = min(backoff * 1.5, 15.0)


FALLBACK_PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>Heart Rate</title></head><body style="background:transparent;color:#fff;
font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<span id="v" style="font-size:64px;color:#ff5a3c">--</span>
<script>const es=new EventSource('/events');
es.onmessage=e=>{const s=JSON.parse(e.data);document.getElementById('v').textContent=s.bpm??'--';};</script>
</body></html>"""


def build_app(hub: Hub) -> web.Application:
    async def index(_request: web.Request) -> web.Response:
        page = HERE / "web" / "pixel.html"
        if page.exists():
            return web.Response(text=page.read_text(encoding="utf-8"),
                                content_type="text/html", charset="utf-8")
        return web.Response(text=FALLBACK_PAGE, content_type="text/html", charset="utf-8")

    async def effects(_request: web.Request) -> web.Response:
        """Local-only visual sandbox. The iframe uses demo=1, never the BLE stream."""
        return web.FileResponse(HERE / 'web' / 'effects.html')

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
        return web.json_response(load_params())

    async def params_post(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        return web.json_response(save_params(body))

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
        logs_dir = HERE / "logs"
        items = []
        for f in sorted(logs_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]:
            try:
                with f.open(encoding="utf-8-sig") as fh:
                    n = max(0, sum(1 for _ in fh) - 1)
            except Exception:  # noqa: BLE001
                n = 0
            items.append({"name": f.name, "samples": n,
                          "kb": round(f.stat().st_size / 1024, 1),
                          "mtime": f.stat().st_mtime})
        return web.json_response(items)

    async def replay(request: web.Request) -> web.Response:
        """对某份真实记录跑一遍当前参数，返回三个验收指标。"""
        name = request.query.get("file", "")
        logs_dir = (HERE / "logs").resolve()
        try:
            path = (logs_dir / name).resolve()
            path.relative_to(logs_dir)          # 防目录穿越
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "bad path"}, status=400)
        if not path.exists():
            return web.json_response({"error": "not found"}, status=404)

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
        rc.P["minGap"] = load_params()["minGap"]      # 用当前面板参数回放
        res = rc.replay(rows)
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
        hub.calibrate_now()
        return web.json_response({"base": hub.base_bpm})

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

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "connected": hub.connected})

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
                snap = await queue.get()
                await response.write(f"data: {json.dumps(snap)}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            hub.queues.discard(queue)
        return response

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/plain", plain)
    app.router.add_get("/effects", effects)
    app.router.add_get("/tune", tune)
    app.router.add_get("/console", console)
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
    return app


async def main_async(args: argparse.Namespace) -> None:
    hub = Hub(warn=args.warn, danger=args.danger, stale_after=args.stale_after,
              history_len=args.history)
    if not args.no_csv:
        path = hub.start_csv(Path(args.csv_dir))
        log.info("logging to %s", path)

    address = args.address
    if not address:
        log.info("未指定 --address，自动寻找心率设备（先试记住的地址，再扫描 + GATT 探测，"
                 "最长约 %d 秒）…", int(args.scan_attempts * 40))
        address = await scan_for_heart_rate(name=args.name, attempts=args.scan_attempts)
        if address is None:
            log.error("多轮扫描都没找到心率设备。请确认手环已开启「心率广播」并让屏幕亮着，"
                      "然后重试；若手环广播时间窗很短，建议手动指定一次地址，"
                      "之后会被记住：--address AA:BB:CC:DD:EE:FF 或 --name 设备名")
            hub.close_csv()
            return
        log.info("使用设备 %s", address)

    stop = asyncio.Event()

    async def periodic_publish() -> None:
        while not stop.is_set():
            await asyncio.sleep(2.0)
            hub.publish()

    runner = web.AppRunner(build_app(hub))
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    log.info("web server on http://%s:%d/   (OBS browser source)", args.host, args.port)

    tasks = [
        asyncio.create_task(ble_loop(hub, address, stop), name="ble"),
        asyncio.create_task(periodic_publish(), name="publish"),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
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
    parser.add_argument("--warn", type=float, default=120.0, help="bpm for 'fast' state")
    parser.add_argument("--danger", type=float, default=150.0, help="bpm for 'alarm' state")
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
