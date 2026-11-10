import json
from tf import *
watch = [s for s, a in D["assets"].items() if a["set"] == "watch"]
unseen = [s for s, a in D["assets"].items() if a["set"] == "unseen"]
LEV = 10 / 8.9
out = {}
def show(k, m): out[k] = {kk: (float(v) if isinstance(v, (int, float, np.floating)) else v) for kk, v in m.items()}; print(k, out[k], flush=True)
for uname, syms in [("watchlist", watch), ("unseen", unseen), ("both", watch + unseen)]:
    p, Wn, lp, sp = run(syms, "T1", True, lev=LEV)
    for wn, w in [("dev", DEV), ("holdout", HOLD)]:
        show(f"FINAL {uname} {wn}", stats(p, *w))
    pc, *_ = run(syms, "T1", True, cost_mult=2.0, lev=LEV); show(f"FINAL costs x2 {uname} holdout", stats(pc, *HOLD))
    # bearish question: long/short version and its short leg on its own, same leverage
    p2, W2, lp2, sp2 = run(syms, "T1", False, lev=LEV)
    show(f"(ref) long/short {uname} holdout", stats(p2, *HOLD))
    for wn, w in [("dev", DEV), ("holdout", HOLD)]:
        s_ = sp2[(sp2.index >= w[0]) & (sp2.index <= w[1])]
        print(f"   short leg {uname} {wn}: total {100*s_.sum():.1f}% of capital, Sharpe {s_.mean()/s_.std()*np.sqrt(365):.2f}")
    if uname == "both":
        p.to_pickle("tf_final_both_pnl.pkl"); Wn.to_pickle("tf_final_both_w.pkl")
    if uname == "watchlist":
        p.to_pickle("tf_final_watch_pnl.pkl")
for bn in ["SPY_BH", "DBMF", "KMLM"]:
    for wn, w in [("dev", DEV), ("holdout", HOLD)]:
        show(f"{bn} {wn}", bench(bn, *w))
json.dump(out, open("tf_holdout.json", "w"), indent=1)
