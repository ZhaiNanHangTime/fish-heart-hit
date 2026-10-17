"""参数扫描：拿真实记录跑多组参数，量化「节目效果 vs 真实性」的权衡。

用法:
    python tune_scan.py logs/heart-rate-XXX.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import replay_check as rc


def load(path: Path) -> list:
    rows = []
    with path.open(encoding="utf-8-sig") as fh:
        for rec in csv.DictReader(fh):
            try:
                rows.append((float(rec["timestamp"]), int(rec["bpm"])))
            except Exception:  # noqa: BLE001
                continue
    rows.sort()
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python tune_scan.py <csv>")
        return 1
    path = Path(sys.argv[1])
    rows = load(path)
    if len(rows) < 50:
        print("样本太少")
        return 1
    dur = (rows[-1][0] - rows[0][0]) / 60.0
    scale = 10.0 / max(0.1, dur)
    vals = [v for _t, v in rows]

    print(f"记录: {path.name}   {len(rows)} 样本 / {dur:.0f} 分钟")
    print(f"心率: min {min(vals)}  avg {sum(vals)//len(vals)}  max {max(vals)}")
    print()
    print(f"{'min_gap':>8}{'burst_rise':>12}{'满红/10min':>12}{'假红':>7}"
          f"{'特效/10min':>12}")
    print("-" * 54)

    for min_gap in (14, 18, 20, 22, 26, 30):
        for burst_rise in (6, 8, 10):
            rc.P["min_gap"] = float(min_gap)
            rc.P["burst_rise"] = float(burst_rise)
            res = rc.replay(rows)
            print(f"{min_gap:>8}{burst_rise:>12}"
                  f"{res['red']*scale:>12.1f}{res['false_red']:>7}"
                  f"{res['burst']*scale:>12.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
