"""用真实心率记录回放「冻结版算法」，输出三个验收指标。

指标：
  1. 节目效果 —— 每 10 分钟触发多少次满红 / 突发特效
  2. 真实性   —— 平静期出现了多少次不该有的满红
  3. 稳定性   —— 锚点是否平滑、有无异常跳变

用法:
    python replay_check.py logs/heart-rate-YYYYmmdd-HHMMSS.csv
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

# ---- 与网页 / 悬浮窗一致的那套参数 ----
P = dict(
    base_fallback=70.0, base_samples=40,
    min_gap=22.0,        # R >= B + 22
    max_gap=30.0,        # R <= B + 30（原来 45，实测会让 R 顶到 114 而本人峰值才 104）
    p90_offset=3.0,
    anchor_tau=15.0,
    attack=2.0, release=6.0,
    red_hold=2.0, red_drop=5.0,
    burst_rise=10, burst_above=15, burst_window=30.0, burst_cooldown=30.0,
)
WINDOW = 600.0           # 最近 10 分钟


def base_heart(hist: list) -> float:
    if len(hist) < P["base_samples"]:
        return P["base_fallback"]
    vals = [v for _t, v in hist]
    lo, avg = min(vals), sum(vals) / len(vals)
    return max(45.0, lo + (avg - lo) * 0.25)


def p90_at(hist: list, now: float):
    vals = sorted(v for t, v in hist if now - t <= WINDOW)
    if not vals:
        return None
    n = len(vals)
    return vals[min(n - 1, int(n * 0.9))]


def replay(rows: list) -> dict:
    hist: list = []
    track: list = []
    anchors = None
    p_smooth = 0.0
    red_since = None
    fully_red = False
    last_burst = -999.0
    last_t = None
    red_events = false_red = burst_events = 0
    prev_red = False
    r_trace: list = []
    over_points = 0          # 有多少个采样点站在阈值之上
    longest_over = 0.0       # 最长连续超阈值时长（秒）
    over_since = None
    seg_max = 0.0
    base_locked = None
    t_first = rows[0][0] if rows else 0.0

    for t, bpm in rows:
        dt = 0.0 if last_t is None else max(0.0, min(2.0, t - last_t))
        last_t = t
        hist.append((t, bpm))

        # 基准：头 3 分钟用累计估计，之后锁定不再漂移（与服务端行为一致）
        if base_locked is None and (t - t_first) >= 180 and len(hist) >= 30:
            _v = sorted(v for _tt, v in hist)
            base_locked = _v[max(0, int(len(_v) * 0.10))]

        # 1) 锚点（R 缓慢跟随）
        B = float(base_locked) if base_locked is not None else base_heart(hist)
        p90 = p90_at(hist, t)
        if p90 is None:
            p90 = B + P["min_gap"]
        r_target = min(B + P["max_gap"], max(B + P["min_gap"], p90 - P["p90_offset"]))
        if anchors is None:
            anchors = {"B": B, "R": r_target}
        else:
            anchors["B"] = B
            if dt > 0:
                anchors["R"] += (r_target - anchors["R"]) * (1 - math.exp(-dt / P["anchor_tau"]))
        R = anchors["R"]
        r_trace.append(R)

        # 2) 强度（Attack / Release）
        p_target = max(0.0, min(1.0, (bpm - anchors["B"]) / max(1.0, R - anchors["B"])))
        tau = P["attack"] if p_target > p_smooth else P["release"]
        if dt > 0:
            p_smooth += (p_target - p_smooth) * (1 - math.exp(-dt / tau))

        # 3) 满红迟滞
        if bpm >= R:
            over_points += 1
            if over_since is None:
                over_since = t
            seg_max = max(seg_max, t - over_since)
            if red_since is None:
                red_since = t
            if t - red_since >= P["red_hold"]:
                fully_red = True
        elif bpm < R - P["red_drop"]:
            if over_since is not None:
                longest_over = max(longest_over, seg_max)
                over_since = None
                seg_max = 0.0
            red_since = None
            fully_red = False

        if fully_red and not prev_red:
            red_events += 1
            if bpm < anchors["B"] + 20:      # 离基线不到 20 就算平静期
                false_red += 1
        prev_red = fully_red

        # 4) 突发特效（独立通道 + 冷却）
        track.append((t, bpm))
        while track and t - track[0][0] > P["burst_window"]:
            track.pop(0)
        if (bpm - track[0][1]) >= P["burst_rise"] and bpm >= anchors["B"] + P["burst_above"] \
                and (t - last_burst) >= P["burst_cooldown"]:
            burst_events += 1
            last_burst = t

    if over_since is not None:
        longest_over = max(longest_over, seg_max)
    return dict(red=red_events, false_red=false_red, burst=burst_events,
                anchors=anchors, r_trace=r_trace,
                over_points=over_points, longest_over=longest_over)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python replay_check.py <csv>")
        return 1
    path = Path(sys.argv[1])
    rows = []
    with path.open(encoding="utf-8-sig") as fh:
        for rec in csv.DictReader(fh):
            try:
                rows.append((float(rec["timestamp"]), int(rec["bpm"])))
            except Exception:  # noqa: BLE001
                continue
    if len(rows) < 10:
        print("样本太少")
        return 1
    rows.sort()
    dur_min = (rows[-1][0] - rows[0][0]) / 60.0
    vals = [v for _t, v in rows]
    res = replay(rows)
    scale = 10.0 / max(0.1, dur_min)

    print(f"文件      : {path.name}")
    print(f"样本/时长 : {len(rows)} 个 / {dur_min:.1f} 分钟")
    print(f"心率分布  : min {min(vals)}  avg {sum(vals)//len(vals)}  max {max(vals)}  "
          f"p90 {sorted(vals)[int(len(vals)*0.9)]}")
    print(f"最终锚点  : B={res['anchors']['B']:.0f}   R={res['anchors']['R']:.0f}"
          f"   (黄 {(res['anchors']['B'] + (res['anchors']['R']-res['anchors']['B'])*0.4):.0f}"
          f" / 橙 {(res['anchors']['B'] + (res['anchors']['R']-res['anchors']['B'])*0.7):.0f})")
    print("-" * 52)
    print(f"[节目效果] 满红 {res['red']} 次   突发特效 {res['burst']} 次"
          f"   -> 每10分钟 {res['red']*scale:.1f} / {res['burst']*scale:.1f} 次")
    print(f"[真实性]   平静期假红 {res['false_red']} 次")
    over_pct = res["over_points"] / max(1, len(rows)) * 100
    print(f"[阈值诊断] 站在满红阈值之上 {res['over_points']} 个采样点（{over_pct:.1f}%），"
          f"最长连续 {res['longest_over']:.1f} 秒"
          f"（满红需要连续 ≥{P['red_hold']:.0f} 秒）")
    r = res["r_trace"]
    if r:
        jumps = [abs(r[i] - r[i-1]) for i in range(1, len(r))]
        print(f"[稳定性]   阈值波动 最大跳变 {max(jumps):.2f} bpm，"
              f"均值 {sum(jumps)/len(jumps):.3f} bpm；R 范围 {min(r):.0f}~{max(r):.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
