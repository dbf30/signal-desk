import json
from portfolio import *
RB = dict(max_open=6, cluster_cap=2, rank=True)
def final(uni): return select(candidates("widestop", uni=uni, backdrop_shorts_only=True), **RB)
def current(uni): return select(candidates("base", uni=uni), max_open=3)
W = [("dev 2010-2022","2010-01-01","2022-12-31"), ("holdout 2023-2026","2023-01-01","2026-11-10")]
out = {}
for uname, uni in [("watchlist", ("watch",)), ("unseen assets", ("unseen",)), ("both (widened universe)", ("watch","unseen"))]:
    for lab, P in [("current app rules", current(uni)), ("final candidate", final(uni))]:
        pnl = daily_pnl(P)
        for wn, a, b in W:
            m = metrics(P, a, b, pnl)
            sh = P[(P.direction=="bearish") & P.status.isin(["win","loss"]) & (P.fill_date>=a) & (P.fill_date<=b)]
            m["shorts"] = len(sh); m["short_avg_R"] = round(float(sh.r.mean()),3) if len(sh) else None
            out[f"{uname} | {lab} | {wn}"] = m
            print(f"{uname} | {lab} | {wn}", {k: (float(v) if v is not None else None) for k, v in m.items()}, flush=True)
        if lab == "final candidate" and uname == "both (widened universe)":
            P.to_pickle("final_both.pkl"); pnl.to_pickle("final_both_pnl.pkl")
for bn in ["SPY_BH","DBMF","KMLM"]:
    for wn, a, b in W:
        print(bn, wn, bench(bn, a, b))
json.dump({k: {kk: (float(vv) if vv is not None else None) for kk, vv in v.items()} for k, v in out.items()}, open("holdout_results.json","w"), indent=1)
