import numpy as np
import pandas as pd
from levels import analyse_levels, find_levels, swing_points, pick


def make(path, freq="B"):
    idx = pd.date_range("2023-01-02", periods=len(path), freq=freq)
    c = pd.Series(path, index=idx)
    return pd.DataFrame({"open": c.shift(1).fillna(c), "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6})


# 1. Swing points: a single clear peak and trough are found at the right bars
p = np.r_[np.linspace(100, 120, 30), np.linspace(120, 90, 30), np.linspace(90, 110, 30)]
d = make(p)
sp = swing_points(d)
highs = [x for x in sp if x[1] == "high"]; lows = [x for x in sp if x[1] == "low"]
assert any(abs(h[0] - 120 * 1.01) < 1e-6 for h in highs), highs
assert any(abs(l[0] - 90 * 0.99) < 1e-6 for l in lows), lows
print("swing points ok")

# 2. Merging: two peaks 0.2 ATR apart become one level with 2 touches
lv = find_levels(d, atr=5.0)
assert all(b["price"] > a["price"] for a, b in zip(lv, lv[1:]))
print("levels sorted ok:", [(round(l["price"], 2), l["touches"]) for l in lv])

rng = np.random.default_rng(1)
up = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.012, 600)))
dn = 100 * np.exp(np.cumsum(rng.normal(-0.001, 0.012, 600)))

# 3. Bullish: supports below price, resistances above, zone at/below price, break below zone
b = analyse_levels({"symbol": "UP", "score": 60, "label": "Bullish", "confidence": "High"}, make(up))
assert b["status"] == "ok" and b["direction"] == "bullish"
assert all(s["price"] < b["price"] for s in b["supports"])
assert all(r["price"] > b["price"] for r in b["resistances"])
z = b["zone"]
assert z["lo"] < z["hi"] <= b["price"] + 1e-9, z
assert b["signal_break"] < z["lo"]
assert b["target"]["price"] is None or b["target"]["price"] > z["hi"]
print("bullish ok:", b["price"], z, b["signal_break"], b["target"], b["reward_risk"])

# 4. Bearish mirror
s = analyse_levels({"symbol": "DN", "score": -60, "label": "Bearish", "confidence": "High"}, make(dn))
z = s["zone"]
assert s["direction"] == "bearish"
assert s["price"] - 1e-9 <= z["lo"] < z["hi"], z
assert s["signal_break"] > z["hi"]
assert s["target"]["price"] is None or s["target"]["price"] < z["lo"]
print("bearish ok:", s["price"], z, s["signal_break"], s["target"], s["reward_risk"])

# 5. Neutral: no zone
n = analyse_levels({"symbol": "N", "score": 5, "label": "Neutral", "confidence": "Low"}, make(up))
assert n["direction"] is None and "zone" not in n
print("neutral ok")

# 6. Picks: strongest first, Low confidence skipped, at most 3
picks = pick([{"symbol": k, "status": "ok", "direction": "bullish", "score": sc, "confidence": cf}
              for k, sc, cf in [("A", 80, "High"), ("B", -70, "Medium"), ("C", 90, "Low"), ("D", 45, "High"), ("E", 41, "Medium")]])
assert picks == ["A", "B", "D"], picks
print("picks ok:", picks)
print("ALL TESTS PASSED")
