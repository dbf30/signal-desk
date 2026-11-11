"""Q3 of PREREG_V2.md: the live intraday rule (S0) and the pre-registered variants, on hourly crypto bars.
Needs data.pkl (data.py) and hourly.pkl (fetch_hourly.py). Trades use engine/intraday.intraday_trade."""
import sys, os, pickle, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import numpy as np, pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from engine import atr_wilder
from intraday import intraday_trade, COST

OUT = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(OUT, "data.pkl"), "rb"))
H = pickle.load(open(os.path.join(OUT, "hourly.pkl"), "rb"))
UK = ZoneInfo("Europe/London")
WATCH = ["BTC", "ETH", "SOL", "XRP"]
C = COST["crypto"]


def sessions(sym):
    a = D["assets"][sym]; df = a["df"]; score = a["score"]
    atr = atr_wilder(df["high"].astype(float), df["low"].astype(float), df["close"].astype(float))
    h = H[sym]; rows = []
    day = h.index[0].tz_convert(UK).date() + timedelta(days=1)
    end = h.index[-1].tz_convert(UK).date()
    while day < end:
        s = pd.Timestamp(datetime(day.year, day.month, day.day, 8, tzinfo=UK)).tz_convert("UTC")
        e = pd.Timestamp(datetime(day.year, day.month, day.day, 20, tzinfo=UK)).tz_convert("UTC")
        b = h[(h.index >= s) & (h.index < e)]
        prev = pd.Timestamp(day) - pd.Timedelta(days=1)          # last completed daily bar
        if len(b) >= 10 and prev in score.index and pd.notna(score.loc[prev]) and b.index[0] == s:
            sc = float(score.loc[prev]); px = float(df["close"].loc[prev]); at = float(atr.loc[prev])
            rows.append((sym, day, sc, at / px, b))
        day += timedelta(days=1)
    return rows


def trade(b, bull, floor_frac=None):
    o, h, l, c = (b[k].values.astype(float) for k in ("open", "high", "low", "close"))
    if floor_frac is None:
        return intraday_trade(o, h, l, c, bull, "orb", 0.0, None, None, C, True)
    # stop floor: same entry, stop at least floor_frac * price away
    E = h[0] if bull else l[0]; rng = h[0] - l[0]
    dist = max(rng, floor_frac * E); S = E - dist if bull else E + dist
    fi = None
    for i in range(1, len(o)):
        if bull and o[i] >= E: fi, entry = i, o[i]; break
        if not bull and o[i] <= E: fi, entry = i, o[i]; break
        if bull and h[i] >= E: fi, entry = i, E; break
        if not bull and l[i] <= E: fi, entry = i, E; break
    if fi is None: return {"status": "no fill", "r": None, "entry": E, "stop": S}
    risk = (entry - S) if bull else (S - entry)
    if risk <= 0: return {"status": "stopped", "r": -1.0, "entry": entry, "stop": S}
    cr = C * entry / risk
    R = lambda px: round(((px - entry) if bull else (entry - px)) / risk - cr, 3)
    if (bull and l[fi] <= S) or (not bull and h[fi] >= S): return {"status": "stopped", "r": R(S), "entry": entry, "stop": S}
    for i in range(fi + 1, len(o)):
        if bull and o[i] <= S: return {"status": "stopped", "r": R(o[i]), "entry": entry, "stop": S}
        if bull and l[i] <= S: return {"status": "stopped", "r": R(S), "entry": entry, "stop": S}
        if not bull and o[i] >= S: return {"status": "stopped", "r": R(o[i]), "entry": entry, "stop": S}
        if not bull and h[i] >= S: return {"status": "stopped", "r": R(S), "entry": entry, "stop": S}
    return {"status": "closed at session end", "r": R(c[-1]), "entry": entry, "stop": S}


recs = []
for sym in H:
    for sym_, day, sc, atrp, b in sessions(sym):
        if abs(sc) < 15: continue
        bull = sc >= 15
        rng = float(b["high"].iloc[0] - b["low"].iloc[0]); px = float(b["high"].iloc[0] if bull else b["low"].iloc[0])
        t0 = trade(b, bull)
        rec = {"symbol": sym, "day": pd.Timestamp(day), "score": sc, "bull": bull, "rng_pct": rng / px, "atr_pct": atrp,
               "cost_frac": (C * px / rng) if rng > 0 else np.inf, "r0": t0["r"], "status0": t0["status"],
               "entry0": t0.get("entry"), "stop0": t0.get("stop")}
        for k in (0.10, 0.15, 0.25):
            rec[f"r_floor{k}"] = trade(b, bull, k * atrp)["r"]
        recs.append(rec)
T = pd.DataFrame(recs)
T.to_pickle(os.path.join(OUT, "intraday_v2.pkl"))

SPLIT, LIVE = pd.Timestamp("2025-07-21"), pd.Timestamp("2026-11-02")
sets = {"DEV": T[T.symbol.isin(WATCH) & (T.day < SPLIT)],
        "SECOND LOOK A": T[T.symbol.isin(WATCH) & (T.day >= SPLIT) & (T.day < LIVE)],
        "SECOND LOOK B": T[~T.symbol.isin(WATCH) & (T.day < LIVE)],
        "LIVE WINDOW": T[T.symbol.isin(WATCH) & (T.day >= LIVE)]}


def stats(X, col="r0", cap=None):
    X = X[X[col].notna()]
    if cap:
        X = X.assign(a=-X.score.abs()).sort_values(["day", "a"]).groupby("day").head(cap)
    if not len(X): return {"n": 0}
    r = X[col]; days = pd.date_range(X.day.min(), X.day.max(), freq="D")
    d = r.groupby(X.day).sum().reindex(days, fill_value=0.0)
    w, l = r[r > 0], r[r <= 0]
    eq = d.cumsum(); dd = float((eq - eq.cummax()).min())
    return {"n": int(len(r)), "win": round(float((r > 0).mean()), 3), "avg_r": round(float(r.mean()), 3),
            "pf": round(float(w.sum() / abs(l.sum())), 2) if l.sum() else None, "total_r": round(float(r.sum()), 1),
            "day_sharpe": round(float(d.mean() / d.std() * np.sqrt(365)), 2) if d.std() > 0 else None,
            "max_dd_r": round(dd, 1), "worst_day_r": round(float(d.min()), 1)}


def variants(X):
    out = {"S0 current": stats(X)}
    for x in (0.10, 0.20, 0.30): out[f"S1 cost<= {int(x*100)}%"] = stats(X[X.cost_frac <= x])
    for k in (0.10, 0.15, 0.25): out[f"S2 floor {k} ATR"] = stats(X, f"r_floor{k}")
    out["S3 |score|>=40"] = stats(X[X.score.abs() >= 40])
    out["S4 longs only"] = stats(X[X.bull]); out["S4 shorts only"] = stats(X[~X.bull])
    out["S5 cap 2/day"] = stats(X, cap=2)
    return out

res = {}
if __name__ == "__main__":
    which = sys.argv[1:] or ["DEV"]
    for name in which:
        res[name] = variants(sets[name])
        print("\n==", name, str(sets[name].day.min())[:10], "to", str(sets[name].day.max())[:10])
        print(pd.DataFrame(res[name]).T.to_string())
    if "DEV" in which:
        X = sets["DEV"]; mid = X.day.min() + (X.day.max() - X.day.min()) / 2
        print("\nDEV halves, avg R:", {k: (stats(X[(X.day < mid) & m])["avg_r"], stats(X[(X.day >= mid) & m])["avg_r"])
              for k, m in {"long": X.bull, "short": ~X.bull, "all": X.bull | ~X.bull}.items()})
        print("DEV cost drag: median cost/risk", round(float(X.cost_frac.median()), 3), "mean of filled", round(float(X[X.r0.notna()].cost_frac.clip(upper=5).mean()), 3),
              " share of sessions with cost > 20% of risk:", round(float((X.cost_frac > 0.2).mean()), 3))
        q = pd.qcut(X.cost_frac.clip(upper=5), 4)
        print(X[X.r0.notna()].groupby(q, observed=True).r0.agg(["count", "mean"]).round(3).to_string())
    json.dump(res, open(os.path.join(OUT, "results", "intraday_v2_" + "_".join(w.replace(" ", "") for w in which) + ".json"), "w"), indent=1)
