"""Q1 and Q2 of PREREG_V2.md. Usage: python3 swing_v2.py dev | second"""
import sys, os, json, pickle
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
from scorecard import COST
import portfolio as P

OUT = P.OUT; D = P.D
T = P.S.join(P.sim("base")).join(pd.read_pickle(os.path.join(OUT, "features.pkl")))
T["bull"] = T.direction == "bullish"
T["group"] = T.cls + ":" + T.direction
T["filled"] = T.status.isin(["win", "loss", "open"])
lim = np.where(T.bull, T.hi, T.lo); T["cost_r"] = [COST[c] for c in T.cls] * lim * 2 / np.abs(lim - T.brk)
eq, cr = T.cls.isin(["stock", "index"]), T.cls == "crypto"
sgn = np.where(T.bull, 1, -1)
T["backdrop"] = np.where(eq, np.where(T.spy_reg * sgn > 0, "with", "against"), np.where(cr, np.where(T.btc_reg * sgn > 0, "with", "against"), "n/a"))
T["f_score"] = pd.cut(T.score.abs(), [0, 55, 70, 101], labels=["40-55", "55-70", "70+"], right=False)
T["f_room"] = np.where(T.rr.isna(), "no level", np.where(T.rr < 1.5, "<1.5", np.where(T.rr < 3, "1.5-3", "3+")))
T["f_stretch"] = np.where(T.stretch > 2, "stretched", "ok")
T["f_dist"] = np.where(T.dist == 0, "in zone", np.where(T.dist <= 1, "<=1", np.where(T.dist <= 2, "1-2", ">2")))
T["f_vol"] = np.where(T.volratio > 1.5, ">1.5", "<=1.5")
T["f_anchor"] = np.where(T.touches >= 2, "2+ touches", np.where(T.touches == 1, "1 touch", "no level"))
FACT = ["group", "f_score", "f_room", "f_stretch", "f_dist", "f_vol", "backdrop", "f_anchor"]
DEV0, DEV1, HOLD1 = pd.Timestamp("2010-01-01"), pd.Timestamp("2022-12-31"), pd.Timestamp("2026-11-10")
MID = pd.Timestamp("2016-12-31")
F = T[T.filled & T.status.isin(["win", "loss"])]
dev = F[(F.uni == "watch") & (F.fill_date >= DEV0) & (F.fill_date <= DEV1)]          # every daily signal (overlapping), used for Q1
# Q2 uses the scorecard's unit instead: one live trade per asset at a time, R against planned risk (as portfolio.py).
# Consecutive days' signals on one asset are near-copies of each other, so counting them all would overstate n.
EXTRA = T[["bull", "group", "backdrop", "cost_r", "touches", "rr", "dist", "stretch"] + [c for c in T.columns if c.startswith("f_")]]
def trades(uni, a, b):
    C = P.candidates("base", uni=uni).join(EXTRA)
    X = P.select(C)
    return X[X.status.isin(["win", "loss"]) & (X.fill_date >= a) & (X.fill_date <= b)]
dev2 = trades(("watch",), DEV0, DEV1)


def tab(X, col):
    g = X.groupby(col, observed=True).r
    return pd.DataFrame({"n": g.size(), "avg_r": g.mean().round(3), "win": g.apply(lambda r: (r > 0).mean()).round(3)})


def q1():
    out = {}
    # (a) closed-only bias: replay the scorecard's recording rule from random start dates
    W = T[T.uni == "watch"].sort_values(["date", "symbol"])
    rng = np.random.default_rng(7)
    starts = pd.to_datetime(rng.choice(pd.date_range("2010-01-04", "2022-12-01", freq="B").values, 300, replace=False))
    far = pd.Timestamp("2200-01-01"); res = []
    bydate = {d: g for d, g in W.groupby("date")}
    for t0 in starts:
        t1 = t0 + pd.Timedelta(days=9); active = {}; closed = 0; closed_r = 0.0; open_r = 0.0; n_open = 0; pend = 0
        ents = []
        for d in pd.date_range(t0, t1, freq="D"):
            g = bydate.get(d)
            if g is None: continue
            for s in g.itertuples():
                if active.get(s.symbol, pd.Timestamp("1900-01-01")) > d: continue
                idx = D["assets"][s.symbol]["df"].index
                if s.status == "unfilled" or not s.filled:
                    end = idx[min(len(idx) - 1, s.i + 10)]
                else:
                    end = s.exit_date if isinstance(s.exit_date, pd.Timestamp) else far
                active[s.symbol] = end; ents.append(s)
        for s in ents:
            if not s.filled or s.fill_date > t1: pend += 1; continue
            if isinstance(s.exit_date, pd.Timestamp) and s.exit_date <= t1:
                closed += 1; closed_r += s.r_raw if hasattr(s, "r_raw") else s.r
            else:
                idx = D["assets"][s.symbol]["df"].index; pi, pm = s.path
                m = pm[idx[pi] <= t1]
                if len(m): n_open += 1; open_r += float(m[-1])
                else: pend += 1
        res.append((closed, closed_r, n_open, open_r, pend))
    R = pd.DataFrame(res, columns=["closed", "closed_r", "open", "open_r", "pending"])
    winless = float(((R.closed_r <= -0.95 * R.closed) & (R.closed >= 5)).mean())
    out["closed_only_bias"] = {"starts": len(R), "median_closed": float(R.closed.median()), "median_closed_r": round(float(R.closed_r.median()), 2),
        "share_of_starts_closed_total_negative": round(float((R.closed_r < 0).mean()), 3),
        "share_of_starts_with_5plus_closed_and_no_winner": round(winless, 3),
        "median_open_r": round(float(R.open_r.median()), 2), "median_closed_plus_open": round(float((R.closed_r + R.open_r).median()), 2),
        "avg_closed_r_per_closed_trade": round(float(R.closed_r.sum() / max(1, R.closed.sum())), 3),
        "avg_closed_plus_open_per_start": round(float((R.closed_r + R.open_r).mean()), 2)}
    # (b) horizon: marked R n bars after the fill (final R if already closed)
    hz = {}
    for grp, X in dev.groupby("group"):
        row = {"n": int(len(X))}
        for n in (5, 10, 20, 40, 60):
            row[str(n)] = round(float(np.mean([pm[min(n, len(pm) - 1)] for _, pm in X.path])), 3)
        hz[grp] = row
    allr = {"n": int(len(dev))}
    for n in (5, 10, 20, 40, 60): allr[str(n)] = round(float(np.mean([pm[min(n, len(pm) - 1)] for _, pm in dev.path])), 3)
    hz["ALL"] = allr; out["horizon_marked_r"] = hz
    out["time_to_close_bars"] = {"losers_median": float(np.median([len(pm) for pm in dev[dev.r <= 0].path.map(lambda p: p[1])])),
                                 "winners_median": float(np.median([len(pm) for pm in dev[dev.r > 0].path.map(lambda p: p[1])]))}
    # (c) cost drag
    out["cost_as_share_of_risk"] = {"swing_median": round(float(dev.cost_r.median()), 4), "swing_mean": round(float(dev.cost_r.mean()), 4)}
    return out


def q2_dev():
    out = {}
    h1, h2 = dev2[dev2.fill_date <= MID], dev2[dev2.fill_date > MID]
    print("Q2 development trades (one per asset at a time):", len(dev2), "avg R", round(dev2.r.mean(), 3))
    for f in FACT:
        t = tab(dev2, f); t["h1"] = tab(h1, f).avg_r; t["h2"] = tab(h2, f).avg_r
        big = t[t.n >= 150]
        verdict = "fail (too few trades)"
        if len(big) >= 2:
            best, worst = big.avg_r.idxmax(), big.avg_r.idxmin()
            gap = big.avg_r[best] - big.avg_r[worst]
            holds = (t.h1[best] > t.h1[worst]) and (t.h2[best] > t.h2[worst])
            verdict = f"{'PASS' if gap >= 0.15 and holds else 'fail'} (best {best} vs worst {worst}: gap {gap:.2f}R, holds in both halves: {holds})"
        out[f] = {"table": t.reset_index().to_dict("records"), "verdict": verdict}
        print("\n", f, "->", verdict); print(t.to_string())
    return out


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "dev":
        res = {"q1": q1() if "--skip-q1" not in sys.argv else None, "q2_dev": q2_dev()}
        json.dump(res, open(os.path.join(OUT, "results", "swing_v2_dev.json"), "w"), indent=1, default=str)
