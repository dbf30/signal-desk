import pickle, json, numpy as np, pandas as pd
t = pd.read_csv("trades.csv")
px = pickle.load(open("prices.pkl","rb"))
print(t[(t.symbol.isin(["WTI","UK100","COPPER"])) & (t.signal_date>="2026-10-01")][["symbol","signal_date","status","fill_date","exit_date","r"]].to_string())

def closed_stats(c):
    w, l = c[c.r>0], c[c.r<=0]
    return dict(trades=len(c), win_rate=round(len(w)/len(c)*100,1), avg_win_R=round(w.r.mean(),2), avg_loss_R=round(l.r.mean(),2),
                win_loss_ratio=round(w.r.mean()/abs(l.r.mean()),2), profit_factor=round(w.r.sum()/abs(l.r.sum()),2),
                avg_R=round(c.r.mean(),3), total_R=round(c.r.sum(),1))

def daily_pnl_R(tr):
    """mark every filled trade to market at each daily close, in R; calendar days"""
    days = pd.date_range("2023-11-10","2026-11-10",freq="D")
    pnl = pd.Series(0.0, index=days)
    for _, x in tr.iterrows():
        if pd.isna(x.fill_date): continue
        c = px[x.symbol]["close"]; sgn = 1 if x.direction=="bullish" else -1
        risk = abs(x.entry - x.stop); f = pd.Timestamp(x.fill_date)
        end = pd.Timestamp(x.exit_date) if isinstance(x.exit_date,str) else c.index[-1]
        seg = c[(c.index>=f)&(c.index<=end)].copy()
        if x.status in ("win","loss"): seg.iloc[-1] = x.exit
        marks = sgn*(seg - x.entry)/risk
        steps = marks.diff(); steps.iloc[0] = marks.iloc[0]
        if x.status in ("win","loss"): steps.iloc[-1] += x.r - marks.iloc[-1]   # costs land at exit
        else: steps.iloc[-1] += x.r - marks.iloc[-1]
        for d, v in steps.items():
            if d in pnl.index: pnl[d] += v
    return pnl

def portfolio(tr, risk_pct, label):
    pnl = daily_pnl_R(tr) * risk_pct/100          # fraction of starting balance, no compounding
    eq = 1 + pnl.cumsum()
    dd = (eq/eq.cummax()-1).min()
    ret = pnl / eq.shift(1).fillna(1)
    sharpe = ret.mean()/ret.std()*np.sqrt(365)
    return dict(variant=label, net_return_pct=round((eq.iloc[-1]-1)*100,1), max_drawdown_pct=round(dd*100,1), sharpe=round(sharpe,2)), eq

def cap(tr, n):
    tr = tr[tr.fill_date.notna()].sort_values(["fill_date","signal_date"])
    taken, openx = [], []
    for _, x in tr.iterrows():
        f = x.fill_date
        openx = [e for e in openx if isinstance(e,str) and e > f] + [e for e in openx if not isinstance(e,str)]
        if len(openx) < n:
            taken.append(x); openx.append(x.exit_date if isinstance(x.exit_date,str) else None)
    return pd.DataFrame(taken)

out = {}
closed = t[t.status.isin(["win","loss"])]
out["all_closed"] = closed_stats(closed)
out["bullish_only_closed"] = closed_stats(closed[closed.direction=="bullish"])
out["bearish_only_closed"] = closed_stats(closed[closed.direction=="bearish"])
out["by_group"] = {f"{k[0]}:{k[1]}": closed_stats(g) for k, g in closed.groupby(["asset_class","direction"])}
out["by_year"] = {y: closed_stats(g) for y, g in closed.groupby(closed.fill_date.str[:4])}
out["setup_counts"] = t.status.value_counts().to_dict()
filled = t[t.fill_date.notna()]
p = []; eqs = {}
for lab, tr, rp in [("Every setup, 0.5% risk each", filled, 0.5),
                    ("Max 3 open (app default), 0.5% risk", cap(filled,3), 0.5),
                    ("Bullish only, max 3 open, 0.5% risk", cap(filled[filled.direction=="bullish"],3), 0.5)]:
    s, eq = portfolio(tr, rp, lab); s["trades_taken"] = len(tr); p.append(s); eqs[lab] = eq
out["portfolio"] = p
json.dump(out, open("results.json","w"), indent=1)
print(json.dumps(out, indent=1))
w = pd.DataFrame(eqs).resample("W").last()
w.to_csv("equity_weekly.csv")
