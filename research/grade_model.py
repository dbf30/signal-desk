"""Q2 of PREREG_V2.md: fit the grade model on development trades, then (mode 'second') check it once on later data.
Usage: python3 grade_model.py fit | second"""
import sys, os, json
import numpy as np, pandas as pd
mode = sys.argv[1]; sys.argv = [sys.argv[0], "none"]
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "swing_v2.py")).read().split("if __name__")[0])

SHRINK_N = 200          # group means are pulled toward zero as if 200 zero-R trades were added
FACTOR_SHRINK = 0.5     # factor effects are halved: they overlap and were chosen on this same data
CUTS = {"A+": 0.50, "A": 0.30, "B": 0.12, "C": 0.0}     # predicted R per trade; below 0 = Avoid


def factor_cols(X):
    return pd.DataFrame({
        "backdrop": X.backdrop,
        "location": np.where(X.dist == 0, "in zone", np.where(X.dist <= 2, "within 2 ATR", "beyond 2 ATR")),
        "freshness": np.where(X.score.abs() < 55, "score 40-55", "score 55+"),
        "overhead": np.where(X.rr.isna(), "none ahead", np.where(X.rr < 1.5, "close", "far")),
        "anchor": np.where(X.touches == 0, "no level", "level"),
    }, index=X.index)

BASE = {"backdrop": "n/a", "location": "within 2 ATR", "freshness": "score 55+", "overhead": "far", "anchor": "level"}


def fit(X):
    y = X.r.clip(upper=X.r.quantile(0.99))
    g = X.groupby("group").r.agg(["size", "mean"])
    gm = (g["mean"] * g["size"] / (g["size"] + SHRINK_N)).round(3)
    res = y - X.group.map(g["mean"])
    Fc = factor_cols(X)
    cols, names = [], []
    for f, base in BASE.items():
        for lv in sorted(Fc[f].unique()):
            if lv != base:
                cols.append((Fc[f] == lv).astype(float).values); names.append((f, lv))
    A = np.column_stack([np.ones(len(X))] + cols)
    beta, *_ = np.linalg.lstsq(A, res.values, rcond=None)
    eff = {f: {BASE[f]: 0.0} for f in BASE}
    for (f, lv), b in zip(names, beta[1:]):
        eff[f][lv] = round(float(b) * FACTOR_SHRINK, 3)
    return {"groups": {k: float(v) for k, v in gm.items()}, "group_n": {k: int(v) for k, v in g["size"].items()},
            "group_raw": {k: round(float(v), 3) for k, v in g["mean"].items()},
            "factors": eff, "intercept": round(float(beta[0]) * FACTOR_SHRINK, 3), "cuts": CUTS}


def predict(M, X):
    Fc = factor_cols(X)
    p = X.group.map(M["groups"]).astype(float) + M["intercept"]
    for f in BASE:
        p = p + Fc[f].map(M["factors"][f]).fillna(0.0).astype(float)
    return p


def grade(p):
    return np.where(p >= CUTS["A+"], "A+", np.where(p >= CUTS["A"], "A", np.where(p >= CUTS["B"], "B", np.where(p >= CUTS["C"], "C", "Avoid"))))


def table(X, M):
    X = X.assign(pred=predict(M, X)); X["grade"] = grade(X.pred)
    rows = {}
    for gname in ["A+", "A", "B", "C", "Avoid"]:
        r = X[X.grade == gname].r
        if len(r) == 0:
            rows[gname] = {"n": 0}; continue
        rng = np.random.default_rng(11); bs = [r.sample(len(r), replace=True, random_state=rng.integers(1 << 31)).mean() for _ in range(1000)]
        rows[gname] = {"n": int(len(r)), "avg_r": round(float(r.mean()), 3), "ci_lo": round(float(np.percentile(bs, 5)), 3),
                       "ci_hi": round(float(np.percentile(bs, 95)), 3), "win": round(float((r > 0).mean()), 3),
                       "pf": round(float(r[r > 0].sum() / abs(r[r <= 0].sum())), 2) if (r <= 0).any() else None}
    top = X[X.grade.isin(["A+", "A"])].r; rest = X[~X.grade.isin(["A+", "A"])].r
    rows["A_or_better_minus_rest"] = round(float(top.mean() - rest.mean()), 3) if len(top) and len(rest) else None
    return rows

MP = os.path.join(OUT, "results", "grade_model.json")
if mode == "fit":
    M = fit(dev2)
    M["fitted_on"] = {"set": "watchlist, one trade per asset at a time", "from": "2010-01-01", "to": "2022-12-31", "trades": int(len(dev2))}
    M["development"] = table(dev2, M)
    json.dump(M, open(MP, "w"), indent=1)
    print(json.dumps(M, indent=1))
    g = pd.Series(grade(predict(M, dev2))).value_counts(normalize=True).round(3); print(g.to_dict())
else:
    M = json.load(open(MP))
    looks = {"watchlist 2023-2026": trades(("watch",), pd.Timestamp("2023-01-01"), HOLD1),
             "unseen markets 2010-2022": trades(("unseen",), DEV0, DEV1),
             "unseen markets 2023-2026": trades(("unseen",), pd.Timestamp("2023-01-01"), HOLD1)}
    M["second_look"] = {k: table(v, M) for k, v in looks.items()}
    allx = pd.concat(looks.values()); M["second_look"]["all three together"] = table(allx, M)
    json.dump(M, open(MP, "w"), indent=1)
    for k, v in M["second_look"].items():
        print("\n", k); print(pd.DataFrame({g: r for g, r in v.items() if isinstance(r, dict)}).T.to_string()); print("A or better minus the rest:", v["A_or_better_minus_rest"])
