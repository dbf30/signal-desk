"""Simulate every setup under each trade-rule variant. First verify sim.simulate == trades.simulate_trade."""
import sys, os, pickle, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import numpy as np, pandas as pd
from trades import simulate_trade
from scorecard import COST
from sim import simulate

OUT = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(OUT, "data.pkl"), "rb"))
S = pd.read_pickle(os.path.join(OUT, "setups.pkl"))
arr = {}
for sym, a in D["assets"].items():
    df = a["df"]
    arr[sym] = (df["open"].values.astype(float), df["high"].values.astype(float), df["low"].values.astype(float),
                df["close"].values.astype(float), a["score"].values.astype(float), df.index)

# 1. verification against the app's trades.py
bad = 0; samp = S.sample(4000, random_state=1)
for _, s in samp.iterrows():
    o, h, l, c, sc, idx = arr[s.symbol]; i = s.i; j = i + 1; k = j + 71
    bull = s.direction == "bullish"; cls = D["assets"][s.symbol]["cls"]
    ref = simulate_trade({"direction": s.direction, "zone": {"lo": s.lo, "hi": s.hi}, "signal_break": s.brk},
                         D["assets"][s.symbol]["df"].iloc[j:k], list(sc[j:k]), COST[cls])
    me = simulate(bull, s.lo, s.hi, s.brk, s.atr, o[j:k], h[j:k], l[j:k], c[j:k], list(sc[j:k]), idx[j:k], COST[cls])
    same = ref["status"] == me["status"] and (ref["r"] is None and me["r"] is None or abs((ref["r"] or 0) - (me["r"] or 0)) < 1e-6)
    if not same:
        bad += 1
        if bad < 5: print("MISMATCH", s.symbol, s.date, ref["status"], ref["r"], me["status"], me["r"])
print(f"verification: {len(samp) - bad}/{len(samp)} identical to trades.simulate_trade")

VARIANTS = {
    "base": {},
    "fastshort": {"short": {"exit_level": 40.0, "max_hold": 20}},
    "widestop": {"widestop": True},
    "confirm": {"entry": "confirm"},
    "partial": {"partial": True},
}
for name, v in VARIANTS.items():
    rows = []
    for s in S.itertuples(index=False):
        o, h, l, c, sc, idx = arr[s.symbol]; j = s.i + 1; k = j + 71
        bull = s.direction == "bullish"; cls = D["assets"][s.symbol]["cls"]
        stop = s.brk
        if v.get("widestop"):
            stop = s.lo - 1.5 * s.atr if bull else s.hi + 1.5 * s.atr
        kw = {}
        if not bull and "short" in v: kw.update(v["short"])
        if "entry" in v: kw["entry"] = v["entry"]
        if v.get("partial"): kw["partial"] = True
        r = simulate(bull, s.lo, s.hi, stop, s.atr, o[j:k], h[j:k], l[j:k], c[j:k], list(sc[j:k]), idx[j:k], COST[cls], **kw)
        if r["fill_i"] is None:
            rows.append((r["status"], None, None, None, None, None)); continue
        fi = idx[j + r["fill_i"]]
        ei = idx[j + r["exit_i"]] if r["exit_i"] is not None else None
        path = (np.array([j + p for p, _ in r["path"]], dtype=np.int32), np.array([m for _, m in r["path"]], dtype=np.float32))
        rows.append((r["status"], fi, ei, r["entry"], r["r"], path))
    df_ = pd.DataFrame(rows, columns=["status", "fill_date", "exit_date", "entry", "r", "path"])
    df_.to_pickle(os.path.join(OUT, f"sim_{name}.pkl"))
    print(name, df_.status.value_counts().to_dict(), flush=True)
    del rows, df_
