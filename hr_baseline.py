"""Baseline policy only; independent of the frozen color/effect equations."""
import math
from collections import deque

def percentile(values, q):
    vals = sorted(values)
    return vals[min(len(vals) - 1, int(len(vals) * q))] if vals else None

class Baseline:
    def __init__(self):
        self.rows = deque()
        self.value = None
        self.last_t = None
        self.mode = "warming"

    def add(self, now, bpm):
        previous = self.last_t
        self.last_t = now
        self.rows.append((now, bpm))
        while self.rows and self.rows[0][0] < now - 600:
            self.rows.popleft()
        if len(self.rows) < 30 or now - self.rows[0][0] < 60:
            return
        target = percentile([v for _, v in self.rows], .25)
        if self.value is None:
            self.value = float(target)
        elif previous is not None and 0 < now - previous <= 5:
            self.value += (target - self.value) * (1 - math.exp(-(now - previous) / 60))
        self.mode = "auto"

    def calibrate(self, now):
        rows = [(t, v) for t, v in self.rows if now - t <= 65]
        p25 = percentile([v for t, v in self.rows if now - t <= 600], .25)
        if (len(rows) < 30 or rows[-1][0] - rows[0][0] < 60 or now - rows[-1][0] > 5
                or any(b[0] - a[0] > 5 for a, b in zip(rows, rows[1:]))):
            return False, "需要连续至少60秒有效心率，数据间隔不得超过5秒"
        if any(abs(v - p25) > 3 for _, v in rows):
            return False, "最近60秒须始终在十分钟P25的±3 bpm内，请平静后重试"
        self.value = float(percentile([v for _, v in rows], .25))
        self.mode = "calibrated-following"
        return True, "校准成功；基准仍会慢跟随，避免永久锁高"

    def status(self, now):
        vals = [v for t, v in self.rows if now - t <= 600]
        p25 = percentile(vals, .25)
        delta = self.value - p25 if self.value is not None and p25 is not None else None
        warning = ""
        if delta is not None and abs(delta) > 8:
            warning = "基准偏高" if delta > 0 else "基准偏低"
        return {"mode": self.mode, "p25": p25,
                "delta": round(delta, 1) if delta is not None else None,
                "warning": warning, "note": "P25是会话参考，持续活动时不能推断真实静息值"}
