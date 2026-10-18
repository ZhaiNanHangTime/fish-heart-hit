"""Shared defaults and validation. Flat keys preserve OBS query URLs."""
import math

DEFAULT_PARAMS = {
    "skin": "fish", "minGap": 22, "maxGap": 30, "p90Offset": 3,
    "anchorTau": 15, "yellowAt": 0.4, "orangeAt": 0.7,
    "attack": 2, "release": 6, "redHold": 2, "redDrop": 5,
    "offlineAfter": 5, "burstRise": 8, "burstAbove": 10,
    "burstWindow": 30, "burstCooldown": 30,
    "fishScale": 1.0, "fishWidth": 1.5, "fxWarmth": True, "fxKick": True,
    "warn": 90, "danger": 100, "viewWidth":520,"viewHeight":170,
    "traceLayout": "overlay",
    "traceSeconds": 180,
    "hudWidth": 240, "hudHeight": 104,
}
GROUPS = {
    "color": ["minGap", "maxGap", "p90Offset", "anchorTau", "yellowAt", "orangeAt",
              "attack", "release", "redHold", "redDrop"],
    "effect": ["burstRise", "burstAbove", "burstWindow", "burstCooldown",
               "fishScale", "fishWidth", "fxWarmth", "fxKick"],
    "device": ["viewWidth","viewHeight","hudWidth","hudHeight","skin", "traceLayout", "traceSeconds", "offlineAfter", "warn", "danger"],
}
LIMITS = {
    "minGap": (1, 80), "maxGap": (1, 100), "p90Offset": (0, 30),
    "anchorTau": (0.1, 300), "yellowAt": (0.01, 0.98), "orangeAt": (0.02, 0.99),
    "attack": (0.05, 60), "release": (0.05, 120), "redHold": (0, 60),
    "redDrop": (0, 40), "offlineAfter": (1, 60), "burstRise": (1, 60),
    "burstAbove": (0, 80), "burstWindow": (1, 300), "burstCooldown": (0, 600),
    "viewWidth":(300,1200), "viewHeight":(90,450), "fishScale": (0.5, 4.0), "warn": (30, 249), "danger": (31, 250),
    "hudWidth": (160, 1920), "hudHeight": (64, 1080),
    "fishWidth": (0.5, 1.5),
    "traceSeconds": (30, 600),
}

def merge_params(base, values):
    if not isinstance(values, dict):
        raise ValueError("参数必须为 JSON 对象")
    out = dict(base)
    for key, value in values.items():
        if key not in DEFAULT_PARAMS:
            continue
        if key == "skin":
            if value not in ("fish", "ghost", "xianyu"):
                raise ValueError("未知皮肤")
        elif key == "traceLayout":
            if value not in ("overlay", "lower"):
                raise ValueError("心率线布局须为 overlay 或 lower")
        elif key in ("fxWarmth", "fxKick"):
            if not isinstance(value, bool):
                raise ValueError(f"{key} 必须为布尔值")
        else:
            if isinstance(value, bool):
                raise ValueError(f"{key} 必须为数字")
            value = float(value)
            lo, hi = LIMITS[key]
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{key} 超出范围 {lo}..{hi}")
            if key in ("hudWidth", "hudHeight"):
                if not value.is_integer():
                    raise ValueError(f"{key} 必须为整数像素")
                value = int(value)
        out[key] = value
    if out["minGap"] > out["maxGap"] or out["yellowAt"] >= out["orangeAt"] or out["warn"] >= out["danger"]:
        raise ValueError("须满足 minGap≤maxGap、yellowAt<orangeAt、warn<danger")
    return out
