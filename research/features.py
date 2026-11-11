"""Q2 of PREREG_V2.md: the grading factors for every setup, computed as the app would see them on the signal day."""
import sys, os, pickle
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import numpy as np, pandas as pd
from multiprocessing import Pool
from levels import find_levels

OUT = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(OUT, "data.pkl"), "rb"))
S = pd.read_pickle(os.path.join(OUT, "setups.pkl"))


def work(sym):
    df = D["assets"][sym]["df"]; c = df["close"].astype(float); s20 = c.rolling(20, min_periods=20).mean().values
    rows = []
    for t in S[S.symbol == sym].itertuples():
        i, atr = t.i, t.atr; price = float(c.iloc[i]); bull = t.direction == "bullish"; sgn = 1 if bull else -1
        lv = find_levels(df.iloc[i - 259:i + 1], atr)
        sups = sorted([l for l in lv if l["price"] < price - 0.1 * atr], key=lambda l: -l["price"])
        ress = sorted([l for l in lv if l["price"] > price + 0.1 * atr], key=lambda l: l["price"])
        near, ahead = (sups, ress) if bull else (ress, sups)
        anchor = next((l for l in near if abs(price - l["price"]) <= 3 * atr), None)
        mid = (t.lo + t.hi) / 2
        tgt = next((l for l in ahead if (l["price"] - mid) * sgn > 0.25 * atr), None)
        rr = abs(tgt["price"] - mid) / abs(mid - t.brk) if tgt else np.nan
        in_zone = t.lo <= price <= t.hi
        dist = 0.0 if in_zone else min(abs(price - t.lo), abs(price - t.hi)) / atr
        rows.append((t.Index, anchor["touches"] if anchor else 0, rr, dist, sgn * (price - s20[i]) / atr))
    return rows


if __name__ == "__main__":
    with Pool(2) as p:
        res = p.map(work, list(D["assets"]), chunksize=1)
    F = pd.DataFrame([r for rs in res for r in rs], columns=["idx", "touches", "rr", "dist", "stretch"]).set_index("idx").sort_index()
    F.to_pickle(os.path.join(OUT, "features.pkl")); print("features", len(F))
