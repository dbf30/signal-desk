import numpy as np
import pandas as pd
from engine import rsi_wilder, sma, analyse, signal_frame, backtest, alerts

# 1. RSI vs the published StockCharts worked example (Wilder RSI-14)
closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
          46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18,
          44.22, 44.57, 43.42, 42.66, 43.13]
expected = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
            41.87, 45.46, 37.30, 33.08, 37.77]
r = rsi_wilder(pd.Series(closes), 14).dropna().round(2).tolist()
diff = max(abs(a - b) for a, b in zip(r, expected))
print("RSI max diff vs StockCharts:", diff)
assert diff < 0.1, (r, expected)

# 2. SMA vs naive loop
s = pd.Series(np.random.default_rng(0).normal(size=300).cumsum() + 100)
naive = [np.mean(s[i - 49:i + 1]) if i >= 49 else np.nan for i in range(len(s))]
assert np.allclose(sma(s, 50).values[49:], naive[49:])
print("SMA ok")


def make(path, start="2020-01-01", freq="B", vol=True):
    idx = pd.date_range(start, periods=len(path), freq=freq)
    c = pd.Series(path, index=idx)
    return pd.DataFrame({"open": c.shift(1).fillna(c), "high": c * 1.01, "low": c * 0.99, "close": c,
                         "volume": 1e6 if vol else np.nan})


rng = np.random.default_rng(42)
n = 1200
up = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.01, n)))
down = 100 * np.exp(np.cumsum(rng.normal(-0.0008, 0.01, n)))

for cls in ("stock", "fx", "commodity"):
    a = analyse("UP", "up", cls, make(up))
    b = analyse("DN", "down", cls, make(down))
    print(cls, "uptrend:", a["score"], a["label"], "| downtrend:", b["score"], b["label"])
    assert a["score"] > 15 and b["score"] < -15

cu = analyse("UPC", "up", "crypto", make(up, freq="D"))
cd = analyse("DNC", "down", "crypto", make(down, freq="D"))
print("crypto uptrend:", cu["score"], cu["label"], "| downtrend:", cd["score"], cd["label"])

# 3. No look-ahead: on pure random walks the backtest hit rate must sit near 50%
hits = []
for seed in range(40):
    g = np.random.default_rng(seed)
    rw = 100 * np.exp(np.cumsum(g.normal(0, 0.01, 2500)))
    df = make(rw)
    sig = signal_frame(df, "stock")
    bt = backtest(sig, df["close"], 20)
    if bt.get("overall_hit") is not None:
        hits.append(bt["overall_hit"])
print(f"random-walk mean hit rate over {len(hits)} runs: {np.mean(hits):.3f} (should be ~0.50)")
assert abs(np.mean(hits) - 0.5) < 0.03

# 4. Missing volume handled; alert logic
a = analyse("NOVOL", "x", "crypto", make(up, freq="D", vol=False))
assert a["status"] == "ok"
prev = {"X": {"status": "ok", "label": "Neutral", "score": 5}}
print(alerts(prev, [{"symbol": "X", "status": "ok", "label": "Bullish", "score": 45}]))
print(alerts(prev, [{"symbol": "X", "status": "ok", "label": "Leaning bullish", "score": 20}]))

# 5. Crypto context blend: score = (0.7*chart + 15*regime + 0.15*btc) / available weight
df = make(up, freq="D")
plain = signal_frame(df, "crypto")
reg = pd.Series(1.0, index=df.index); btc = pd.Series(-50.0, index=df.index)
ctx = signal_frame(df, "crypto", {"risk_regime": reg, "btc_factor": btc})
i = plain["score"].last_valid_index()
exp = 0.7 * plain.loc[i, "score"] + 15 * 1.0 + 0.15 * -50.0
assert abs(ctx.loc[i, "score"] - exp) < 1e-9, (ctx.loc[i, "score"], exp)
only = signal_frame(df, "crypto", {"risk_regime": reg, "btc_factor": None})
exp2 = (0.7 * plain.loc[i, "score"] + 15 * 1.0) / 0.85
assert abs(only.loc[i, "score"] - exp2) < 1e-9
# context on a sparser calendar (stocks trade weekdays) is forward-filled onto crypto days
wk = reg[reg.index.dayofweek < 5].copy(); wk.iloc[:] = -1.0
ff = signal_frame(df, "crypto", {"risk_regime": wk})
assert ff["risk_regime"].dropna().eq(-1.0).all()
# stocks ignore context entirely
assert np.allclose(signal_frame(df, "stock", {"risk_regime": reg})["score"].fillna(-999), signal_frame(df, "stock")["score"].fillna(-999))
a = analyse("C", "c", "crypto", df, {"risk_regime": reg, "btc_factor": btc})
assert abs(sum(r["contribution"] for r in a["reasons"]) - a["score"]) < 1.0, a["reasons"]
print("context blend ok")
print("ALL TESTS PASSED")
