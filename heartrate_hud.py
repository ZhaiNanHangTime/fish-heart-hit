"""咸鱼突刺 · 桌面置顶悬浮窗（极简透明版）

只有三样东西：
    * 红色心率线 —— 横穿窗口中央，起伏随心率变化
    * 像素咸鱼   —— 左侧，背矛 + 小令旗，随心率突刺
    * 心率数字   —— 白色像素字 + 深色投影，压在线上

没有背景框、没有统计、没有电量，整体透明，适合叠在游戏画面上。

用法:
    python heartrate_hud.py                 # 默认
    python heartrate_hud.py --scale 4       # 放大（2~5）
    python heartrate_hud.py --opaque        # 不透明背景（调试/兼容）
    python heartrate_hud.py --skin ghost    # 幽灵皮肤（缺省跟随服务端 /params 的 skin）

操作:
    左键拖动 / 右键菜单（重置、置顶、退出）/ 双击换大小
    位置记在 hud.json
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "hud.json"
TRANSPARENT_KEY = "#ff00fe"

FONT = {
    '0': ['111', '101', '101', '101', '111'], '1': ['010', '110', '010', '010', '111'],
    '2': ['111', '001', '111', '100', '111'], '3': ['111', '001', '111', '001', '111'],
    '4': ['101', '101', '111', '001', '001'], '5': ['111', '100', '111', '001', '111'],
    '6': ['111', '100', '111', '101', '111'], '7': ['111', '001', '001', '001', '001'],
    '8': ['111', '101', '111', '101', '111'], '9': ['111', '101', '111', '001', '111'],
    '-': ['000', '000', '111', '000', '000'], ' ': ['000', '000', '000', '000', '000'],
}

SKIN = {
    'rest':   {'body': '#e8e6df', 'hi': '#ffffff', 'shade': '#9aa3ad', 'line': '#2b2f36'},
    'warn':   {'body': '#f6e2d6', 'hi': '#fff7f2', 'shade': '#cba48e', 'line': '#2b2f36'},
    'danger': {'body': '#ffb3a6', 'hi': '#ffd9d0', 'shade': '#e05a4a', 'line': '#2b2f36'},
    'idle':   {'body': '#dfe3e8', 'hi': '#f4f6f8', 'shade': '#a9b2bd', 'line': '#3a4048'},
}
TRACE = '#ff3b30'
TRACE_DARK = '#a01f18'
DIGIT = '#ffffff'
DIGIT_SHADOW = '#101319'
ACCENT = {'cool': '#3ad6c8', 'hot': '#ffb03a', 'danger': '#ff2f2f', 'dim': '#6b7787'}
FIN = '#ff8a5c'
SWEAT = '#bfe9ff'
PANEL = '#0f1116'

FISH_W, FISH_H = 18, 13

# ---------- 幽灵皮肤（与 web/pixel.html 的 GHOST_ROWS 一致） ----------
GHOST_W, GHOST_H = 14, 14
GHOST_ROWS = [
    '.....####.....',
    '...########...',
    '..##########..',
    '.############.',
    '##############',
    '##EE######EE##',
    '##############',
    '######TT######',
    '######TT######',
    '######TT######',
    '##############',
    '##############',
    '####..##..####',
    '####..##..####',
]
GHOST_BASE = {'body': '#f4f6fa', 'line': '#2b2f36', 'E': '#1a1d24', 'T': '#ff3b30'}
GHOST_IDLE = {'body': '#aeb4c0', 'line': '#2b2f36', 'E': '#7c8492', 'T': '#7c8492'}
CGX, CGY, RX, RY = 7.2, 6.4, 6.6, 4.6
TAIL = ((13.4, 5, 3), (14.4, 4, 5), (15.4, 3, 7), (16.4, 2, 9))

SPEAR_N = 24
SPEAR_BX, SPEAR_BY = 0.5, 14.5
SPEAR_DX, SPEAR_DY = 0.55, -0.55
SPEAR_SHAFT = '#7a4a1e'
SPEAR_SHAFT_DARK = '#4d2d10'
SPEAR_WING = '#aeb8c2'
SPEAR_HEAD = ((0.00, 0.00, 1.00, '#cfd8e2'), (0.60, -0.60, 1.00, '#e4ebf3'),
              (1.20, -1.20, 0.85, '#f6faff'), (1.80, -1.80, 0.60, '#ffffff'))
SPEAR_FLAG = ((0.55, -1.95, 1.60, 1.50, '#d43232'),
              (1.75, -1.72, 1.50, 1.40, '#d43232'),
              (2.90, -1.50, 1.20, 1.10, '#8e1f1f'))


def _inside(gx: float, gy: float) -> bool:
    nx, ny = (gx - CGX) / RX, (gy - CGY) / RY
    return nx * nx + ny * ny <= 1.0


def _dist(gx: float, gy: float) -> float:
    nx, ny = (gx - CGX) / RX, (gy - CGY) / RY
    return nx * nx + ny * ny


# ---------- 心率 → 颜色（连续渐变） ----------

def mix_color(c1: str, c2: str, k: float) -> str:
    k = max(0.0, min(1.0, k))
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return '#%02x%02x%02x' % tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


# ---------- 冻结版算法参数（启动时会被服务端 /params 覆盖） ----------
P = {
    "minGap": 22.0,      # R ≥ B + minGap（防假红，实测甜点 22）
    "maxGap": 30.0,      # R ≤ B + maxGap（防抗红；原来 45 会让 R 顶到 114）
    "p90Offset": 3.0,    # R = P90 − 该值
    "yellowAt": 0.4,     # 黄锚在 B→R 区间的位置
    "orangeAt": 0.7,     # 橙锚位置
    "anchorTau": 15.0,   # 阈值跟随时间常数（秒）
    "attack": 2.0,       # 上色时间常数（秒）
    "release": 6.0,      # 褪色时间常数（秒）
    "redHold": 2.0,      # 连续达阈值多久算满红（秒）
    "redDrop": 5.0,      # 回落多少解除满红（bpm）
    "offlineAfter": 5.0, # 多久没数据算离线（秒）
    "burstRise": 10.0,   # 窗口内涨多少触发特效（bpm）
    "burstAbove": 15.0,  # 且要高于基线多少（bpm）
    "burstWindow": 30.0, # 涨幅观察窗口（秒）
    "burstCooldown": 30.0,  # 特效冷却（秒）
}
BASE_FALLBACK = 70.0
BASE_SAMPLES = 40
LOCKED_BASE: float | None = None     # 服务端在开播头 3 分钟锁定后下发，之后不再漂移
SKIN_NAME = 'fish'                    # 当前皮肤：fish（咸鱼）/ ghost（幽灵）


def load_remote_params(base: str, apply_skin: bool = True) -> None:
    """把 /tune 面板保存到服务端的参数拉过来。

    apply_skin=False 时只同步数值参数、不动皮肤（渲染验收脚本用）。
    """
    try:
        with urlopen(f"{base}/params", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for k, v in (data or {}).items():
            if k in P:
                try:
                    P[k] = float(v)
                except (TypeError, ValueError):
                    pass
            elif k == 'skin' and apply_skin and str(v) in ('fish', 'ghost'):
                global SKIN_NAME
                SKIN_NAME = str(v)
    except Exception:  # noqa: BLE001
        pass


def log_skin_change(old: str, new: str) -> None:
    print(f"[hud] 皮肤切换：{old} → {new}", file=sys.stderr, flush=True)


def base_heart(stats: dict) -> float:
    if LOCKED_BASE is not None:
        return LOCKED_BASE
    s = stats or {}
    if (s.get("samples") or 0) >= BASE_SAMPLES and s.get("min") is not None and s.get("avg") is not None:
        # 锁定前的临时估计：落在「本场最低」与「本场平均」之间偏平静的一侧（1/4 处）
        return max(45.0, float(s["min"]) + (float(s["avg"]) - float(s["min"])) * 0.25)
    return BASE_FALLBACK


def intensity_of(bpm, anchors) -> float:
    if bpm is None or not anchors:
        return 0.0
    b, r = anchors
    return max(0.0, min(1.0, (bpm - b) / max(1.0, r - b)))


def color_of_intensity(p: float) -> str:
    """强度 → 颜色：0 白 · yellowAt 黄 · orangeAt 橙 · 1 红。"""
    q = max(0.0, p)
    y, o = P["yellowAt"], P["orangeAt"]
    if q <= y:
        return mix_color('#ffffff', '#ffe066', q / max(0.05, y))
    if q <= o:
        return mix_color('#ffe066', '#ffa53a', (q - y) / max(0.05, o - y))
    return mix_color('#ffa53a', '#ff3b30', min(1.0, (q - o) / max(0.05, 1.0 - o)))


class HeartHud:
    def __init__(self, api: str, scale: int, opaque: bool = False,
                 apply_skin: bool = True, watch_skin: bool = True) -> None:
        self.api = api
        self.base = api.rsplit("/hr", 1)[0]
        self.scale = scale
        self.follow_remote_skin = watch_skin          # False = 已按服务端皮肤重启过，别再重启
        load_remote_params(self.base, apply_skin=apply_skin)   # 拉取 /tune 面板保存的参数
        self.state: dict = {"bpm": None, "zone": "idle", "connected": False,
                            "stats": {}, "recent": {}}
        self.history: list = []
        self.phase = 0.0
        # ---- 冻结版算法状态 ----
        self.anchors = None          # [B, R]
        self.p_smooth = 0.0          # 平滑后的强度 0..1
        self.red_since = None        # 满红迟滞计时
        self.fully_red = False
        self.live = False            # 是否有有效且非离线的数据
        self.burst = 0.0             # 特效强度
        self.burst_track: list = []
        self.last_burst = -999.0
        self.last_tick = time.time()
        self.started = time.time()
        self.last_skin_check = 0.0
        self.topmost = True
        self.drag = (0, 0)

        self.root = tk.Tk()
        self.root.title("咸鱼突刺 · 心率")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if opaque:
            self.transparent = False
            self.bg = PANEL
        else:
            try:
                self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
                self.bg = TRANSPARENT_KEY
                self.transparent = True
            except tk.TclError:
                self.bg = PANEL
                self.transparent = False
        self.root.configure(bg=self.bg)

        self._layout()
        self.panel = None
        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h,
                                bg=self.bg, highlightthickness=0, bd=0)
        self.canvas.pack()

        self._build_scene()
        self._restore_position()
        self._bind_events()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.root.after(40, self._tick)

    # ---------- 布局 ----------

    def _layout(self) -> None:
        s = self.scale
        self.pad = s + 2
        self.fish_unit = s
        self.fish_w = FISH_W * s
        self.fish_h = FISH_H * s
        self.dot = 2 * s
        self.digit_w = 4 * self.dot * 3
        self.digit_h = 5 * self.dot
        self.gap = 3 * s
        self.dot_r = max(2, s)

        body_h = max(self.fish_h, self.digit_h)
        self.w = self.pad * 2 + self.fish_w + self.gap + self.digit_w + self.pad * 2
        self.h = self.pad * 2 + body_h + 4 * s
        self.center_y = self.h / 2
        self.amp = max(6, (self.h - self.pad * 2) / 2 * 0.95)

        self.fish_org = (self.pad, self.center_y - self.fish_h / 2 + self.fish_unit * 0.5)
        self.digit_org = (self.pad + self.fish_w + self.gap,
                          self.center_y - self.digit_h / 2)

    # ---------- 场景构建（只做一次） ----------

    def _new(self, w=None, h=None) -> int:
        w = w if w is not None else self.fish_unit
        h = h if h is not None else w
        return self.canvas.create_rectangle(0, 0, w, h, outline="", fill=self.bg)

    def _build_scene(self) -> None:
        u = self.fish_unit

        # 心率线（最底层）
        self.trace = self.canvas.create_line(0, 0, 0, 0, fill=TRACE,
                                             width=max(3, self.scale + 1),
                                             capstyle='butt', joinstyle='miter')
        self.trace_dot = self._new(max(3, self.scale * 1.4))

        # 小矛（先建，鱼身盖住中段）
        self.spear_shaft = [(SPEAR_BX + i * SPEAR_DX, SPEAR_BY + i * SPEAR_DY,
                             self._new(), self._new()) for i in range(SPEAR_N)]
        self.spear_wing = [self._new(u * 0.9), self._new(u * 0.9)]
        self.spear_head = [(dx, dy, sc, self._new(u * sc)) for dx, dy, sc, _c in SPEAR_HEAD]
        self.spear_flag = [(dx, dy, self._new(u * w, u * h)) for dx, dy, w, h, _c in SPEAR_FLAG]

        # 鱼身
        self.body_cells = []
        for gy in range(FISH_H):
            for gx in range(FISH_W):
                d = _dist(gx, gy)
                if d <= 1.0:
                    kind = 'shade' if d > 0.72 else ('hi' if (gy <= CGY - 2 and gx < CGX + 2) else 'body')
                    self.body_cells.append((gx, gy, kind, self._new()))
                elif (_inside(gx - 1, gy) or _inside(gx + 1, gy)
                      or _inside(gx, gy - 1) or _inside(gx, gy + 1)):
                    self.body_cells.append((gx, gy, 'line', self._new()))

        self.tail_cells = [(gx, top + i, 'line' if (i == 0 or i == hgt - 1) else 'fin', self._new())
                           for gx, top, hgt in TAIL for i in range(hgt)]
        self.fin_cells = [(6 + i, 2 - i * 0.4, 'line' if i == 2 else 'fin', self._new())
                          for i in range(3)]
        self.eye = self._new(u * 2)
        self.eye_lid = self._new()
        self.mouth = self._new(u)
        self.gill_cells = [(5, 4.6 + i, self._new(u * 0.7)) for i in range(3)]
        self.sweat = [self._new(u * 0.7), self._new(u * 0.6), self._new(u * 0.5)]

        # 数字（每个块一个投影 + 一个主色）
        self.digit_items = []
        for _ in range(3):
            self.digit_items.append([(r, c, self._new(self.dot), self._new(self.dot))
                                     for r in range(5) for c in range(3)])

        self.status_dot = self._new(self.dot_r * 2)

        # 幽灵皮肤：每格一个填充块（相互重叠 1px 用）+ 四条轮廓条（个/格）
        # 轮廓条只在"朝空白的一侧"显示，因此填充互相重叠也不会吃掉外轮廓
        self.ghost_cells = []
        for gy, row in enumerate(GHOST_ROWS):
            for gx, ch in enumerate(row):
                if ch != '.':
                    self.ghost_cells.append((gx, gy, ch, self._new()))
        self.ghost_out = []            # (gx, gy, 方向, 图元)
        for gx, gy, _ch, _fill in self.ghost_cells:
            for slot in ('u', 'd', 'l', 'r'):
                self.ghost_out.append((gx, gy, slot, self._new()))
        self.ghost_xoff = (FISH_W - GHOST_W) / 2.0   # 幽灵比鱼窄，居中一点
        self.ghost_float = 0.0

        # 图层顺序：线在最底层，鱼身盖住它；数字仍在最上层
        self.canvas.tag_lower(self.trace)
        self.canvas.tag_lower(self.trace_dot)
        for pos in self.digit_items:
            for _r, _c, shadow, main in pos:
                self.canvas.tag_raise(shadow)
                self.canvas.tag_raise(main)
        self.canvas.tag_raise(self.status_dot)

        if not self.transparent:
            self.panel = self.canvas.create_rectangle(0, 0, self.w, self.h,
                                                      fill=PANEL, outline='#232833')
            self.canvas.tag_lower(self.panel)

    # ---------- 位置记忆 ----------

    def _restore_position(self) -> None:
        pos = None
        if SETTINGS.exists():
            try:
                pos = json.loads(SETTINGS.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pos = None
        if pos and "x" in pos and "y" in pos:
            self.root.geometry(f"+{pos['x']}+{pos['y']}")
            self.topmost = bool(pos.get("topmost", True))
            self.root.attributes("-topmost", self.topmost)
        else:
            self.root.geometry(f"+{self.root.winfo_screenwidth() - self.w - 40}+40")

    def _save_position(self) -> None:
        try:
            SETTINGS.write_text(json.dumps({
                "x": self.root.winfo_x(), "y": self.root.winfo_y(),
                "scale": self.scale, "topmost": self.topmost,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ---------- 事件 ----------

    def _bind_events(self) -> None:
        self.canvas.bind("<Button-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: self._save_position())
        self.canvas.bind("<Double-Button-1>", self._toggle_scale)
        self.canvas.bind("<Button-3>", self._menu)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    def _start_drag(self, event) -> None:
        self.drag = (event.x, event.y)

    def _on_drag(self, event) -> None:
        self.root.geometry(f"+{self.root.winfo_x() + event.x - self.drag[0]}"
                           f"+{self.root.winfo_y() + event.y - self.drag[1]}")

    def _toggle_scale(self, _event=None) -> None:
        self.scale = 2 if self.scale >= 5 else self.scale + 1
        self._save_position()
        api, scale = self.api, self.scale
        self.root.destroy()
        subprocess.Popen([sys.executable, str(HERE / "heartrate_hud.py"),
                          "--api", api, "--scale", str(scale)],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _menu(self, event) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="重置统计", command=self._reset)
        menu.add_command(label=f"切换皮肤：{'幽灵' if SKIN_NAME == 'ghost' else '咸鱼'}",
                         command=self._toggle_skin)
        menu.add_command(label=f"置顶：{'开' if self.topmost else '关'}", command=self._toggle_topmost)
        menu.add_separator()
        menu.add_command(label="退出", command=self._quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _reset(self) -> None:
        try:
            urlopen(f"{self.base}/reset", timeout=3).read()
        except Exception:  # noqa: BLE001
            pass

    def _toggle_skin(self) -> None:
        """右键切换皮肤：先把选择写回服务端 /params，再以新皮肤重启自己。

        顺序有讲究：先写服务端，重启出来的新进程读 /params 时才会看到新皮肤，
        不会出现"重启完又变回旧皮肤"。
        """
        new_skin = 'fish' if SKIN_NAME == 'ghost' else 'ghost'
        self._push_skin(new_skin)
        self._restart_with_skin(new_skin)

    def _push_skin(self, new_skin: str) -> None:
        """把皮肤写进服务端参数（写失败不阻塞切换，本地照样生效）。"""
        payload = json.dumps({"skin": new_skin}).encode("utf-8")
        for _attempt in range(2):
            try:
                req = Request(f"{self.base}/params", data=payload,
                              headers={"Content-Type": "application/json"})
                urlopen(req, timeout=3).read()
                return
            except Exception:  # noqa: BLE001
                time.sleep(0.5)

    def _restart_with_skin(self, new_skin: str) -> None:
        """换皮肤要重建画布图元，直接以新 --skin 重启一个自己（与双击换大小同一套路）。

        --no-skin-watch 很关键：否则新进程起来后又发现服务端皮肤与启动参数一致时还好，
        但若不一致就会再次重启，形成重启循环。
        """
        self._save_position()
        api, scale = self.api, self.scale
        self.root.destroy()
        subprocess.Popen([sys.executable, str(HERE / "heartrate_hud.py"),
                          "--api", api, "--scale", str(scale), "--skin", new_skin,
                          "--no-skin-watch"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _toggle_topmost(self) -> None:
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)

    def _quit(self) -> None:
        self._save_position()
        self.root.destroy()

    # ---------- 数据 ----------

    def _poll_loop(self) -> None:
        tick = 0
        while True:
            try:
                with urlopen(self.api, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self.state = {
                    "bpm": data.get("bpm"),
                    "zone": data.get("zone", "idle"),
                    "connected": data.get("connected", False),
                    "stats": data.get("stats", {}) or {},
                    "recent": data.get("recent", {}) or {},
                }
            except Exception:  # noqa: BLE001
                self.state = {"bpm": None, "zone": "idle", "connected": False,
                              "stats": {}, "recent": {}}
            tick += 1
            if tick % 3 == 0:
                try:
                    with urlopen(f"{self.base}/history", timeout=3) as resp:
                        self.history = json.loads(resp.read().decode("utf-8")).get("samples", [])
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.5)

    # ---------- 绘制原语 ----------

    def _show(self, item, color, x, y, size) -> None:
        self.canvas.coords(item, x, y, x + size, y + size)
        self.canvas.itemconfig(item, fill=color, state='normal')

    def _show_rect(self, item, color, x, y, w, h) -> None:
        self.canvas.coords(item, x, y, x + w, y + h)
        self.canvas.itemconfig(item, fill=color, state='normal')

    @staticmethod
    def _span(x: float, size: int) -> tuple[float, float]:
        """把"想覆盖的像素区间"换成 Tk 矩形坐标。

        Tk 的矩形右下边界是**开区间**：coords(x, y, x+N, y+N) 只覆盖 N-1 个像素
        （实测 4px 宽只填 3px）。所以想精确铺 size 个像素，右边界要写 x+size-1+1，
        即 coords 用 [x-0.5, x+size-0.5] —— 同时消除相邻块的取整歧义。
        """
        return x - 0.5, x + size - 0.5

    def _pix(self, item, color, x: float, y: float, size: int) -> None:
        """精确铺一个 size×size 的像素块（左上角对齐 (x, y)）。"""
        x1, x2 = self._span(x, size)
        y1, y2 = self._span(y, size)
        self.canvas.coords(item, x1, y1, x2, y2)
        self.canvas.itemconfig(item, fill=color, state='normal')

    def _pix_rect(self, item, color, x: float, y: float, w: int, h: int) -> None:
        """精确铺一个 w×h 的像素块。"""
        x1, x2 = self._span(x, w)
        y1, y2 = self._span(y, h)
        self.canvas.coords(item, x1, y1, x2, y2)
        self.canvas.itemconfig(item, fill=color, state='normal')

    def _hide(self, item) -> None:
        self.canvas.itemconfig(item, state='hidden')

    # ---------- 绘制 ----------

    # 幽灵的矩形坐标必须落在整像素上，否则会"一闪一闪"。
    # 实测（scale=4，偏移 -4..+4 每 0.25 一点）：凡偏移小数部分 = 0.25 的帧，
    # 身体像素从 1439 突然涨到 1864（+425 ≈ 一整行格子）——tkinter 在 .25 这类
    # 小数上取整会多铺一格。全部对齐整像素后，33 个采样点极差为 0。
    GHOST_STEP_PX = 1.0

    def _quantize_unit(self, gy: int) -> float:
        """幽灵飘浮量的整像素量化（纯函数，便于单测）。"""
        u = self.fish_unit
        raw = math.sin(self.phase * 2 * math.pi) * u * (0.30 + self.burst * 0.75)
        step = max(self.GHOST_STEP_PX, 1.0)
        return round(raw / step) * step

    def _draw_ghost_only(self, line_col: str) -> None:
        """幽灵皮肤：白色圆顶 + 外描边 + 红舌头 + 三瓣波浪底，盖住心率线。

        与网页版一致：冷静偏冷白，激动转暖红；飘浮幅度随爆发变大。
        只画幽灵，不画鱼/矛/鳍/汗滴（那些图元保持构建时的 hidden 状态）。

        注意：这里所有坐标都取整到像素（见 GHOST_STEP_PX 的说明），
        以及描边宽度也取整——两者都为了消除亚像素栅格化带来的闪烁。
        """
        u = self.fish_unit
        ox, oy = self.fish_org
        sleeping = not self.live
        if sleeping:
            palette = GHOST_IDLE
        else:
            flush = self.p_smooth
            palette = {
                'body': mix_color(GHOST_BASE['body'], '#ff9b8a', flush),
                'line': line_col,
                'E': GHOST_BASE['E'],
                'T': GHOST_BASE['T'],
            }

        self.ghost_float = self._quantize_unit(0)
        grow = max(1, round(u * 0.16))
        uu = round(u)
        gy0 = round(oy + self.ghost_float)
        x0 = round(ox + self.ghost_xoff * u)

        for gx, gy, ch, edge, fill in self.ghost_cells:
            x = x0 + gx * uu
            y = gy0 + gy * uu
            self._show_rect(edge, palette['line'], x - grow, y - grow,
                            uu + grow * 2, uu + grow * 2)
            # 网格里 '#' 表示身体，颜色表的键叫 'body'（与网页版 pixelShape 的兜底一致）
            self._show_rect(fill, palette.get(ch) or palette['body'], x, y, uu, uu)
        self._draw_status_and_digits()   # 数字与状态点：两套皮肤共用

    def _draw(self) -> None:
        st = self.state
        bpm = st.get("bpm")
        zone = st.get("zone") if bpm else 'idle'
        if zone not in SKIN:
            zone = 'idle'
        flush = self.p_smooth
        base = SKIN['rest']
        skin = {
            'body': mix_color(base['body'], '#ff9b8a', flush),
            'hi': mix_color(base['hi'], '#ffd0c4', flush),
            'shade': mix_color(base['shade'], '#d4553f', flush),
            'line': base['line'],
        }
        u = self.fish_unit
        ox, oy = self.fish_org

        # ---- 1) 心率线（最底层）----
        self._draw_trace()

        if SKIN_NAME == 'ghost':        # 幽灵皮肤走独立分支，不碰下面鱼的绘制代码
            self._draw_ghost_only(skin['line'])
            return

        sleeping = not self.live
        vigor = 0.75 + flush * 0.5 + self.burst * 0.7     # 心率越高 / 爆发时，突刺越有劲
        thrust = 0.0 if sleeping else (max(0.0, math.sin(self.phase * 2 * math.pi)) ** 3) * vigor
        jitter = (math.sin(time.time() * 37) * u * 0.30) if zone == 'danger' else 0.0
        sx = ox + thrust * u * 1.2 + jitter
        sy = oy + thrust * u * 0.25
        hot = (not sleeping) and flush > 0.35

        # ---- 2) 小矛 ----
        for gx, gy, shaft, shadow in self.spear_shaft:
            self._show(shaft, SPEAR_SHAFT, sx + gx * u, sy + gy * u, u)
            self._show_rect(shadow, SPEAR_SHAFT_DARK, sx + gx * u, sy + (gy + 0.72) * u, u, u * 0.28)

        hx = SPEAR_BX + SPEAR_N * SPEAR_DX
        hy = SPEAR_BY + SPEAR_N * SPEAR_DY
        self._show(self.spear_wing[0], SPEAR_WING, sx + (hx - 0.62) * u, sy + (hy + 0.30) * u, u * 0.9)
        self._show(self.spear_wing[1], SPEAR_WING, sx + (hx + 0.30) * u, sy + (hy - 1.18) * u, u * 0.9)
        for (dx, dy, sc, col), (_dx, _dy, _sc, item) in zip(SPEAR_HEAD, self.spear_head):
            self._show(item, '#ffe9a8' if (hot and dx > 1.5) else col,
                       sx + (hx + dx) * u, sy + (hy + dy) * u, u * sc)

        fwave = math.sin(self.phase * 2 * math.pi) * 0.18
        for (dx, dy, w, h, col), item in zip(SPEAR_FLAG, self.spear_flag):
            self._show_rect(item, '#ff5a5a' if hot else col,
                            sx + (hx + dx) * u, sy + (hy + dy + fwave) * u, u * w, u * h)

        # ---- 3) 鱼身 ----
        for gx, gy, kind, item in self.body_cells:
            self._show(item, skin[kind], sx + gx * u, sy + gy * u, u)
        for gx, gy, kind, item in self.tail_cells:
            self._show(item, skin['line'] if kind == 'line' else FIN, sx + gx * u, sy + gy * u, u)
        for gx, gy, kind, item in self.fin_cells:
            self._show(item, skin['line'] if kind == 'line' else FIN, sx + gx * u, sy + gy * u, u)

        eye_x, eye_y = sx + 3 * u, sy + 5 * u
        if sleeping:
            self._hide(self.eye)
            self._show_rect(self.eye_lid, skin['line'], eye_x, eye_y + u * 0.5, u * 2, u * 0.5)
        else:
            self._hide(self.eye_lid)
            self._show(self.eye, '#7a1414' if zone == 'danger' else skin['line'], eye_x, eye_y, u * 2)

        self._show(self.mouth, skin['line'], sx + 0.2 * u, sy + 6.6 * u, u)
        for gx, gy, item in self.gill_cells:
            self._show(item, skin['shade'], sx + gx * u, sy + gy * u, u * 0.7)

        limit = 3 if flush >= 0.9 else 2 if flush >= 0.6 else 1 if flush >= 0.3 else 0
        for i, item in enumerate(self.sweat):
            if i < limit:
                ph = (self.phase + i / 3.0) % 1.0
                self._show(item, SWEAT,
                           sx + 4 * u - u * (0.6 + i * 0.7) - ph * u * 1.5,
                           sy + 1.5 * u - ph * u * (2.2 + i * 0.5),
                           u * (0.7 - i * 0.12))
            else:
                self._hide(item)

        self._draw_status_and_digits()

    def _draw_status_and_digits(self) -> None:
        """数字（白色 + 深色投影）与右上角状态点 —— 两套皮肤共用。"""
        st = self.state
        bpm = st.get("bpm")
        # ---- 4) 数字（白色 + 深色投影，压在线上）----
        text = f"{int(bpm):03d}" if bpm else "---"
        digit_col = color_of_intensity(self.p_smooth) if self.live else ACCENT['dim']
        if self.fully_red:                                      # 满红：压深
            digit_col = mix_color(digit_col, '#c1130c', 0.55)
        if self.burst > 0.05:                                   # 爆发瞬间提亮
            digit_col = mix_color(digit_col, '#ffffff', self.burst * 0.55)
        dx0, dy0 = self.digit_org
        off = self.dot * 0.34
        for pos in range(3):
            ch = text[pos] if pos < len(text) else ' '
            glyph = FONT.get(ch, FONT[' '])
            for r, c, shadow, main in self.digit_items[pos]:
                bx = dx0 + pos * 4 * self.dot + c * self.dot
                by = dy0 + r * self.dot
                if glyph[r][c] == '1':
                    self._show(shadow, DIGIT_SHADOW, bx + off, by + off, self.dot)
                    self._show(main, digit_col, bx, by, self.dot)
                else:
                    self._hide(shadow)
                    self._hide(main)

        # ---- 5) 状态点 ----
        self._show(self.status_dot,
                   ACCENT['cool'] if bpm else (ACCENT['hot'] if st.get("connected") else ACCENT['danger']),
                   self.w - self.pad - self.dot_r * 2, self.pad, self.dot_r * 2)

    def _draw_trace(self) -> None:
        s = self.scale
        x0, x1 = 0, self.w
        cy = self.center_y
        samples = self.history
        if not samples or len(samples) < 2:
            self.canvas.coords(self.trace, x0, cy, x0, cy)
            self._hide(self.trace_dot)
            return

        vals = [v for _t, v in samples]
        # 3 点移动平均压毛刺，然后让曲线占满整个高度（不留死区）
        n = len(vals)
        smooth = [(vals[max(0, i - 1)] + vals[i] + vals[min(n - 1, i + 1)]) / 3 for i in range(n)]
        mid = (min(smooth) + max(smooth)) / 2
        span = max(3.0, max(smooth) - min(smooth))
        half = span / 2
        total = samples[-1][0] or 1
        t0 = max(0.0, total - 90.0)
        cyc = max(15.0, (total - t0) or 90.0)
        amp = self.amp

        step = max(1, len(samples) // 80)
        pts = []
        for i in range(0, len(samples), step):
            t = samples[i][0]
            if t < t0:
                continue
            px_ = x0 + ((t - t0) / cyc) * (x1 - x0)
            py_ = cy - ((smooth[i] - mid) / half) * amp
            pts.extend((px_, py_))
        if len(pts) < 4:
            self.canvas.coords(self.trace, x0, cy, x0, cy)
            self._hide(self.trace_dot)
            return

        self.canvas.coords(self.trace, *pts)
        self.canvas.itemconfig(self.trace, fill=TRACE)
        # 最右端的心跳亮点（用平滑后的值）
        lx = x0 + ((samples[-1][0] - t0) / cyc) * (x1 - x0)
        ly = cy - ((smooth[-1] - mid) / half) * amp
        d = max(3, s * 1.4)
        self._show(self.trace_dot, '#ffffff', lx - d / 2, ly - d / 2, d)

    def _update_algo(self, bpm, dt: float) -> None:
        """冻结版算法：锚点慢跟随 → 强度 Attack/Release → 满红迟滞 → 突发特效。"""
        global LOCKED_BASE
        now = time.time()
        st = self.state
        if st.get("base") is not None:
            LOCKED_BASE = float(st["base"])     # 服务端锁定后基准不再漂移
        stats = st.get("stats") or {}
        recent = st.get("recent") or {}
        age = st.get("age")
        offline = (not st.get("connected")) or (age is not None and age > P["offlineAfter"])
        self.live = (bpm is not None) and not offline

        # 1) 锚点：R 缓慢跟随，防突然跳变
        b = base_heart(stats)
        p90 = recent.get("p90")
        if p90 is None:
            p90 = b + P["minGap"]
        r_target = min(b + P["maxGap"], max(b + P["minGap"], float(p90) - P["p90Offset"]))
        if self.anchors is None:
            self.anchors = [b, r_target]
        else:
            self.anchors[0] = b
            if dt > 0:
                self.anchors[1] += (r_target - self.anchors[1]) * (1 - math.exp(-dt / P["anchorTau"]))
        r = self.anchors[1]

        # 2) 强度 + Attack / Release
        p_target = intensity_of(bpm, self.anchors) if self.live else 0.0
        tau = P["attack"] if p_target > self.p_smooth else P["release"]
        if dt > 0:
            self.p_smooth += (p_target - self.p_smooth) * (1 - math.exp(-dt / max(0.05, tau)))

        # 3) 满红迟滞
        if self.live and bpm >= r:
            if self.red_since is None:
                self.red_since = now
            if now - self.red_since >= P["redHold"]:
                self.fully_red = True
        elif (not self.live) or bpm < r - P["redDrop"]:
            self.red_since = None
            self.fully_red = False

        # 4) 突发特效（独立通道 + 冷却）
        if self.live:
            self.burst_track.append((now, bpm))
            while self.burst_track and now - self.burst_track[0][0] > P["burstWindow"]:
                self.burst_track.pop(0)
            rise = bpm - self.burst_track[0][1]
            if (rise >= P["burstRise"] and bpm >= b + P["burstAbove"]
                    and now - self.last_burst >= P["burstCooldown"]):
                self.burst = 1.0
                self.last_burst = now
        else:
            self.burst_track.clear()
        self.burst = max(0.0, self.burst - dt * 1.1)

    def _tick(self) -> None:
        now = time.time()
        dt = min(0.2, now - self.last_tick)
        self.last_tick = now
        # 服务端皮肤变了（网页/控制台改的）→ 重启自己跟上；刚启动 2 秒内不查，避免竞态
        if (getattr(self, 'follow_remote_skin', True)
                and now - self.started > 2.0 and now - self.last_skin_check > 2.0):
            self.last_skin_check = now
            before = SKIN_NAME
            load_remote_params(self.base)
            if SKIN_NAME != before:
                log_skin_change(before, SKIN_NAME)
                self._restart_with_skin(SKIN_NAME)
                return
        bpm = self.state.get("bpm")
        self._update_algo(bpm, dt)
        self.phase = (self.phase + ((bpm / 60.0) if (self.live and bpm) else 0.15) * dt) % 1.0
        self._draw()
        self.root.after(40, self._tick)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal transparent HUD for the heart-rate bridge")
    parser.add_argument("--api", default="http://127.0.0.1:8080/hr")
    parser.add_argument("--scale", type=int, default=3, choices=[2, 3, 4, 5])
    parser.add_argument("--opaque", action="store_true", help="不透明背景（调试/兼容）")
    parser.add_argument("--skin", default=None, choices=["fish", "ghost"],
                        help="皮肤：fish（咸鱼）/ ghost（幽灵）；缺省则跟随服务端 /params")
    parser.add_argument("--no-skin-watch", action="store_true",
                        help="不跟随服务端皮肤变化（重启自身时用，避免重启循环）")
    args = parser.parse_args()
    if args.skin:
        global SKIN_NAME
        SKIN_NAME = args.skin
    HeartHud(args.api, args.scale, opaque=args.opaque,
             watch_skin=not args.no_skin_watch).run()


if __name__ == "__main__":
    main()
