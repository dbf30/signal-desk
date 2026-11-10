from tf import *
watch = [s for s, a in D["assets"].items() if a["set"] == "watch"]
unseen = [s for s, a in D["assets"].items() if a["set"] == "unseen"]
LEV = 10 / 8.9
spy = D["bench"]["SPY_BH"].sort_index().pct_change().reindex(CAL).fillna(0.0)
# 1. always-long benchmark: same assets, same vol sizing, weight +1 always (no signal)
orig = {s: ASSET[s].score.copy() for s in ASSET}
for s in ASSET: ASSET[s]["score"] = orig[s].where(orig[s].isna(), 100.0)
for uname, syms in [("watchlist", watch), ("unseen", unseen), ("both", watch + unseen)]:
    p, *_ = run(syms, "T1", True, lev=LEV)
    for wn, w in [("dev", DEV), ("holdout", HOLD)]: print("ALWAYS-LONG", uname, wn, stats(p, *w))
for s in ASSET: ASSET[s]["score"] = orig[s]
# 2. correlation and beta to SPY; gross exposure
for uname, syms in [("watchlist", watch), ("both", watch + unseen)]:
    p, Wn, *_ = run(syms, "T1", True, lev=LEV)
    for wn, w in [("dev", DEV), ("holdout", HOLD)]:
        m = (p.index >= w[0]) & (p.index <= w[1]); wk = pd.DataFrame({"p": p[m], "s": spy[m]}).resample("W").sum()
        beta = wk.cov().iloc[0, 1] / wk.s.var()
        alpha = (wk.p - beta * wk.s).mean() * 52
        print(f"{uname} {wn}: weekly corr to SPY {wk.corr().iloc[0,1]:.2f}, beta {beta:.2f}, alpha after beta {100*alpha:.1f}%/yr, avg gross exposure {Wn[m].abs().sum(axis=1).mean():.2f}x")
# 3. look-ahead check: delay positions by one more week -> should degrade gently, not collapse or improve
for s in ASSET: ASSET[s]["score"] = orig[s].shift(5)
p, *_ = run(watch + unseen, "T1", True, lev=LEV); print("DELAYED 1 WEEK both", "dev", stats(p, *DEV)["Sharpe"], "holdout", stats(p, *HOLD)["Sharpe"])
# 4. placebo: random signals -> Sharpe should be near zero
rng = np.random.default_rng(0); sh = []
for k in range(20):
    for s in ASSET:
        x = pd.Series(rng.uniform(-100, 100, len(orig[s])), index=orig[s].index).where(orig[s].notna())
        ASSET[s]["score"] = x.rolling(20, min_periods=1).mean()
    p, *_ = run(watch + unseen, "T1", False, lev=LEV); sh.append(stats(p, "2010-01-01", "2026-11-10")["Sharpe"])
print("PLACEBO random long/short signals, 20 runs: mean Sharpe", round(float(np.mean(sh)), 2), "max", max(sh))
for s in ASSET: ASSET[s]["score"] = orig[s]
