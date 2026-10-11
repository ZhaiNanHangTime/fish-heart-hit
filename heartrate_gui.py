#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""咸鱼突刺 · 桌面控制台

一个窗口搞定：看心率、启停服务、校准基准、调参、开各个页面。
只用 Python 自带的 tkinter，不依赖第三方库。
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
API = "http://127.0.0.1:8080"
ADDRESS = None                            # None = 启动时自动扫描
PY = sys.executable

# 配色与 web/theme.css 同源：全部取自直播画面里那条鱼
BG, CARD, FG, DIM = "#191d26", "#20252f", "#e8e6df", "#737b8c"
EDGE = "#39414f"
BONE_DIM = "#a9a59b"
ACC, OK, BTN = "#ff8a5c", "#3ad6c8", "#2a3140"
GOLD, EMBER = "#ffd166", "#ff3b30"

SLIDERS = [
    ("minGap",        "满红阈值余量", 10, 40, 1,  "越小越容易红"),
    ("maxGap",        "阈值上限余量", 25, 60, 1,  "限制 R 的上限"),
    ("p90Offset",     "P90 偏移",     0, 15, 1,  "R = P90 − 该值"),
    ("burstRise",     "特效涨幅",     3, 25, 1,  "涨这么多就爆发"),
    ("burstCooldown", "特效冷却(秒)", 0, 180, 5, "防频繁闪烁"),
]


def api_get(path: str, timeout: float = 3.0):
    with urlopen(API + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(path: str, payload: dict, timeout: float = 6.0):
    data = json.dumps(payload).encode("utf-8")
    req = Request(API + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Console:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("咸鱼突刺 · 心率控制台")
        root.configure(bg=BG)
        root.geometry("580x700+60+40")
        root.minsize(540, 640)
        self.params: dict = {}
        self.slider_vars: dict = {}
        self._build()
        self.tick()

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        # 滑杆改用 clam 主题才能自定义配色（默认的系统灰和主题不搭）
        style = ttk.Style()
        with contextlib.suppress(Exception):
            style.theme_use("clam")
        style.configure("HR.Horizontal.TScale", background=BG, troughcolor=BG,
                        bordercolor=EDGE, lightcolor=ACC, darkcolor=ACC,
                        borderwidth=0)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 9))

        pad = dict(padx=16, pady=(12, 0))

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", **pad)
        self.bpm_lbl = tk.Label(top, text="---", font=("Consolas", 56, "bold"),
                                fg=DIM, bg=BG)
        self.bpm_lbl.pack(side="left")
        tk.Label(top, text="BPM", font=("Segoe UI", 12), fg=DIM, bg=BG).pack(
            side="left", anchor="s", pady=(0, 16), padx=(6, 0))

        right = tk.Frame(top, bg=BG)
        right.pack(side="right", anchor="n", pady=(12, 0))
        self.state_lbl = tk.Label(right, text="读取中…", bg=BG, fg=DIM,
                                  font=("Microsoft YaHei", 11))
        self.state_lbl.pack(anchor="e")
        self.stat_lbl = tk.Label(right, text="", bg=BG, fg=DIM,
                                 font=("Consolas", 9))
        self.stat_lbl.pack(anchor="e", pady=(5, 0))

        self.anchor_lbl = tk.Label(self.root, text="", bg=BG, fg=FG,
                                   font=("Consolas", 10), justify="left")
        self.anchor_lbl.pack(fill="x", **pad)

        # ---- 服务 ----
        srv = tk.LabelFrame(self.root, text=" 服务 ", fg=DIM, bg=BG, bd=1,
                            font=("Microsoft YaHei", 10))
        srv.pack(fill="x", padx=16, pady=(14, 0))
        r1 = tk.Frame(srv, bg=BG)
        r1.pack(fill="x", padx=10, pady=(10, 4))
        self._btn(r1, "启动心率服务", self.start_service, ACC).pack(side="left")
        self._btn(r1, "停止服务", self.stop_service).pack(side="left", padx=6)
        self._btn(r1, "连接状态", self.check).pack(side="left")
        r2 = tk.Frame(srv, bg=BG)
        r2.pack(fill="x", padx=10, pady=(4, 10))
        self._btn(r2, "★ 我现在很平静，校准基准", self.calibrate, OK).pack(side="left")
        tip = tk.Label(srv, text="校准：用最近 60 秒的平静心率作为个人基准（开播前坐下点一下）",
                       fg=DIM, bg=BG, font=("Microsoft YaHei", 8))
        tip.pack(anchor="w", padx=12, pady=(0, 8))

        # ---- 参数 ----
        par = tk.LabelFrame(self.root, text=" 参数 ", fg=DIM, bg=BG, bd=1,
                            font=("Microsoft YaHei", 10))
        par.pack(fill="x", padx=16, pady=(12, 0))
        for key, label, lo, hi, step, hint in SLIDERS:
            line = tk.Frame(par, bg=BG)
            line.pack(fill="x", padx=10, pady=(7, 0))
            tk.Label(line, text=label, width=12, anchor="w", fg=FG, bg=BG,
                     font=("Microsoft YaHei", 9)).pack(side="left")
            var = tk.DoubleVar(value=0)
            self.slider_vars[key] = var
            ttk.Scale(line, from_=lo, to=hi, variable=var, orient="horizontal",
                      style="HR.Horizontal.TScale",
                      command=lambda v, k=key: self._on_slide(k, v)
                      ).pack(side="left", fill="x", expand=True, padx=8)
            lab = tk.Label(line, text="--", width=5, fg=ACC, bg=BG,
                           font=("Consolas", 10))
            lab.pack(side="left")
            setattr(self, f"val_{key}", lab)
        brow = tk.Frame(par, bg=BG)
        brow.pack(fill="x", padx=10, pady=10)
        self._btn(brow, "保存参数", self.save_params, OK).pack(side="left")
        self._btn(brow, "重新载入", self.load_params).pack(side="left", padx=6)
        self.param_tip = tk.Label(brow, text="", fg=OK, bg=BG,
                                  font=("Microsoft YaHei", 9))
        self.param_tip.pack(side="left", padx=10)

        # ---- 打开 ----
        ext = tk.LabelFrame(self.root, text=" 打开 ", fg=DIM, bg=BG, bd=1,
                            font=("Microsoft YaHei", 10))
        ext.pack(fill="x", padx=16, pady=(12, 16))
        er = tk.Frame(ext, bg=BG)
        er.pack(fill="x", padx=10, pady=10)
        self._btn(er, "直播页", lambda: webbrowser.open(API + "/")).pack(side="left")
        self._btn(er, "控制台", lambda: webbrowser.open(API + "/console")).pack(side="left", padx=6)
        self._btn(er, "调参面板", lambda: webbrowser.open(API + "/tune")).pack(side="left")
        self._btn(er, "日志目录", self.open_logs).pack(side="left", padx=6)

    def _btn(self, parent, text, cmd, color=None) -> tk.Button:
        return tk.Button(parent, text=text, command=cmd, bg=BTN,
                         fg=color or FG, activebackground=EDGE,
                         activeforeground=color or FG, relief="flat", bd=0,
                         highlightthickness=0, padx=13, pady=7, cursor="hand2",
                         font=("Microsoft YaHei UI", 9))

    # ---------------- 行为 ----------------
    def _on_slide(self, key: str, value) -> None:
        getattr(self, f"val_{key}").config(text=f"{float(value):.0f}")

    def _flash(self, text: str) -> None:
        self.param_tip.config(text=text)
        self.root.after(3500, lambda: self.param_tip.config(text=""))

    def _service_pids(self) -> list:
        if os.name != "nt":
            return []
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                 "Where-Object { $_.CommandLine -like '*heartrate_live*' }"
                 ").ProcessId"],
                capture_output=True, text=True, timeout=15).stdout
            return [int(x) for x in out.split() if x.strip().isdigit()]
        except Exception:
            return []

    def running(self) -> bool:
        try:
            api_get("/health", timeout=1.5)
            return True
        except Exception:
            return False

    def start_service(self) -> None:
        if self.running():
            messagebox.showinfo("提示", "服务已经在运行了")
            return
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(
            [PY, str(HERE / "heartrate_live.py"), 
             "--port", "8080", "--history", "2400"],
            cwd=str(HERE), creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state_lbl.config(text="启动中…（约 5 秒）", fg=DIM)
        self.root.after(5000, self.check)

    def stop_service(self) -> None:
        if not self.running():
            messagebox.showinfo("提示", "服务本来就没在运行")
            return
        if not messagebox.askyesno("确认", "停止心率服务？\n画面会变成 ---，悬浮窗也会失去数据。"):
            return
        for pid in self._service_pids():
            subprocess.run(["taskkill", "/f", "/pid", str(pid)],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self._flash("服务已停止")
        self.root.after(1500, self.check)

    def check(self) -> None:
        if self.running():
            try:
                r = api_get("/hr")
                msg = f"服务在运行\n当前 {r.get('bpm')} bpm，连接 {'正常' if r.get('connected') else '断开'}"
            except Exception:
                msg = "服务在运行"
            self.state_lbl.config(text="已连接", fg=OK)
        else:
            msg = "服务没在运行 —— 点「启动心率服务」"
            self.state_lbl.config(text="服务未运行", fg=ACC)
        messagebox.showinfo("连接状态", msg)

    def calibrate(self) -> None:
        try:
            r = api_post("/calibrate", {})
            self._flash(f"基准已锁定 B={r.get('base')}")
        except Exception as e:
            messagebox.showerror("校准失败", f"服务没在运行？\n\n{e}")

    def load_params(self) -> None:
        try:
            p = api_get("/params")
            self.params = p or {}
            for key, var in self.slider_vars.items():
                if key in self.params:
                    var.set(float(self.params[key]))
                    getattr(self, f"val_{key}").config(text=f"{float(self.params[key]):.0f}")
            self._flash("已载入服务端参数")
        except Exception:
            self._flash("读取参数失败（服务未运行？）")

    def save_params(self) -> None:
        payload = {k: float(v.get()) for k, v in self.slider_vars.items()}
        try:
            saved = api_post("/params", payload)
            self.params = saved or payload
            self._flash("已保存 ✓ 刷新网页后生效")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def open_logs(self) -> None:
        try:
            os.startfile(HERE / "logs")          # noqa: S606
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    # ---------------- 定时刷新 ----------------
    def tick(self) -> None:
        try:
            r = api_get("/hr", timeout=2)
            bpm, age = r.get("bpm"), r.get("age")
            offline = (not r.get("connected")) or (age is not None and age > 5)
            self.bpm_lbl.config(text=str(bpm) if bpm is not None else "---",
                                fg=DIM if bpm is None else (ACC if offline else OK))
            self.state_lbl.config(text="离线（手环没在广播？）" if offline else "已连接",
                                  fg=ACC if offline else OK)
            s, rc = r.get("stats") or {}, r.get("recent") or {}
            self.stat_lbl.config(
                text=f"本场 {s.get('min','-')}/{s.get('avg','-')}/{s.get('max','-')}"
                     f"    10分P90 {rc.get('p90','-')}")

            base = r.get("base")
            if base is None and s.get("min") is not None and s.get("avg") is not None:
                base = max(45, s["min"] + (s["avg"] - s["min"]) * 0.25)
            if base is not None:
                p = self.params or {}
                rv = min(base + p.get("maxGap", 30),
                         max(base + p.get("minGap", 22),
                             (rc.get("p90") or base) - p.get("p90Offset", 3)))
                self.anchor_lbl.config(
                    text=f"基准 B {base:.0f}    黄 {base + (rv - base) * 0.4:.0f}"
                         f"    橙 {base + (rv - base) * 0.7:.0f}    满红 R {rv:.0f}"
                         f"    {'（已锁定）' if r.get('base') is not None else '（临时估计）'}")
        except Exception:
            self.bpm_lbl.config(text="---", fg=DIM)
            self.state_lbl.config(text="服务未运行", fg=ACC)
            self.stat_lbl.config(text="")
            self.anchor_lbl.config(text="点「启动心率服务」开始")
        self.root.after(1000, self.tick)


def main() -> None:
    root = tk.Tk()
    app = Console(root)
    app.load_params()
    root.mainloop()


if __name__ == "__main__":
    main()
