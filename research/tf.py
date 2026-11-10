"""Trend-following portfolio from the Signal Desk daily score (see PREREG_TF.md)."""
import sys, os, pickle, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import numpy as np, pandas as pd
from scorecard import COST

OUT = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(OUT, "data.pkl"), "rb"))
CAL = pd.date_range("2009-01-01", "2026-11-10", freq="D")
DEV, HOLD = ("2010-01-01", "2022-12-31"), ("2023-01-01", "2026-11-10")


def build(sym):
    a = D["assets"][sym]; c = a["df"]["close"].astype(float)
    c = c[c > 0]                                     # drop non-positive prints (WTI Apr 2020)
    r = c.pct_change()
    vol = r.rolling(63, min_periods=40).std()
    r = r.clip(lower=-6 * vol.shift(1), upper=6 * vol.shift(1))
    ann = np.sqrt(365 if a["cls"] == "crypto" else 252)
    sc = a["score"].reindex(c.index)
    week_end = pd.Series(c.index, index=c.index).groupby(c.index.to_period("W")).transform("max") == c.index
    return pd.DataFrame({"r": r, "vol": vol * ann, "score": sc, "rebal": week_end.values})


ASSET = {s: build(s) for s in D["assets"]}


def run(syms, variant="T1", long_only=False, cost_mult=1.0, lev=1.0):
    W, R, C = {}, {}, {}
    for s in syms:
        f = ASSET[s]
        w = f.score / 100 if variant == "T1" else np.sign(f.score).where(f.score.abs() >= 15, 0.0)
        w = w.where(f.score.notna())
        if long_only: w = w.clip(lower=0)
        notional = (w * 0.40 / f.vol).where(f.rebal).ffill()        # set at week end, held through the week
        notional = notional.reindex(CAL).ffill()
        W[s] = notional.shift(1)                                       # earned from the next day
        R[s] = f.r.reindex(CAL).fillna(0.0)
        C[s] = COST[D["assets"][s]["cls"]] * cost_mult
    W = pd.DataFrame(W); R = pd.DataFrame(R)
    n = W.notna().sum(axis=1).replace(0, np.nan)
    Wn = W.div(n, axis=0).fillna(0.0) * lev
    turn = Wn.diff().abs().fillna(0.0)
    pnl = (Wn * R).sum(axis=1) - (turn * pd.Series(C)).sum(axis=1)
    long_pnl = (Wn.clip(lower=0) * R).sum(axis=1); short_pnl = (Wn.clip(upper=0) * R).sum(axis=1)
    return pnl, Wn, long_pnl, short_pnl


def stats(p, a, b):
    p = p[(p.index >= a) & (p.index <= b)]
    eq = (1 + p).cumprod(); yrs = (pd.Timestamp(b) - pd.Timestamp(a)).days / 365.25
    dd = (eq / eq.cummax() - 1).min(); cagr = eq.iloc[-1] ** (1 / yrs) - 1
    down = p[p < 0]
    yearly = (1 + p).groupby(p.index.year).prod() - 1
    return {"net%": round(100 * (eq.iloc[-1] - 1), 1), "CAGR%": round(100 * cagr, 2), "vol%": round(100 * p.std() * np.sqrt(365), 1),
            "maxDD%": round(100 * dd, 1), "Sharpe": round(p.mean() / p.std() * np.sqrt(365), 2),
            "Sortino": round(p.mean() / np.sqrt((down ** 2).sum() / len(p)) * np.sqrt(365), 2),
            "MAR": round(cagr / abs(dd), 2) if dd < 0 else None, "years_up": f"{int((yearly > 0).sum())}/{len(yearly)}"}


def bench(name, a, b):
    s = D["bench"][name].sort_index()
    p = s.pct_change().reindex(CAL).fillna(0.0)
    if s.index[0] > pd.Timestamp(a) + pd.Timedelta(days=30):
        a = str(s.index[0])[:10]
    return {"from": a, **stats(p, a, b)}


if __name__ == "__main__":
    watch = [s for s, a in D["assets"].items() if a["set"] == "watch"]
    unseen = [s for s, a in D["assets"].items() if a["set"] == "unseen"]
    res = {}
    print("== development (watchlist 2010-2022) ==")
    for v in ["T1", "T2"]:
        for lo in [False, True]:
            p, *_ = run(watch, v, lo); m = stats(p, *DEV); res[f"dev {v} {'long-only' if lo else 'long/short'}"] = m
            print(v, "long-only" if lo else "long/short", m, flush=True)
    json.dump(res, open(os.path.join(OUT, "tf_dev.json"), "w"), indent=1)
