"""Build every daily setup (|score| >= 40 with a zone), the way levels.analyse_levels does, but fast.
Validated against levels.analyse_levels on a random sample."""
import sys, os, pickle, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import numpy as np, pandas as pd
from engine import atr_wilder
from levels import find_levels, analyse_levels

OUT = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(OUT, "data.pkl"), "rb"))
START = pd.Timestamp("2009-06-01")


def zone(levels, price, atr, score):
    bull = score >= 15
    sups = sorted([l for l in levels if l["price"] < price - 0.1 * atr], key=lambda l: -l["price"])
    ress = sorted([l for l in levels if l["price"] > price + 0.1 * atr], key=lambda l: l["price"])
    near = sups if bull else ress
    anchor = next((l for l in near if abs(price - l["price"]) <= 3 * atr), None)
    if anchor:
        a = anchor["price"]
        lo, hi = (a - 0.25 * atr, min(a + 0.5 * atr, price)) if bull else (max(a - 0.5 * atr, price), a + 0.25 * atr)
    else:
        lo, hi = (price - 1.5 * atr, price - 0.75 * atr) if bull else (price + 0.75 * atr, price + 1.5 * atr)
    brk = lo - 0.75 * atr if bull else hi + 0.75 * atr
    return {"direction": "bullish" if bull else "bearish", "lo": lo, "hi": hi, "brk": brk}


rows = []
checks = []
for sym, a in D["assets"].items():
    df = a["df"]; c = df["close"].astype(float)
    atr = atr_wilder(df["high"].astype(float), df["low"].astype(float), c).values
    sc = a["score"].values
    for i in range(len(df)):
        d = df.index[i]
        if d < START or i < 260 or np.isnan(sc[i]) or abs(sc[i]) < 40 or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        lv = find_levels(df.iloc[i - 259:i + 1], atr[i])
        z = zone(lv, float(c.iloc[i]), atr[i], sc[i])
        rows.append({"symbol": sym, "i": i, "date": d, "score": float(sc[i]), "atr": float(atr[i]), **z})
        if random.random() < 0.004:
            checks.append((sym, i, z))
    print(sym, sum(r["symbol"] == sym for r in rows), flush=True)

# validation against the app's own analyse_levels (2-year window, as levels.py fetches)
diffs = []
for sym, i, z in checks:
    a = D["assets"][sym]; df = a["df"]
    win = 730 if a["cls"] == "crypto" else 504
    ref = analyse_levels({"symbol": sym, "score": float(a["score"].iloc[i])}, df.iloc[max(0, i + 1 - win):i + 1])
    rz = ref.get("zone")
    if not rz:
        diffs.append(("nozone", sym)); continue
    atr = ref["atr"]
    diffs.append(max(abs(rz["lo"] - z["lo"]), abs(rz["hi"] - z["hi"]), abs(ref["signal_break"] - z["brk"])) / atr)
num = [x for x in diffs if not isinstance(x, tuple)]
print(f"validation: {len(diffs)} samples, max diff {max(num):.4f} ATR, median {np.median(num):.5f} ATR, >0.05 ATR: {sum(x > 0.05 for x in num)}, no-zone mismatches: {len(diffs) - len(num)}")
pd.DataFrame(rows).to_pickle(os.path.join(OUT, "setups.pkl"))
print("setups", len(rows))
