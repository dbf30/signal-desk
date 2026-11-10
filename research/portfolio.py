"""Portfolio selection (risk budget, cluster caps, filters), daily mark-to-market equity and pro metrics."""
import os, pickle
import numpy as np, pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
D = pickle.load(open(os.path.join(OUT, "data.pkl"), "rb"))
S = pd.read_pickle(os.path.join(OUT, "setups.pkl"))
SIMS = {}
def sim(name):
    if name not in SIMS: SIMS[name] = pd.read_pickle(os.path.join(OUT, f"sim_{name}.pkl"))
    return SIMS[name]
RISK = 0.005

CLUSTER = {}
for s in ["SPY","QQQ","AAPL","MSFT","NVDA","AMZN","TSLA","US500","NAS100","US30","US2000","JPM","XOM","JNJ","PG","KO","HD","CAT","WMT","INTC","CSCO"]: CLUSTER[s] = "us_equity"
for s in ["GER40","UK100","EU50"]: CLUSTER[s] = "europe_equity"
for s in ["JP225","HK50","AUS200"]: CLUSTER[s] = "asia_equity"
for s in ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","NZD/USD","USD/CHF","EUR/JPY"]: CLUSTER[s] = "fx"
for s in ["ZT","ZF","ZN","ZB","TLT","IEF","TIP","LQD"]: CLUSTER[s] = "rates"
for s in ["GOLD","SILVER","PLATINUM","PALLADIUM"]: CLUSTER[s] = "metals"
for s in ["WTI","NATGAS","HEATOIL","GASOLINE"]: CLUSTER[s] = "energy"
for s in ["COPPER"]: CLUSTER[s] = "industrial"
for s in ["CORN","WHEAT","SOYBEAN"]: CLUSTER[s] = "grains"
for s in ["COFFEE","SUGAR","COCOA","COTTON"]: CLUSTER[s] = "softs"
for s in ["CATTLE","HOGS"]: CLUSTER[s] = "livestock"
for s, a in D["assets"].items():
    if a["cls"] == "crypto": CLUSTER[s] = "crypto"

S = S.assign(cls=S.symbol.map(lambda s: D["assets"][s]["cls"]), uni=S.symbol.map(lambda s: D["assets"][s]["set"]),
             cluster=S.symbol.map(CLUSTER))
spy_reg = D["spy_regime"].sort_index(); btc_reg = D["btc_regime"].sort_index()
S["spy_reg"] = spy_reg.reindex(S.date, method="ffill").values
S["btc_reg"] = btc_reg.reindex(S.date, method="ffill").values
S["volratio"] = [D["assets"][s]["volratio"].iloc[i] for s, i in zip(S.symbol, S.i)]


def candidates(simname="base", uni=("watch",), backdrop=False, backdrop_shorts_only=False, volfilter=False, no_eq_shorts=False, longs_only=False):
    T = S.join(globals()["sim"](simname) if isinstance(simname, str) else simname)
    T = T[T.uni.isin(uni) & T.status.isin(["win", "loss", "open"])].copy()
    # measure R against the PLANNED risk (limit price to stop), which is how the app sizes positions
    b_ = T.direction == "bullish"
    stop_ = T.brk if simname != "widestop" else pd.Series(np.where(b_, T.lo - 1.5 * T.atr, T.hi + 1.5 * T.atr), index=T.index)
    plan_ = pd.Series(np.where(b_, T.hi - stop_, stop_ - T.lo), index=T.index)
    act_ = pd.Series(np.where(b_, T.entry - stop_, stop_ - T.entry), index=T.index)
    k_ = (act_ / plan_).clip(upper=1.0)
    k_[(act_ <= 0) | (simname == "confirm")] = 1.0
    T["k"] = k_; T["r_raw"] = T.r; T["r"] = T.r * k_
    bull = T.direction == "bullish"; eq = T.cls.isin(["stock", "index"]); cr = T.cls == "crypto"
    keep = pd.Series(True, index=T.index)
    if backdrop or backdrop_shorts_only:
        bad_long = (eq & (T.spy_reg <= 0)) | (cr & (T.btc_reg <= 0))
        bad_short = (eq & (T.spy_reg >= 0)) | (cr & (T.btc_reg >= 0))
        keep &= ~(~bull & bad_short)
        if backdrop: keep &= ~(bull & bad_long)
    if volfilter: keep &= ~(T.volratio > 1.5)
    if no_eq_shorts: keep &= ~(~bull & eq)
    if longs_only: keep &= bull
    return T[keep]


def select(T, max_open=None, cluster_cap=None, rank=False):
    order = ["fill_date", "date"] if not rank else ["fill_date", "absscore"]
    T = T.assign(absscore=-T.score.abs()).sort_values(order + ["symbol"])
    held = []  # (symbol, cluster, exit_date)
    taken = []
    far = pd.Timestamp("2200-01-01")
    for t in T.itertuples():
        d = t.fill_date
        held = [x for x in held if x[2] > d]
        if any(x[0] == t.symbol for x in held): continue
        if max_open and len(held) >= max_open: continue
        if cluster_cap and sum(x[1] == t.cluster for x in held) >= cluster_cap: continue
        held.append((t.symbol, t.cluster, t.exit_date if isinstance(t.exit_date, pd.Timestamp) else far))
        taken.append(t.Index)
    return T.loc[taken]


def daily_pnl(T):
    ds, xs = [], []
    for sym, (pi, pm), kk in zip(T.symbol, T.path, T.k):
        idx = D["assets"][sym]["df"].index
        ds.append(idx[pi].values); xs.append(np.diff(pm.astype(float) * kk, prepend=0.0))
    s = pd.Series(np.concatenate(xs), index=np.concatenate(ds)).groupby(level=0).sum() * RISK
    return s.reindex(pd.date_range("2009-06-01", "2026-11-10", freq="D"), fill_value=0.0)


def metrics(T, a, b, pnl=None):
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    pnl = daily_pnl(T) if pnl is None else pnl
    p = pnl[(pnl.index >= a) & (pnl.index <= b)]
    eq = 1 + p.cumsum()
    yrs = (b - a).days / 365.25
    ret = p                       # fixed risk on starting capital: daily P&L as a fraction of starting capital
    dd = (eq - eq.cummax().clip(lower=1)).min()
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1
    down = ret[ret < 0]
    W = T[(T.fill_date >= a) & (T.fill_date <= b)]
    C = W[W.status.isin(["win", "loss"])]
    w, l = C[C.r > 0].r, C[C.r <= 0].r
    days = pd.date_range(a, b, freq="D")
    fills = W.fill_date.values; exits = W.exit_date.fillna(pd.Timestamp("2200-01-01")).values
    expo = np.mean([((fills <= d) & (exits > d)).sum() for d in days[::7].values])
    return {"trades": len(C), "win%": round(100 * len(w) / max(1, len(C)), 1),
            "avg_win": round(w.mean(), 2) if len(w) else None, "avg_loss": round(l.mean(), 2) if len(l) else None,
            "PF": round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() else None, "avg_R": round(C.r.mean(), 3) if len(C) else None,
            "net%": round(100 * (eq.iloc[-1] - 1), 1), "CAGR%": round(100 * cagr, 2), "maxDD%": round(100 * dd, 1),
            "Sharpe": round(ret.mean() / ret.std() * np.sqrt(365), 2) if ret.std() > 0 else 0,
            "Sortino": round(ret.mean() / (np.sqrt((down ** 2).sum() / len(ret))) * np.sqrt(365), 2) if len(down) else None,
            "MAR": round(cagr / abs(dd), 2) if dd < 0 else None, "avg_open": round(expo, 1)}


def bench(name, a, b):
    s = D["bench"][name].sort_index(); s = s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))]
    if len(s) < 50: return None
    r = s.pct_change().dropna(); eq = s / s.iloc[0]; yrs = (pd.Timestamp(b) - pd.Timestamp(a)).days / 365.25
    dd = (eq / eq.cummax() - 1).min(); cagr = eq.iloc[-1] ** (1 / yrs) - 1
    return {"from": str(s.index[0])[:10], "net%": round(100 * (eq.iloc[-1] - 1), 1), "CAGR%": round(100 * cagr, 2), "maxDD%": round(100 * dd, 1),
            "Sharpe": round(r.mean() / r.std() * np.sqrt(252), 2), "MAR": round(cagr / abs(dd), 2)}
