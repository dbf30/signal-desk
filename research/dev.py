import json, pandas as pd
from portfolio import *
A, B = "2010-01-01", "2022-12-31"
RB = dict(max_open=6, cluster_cap=2, rank=True)
V = {
 "V0a every setup":        (candidates("base"), dict()),
 "V0b max 3 first-come":   (candidates("base"), dict(max_open=3)),
 "V1 risk budget":         (candidates("base"), RB),
 "V2 + backdrop/vol":      (candidates("base", backdrop=True, volfilter=True), RB),
 "B1 no stock/index shorts": (candidates("base", backdrop=True, volfilter=True, no_eq_shorts=True), RB),
 "B2x backdrop shorts only": (candidates("base", backdrop_shorts_only=True), RB),
 "B3 fast short exits":    (candidates("fastshort", backdrop=True, volfilter=True), RB),
 "B4 = B1 + B3":           (candidates("fastshort", backdrop=True, volfilter=True, no_eq_shorts=True), RB),
 "E1 wider stop":          (candidates("widestop", backdrop=True, volfilter=True), RB),
 "E2 confirmation entry":  (candidates("confirm", backdrop=True, volfilter=True), RB),
 "E3 half at 2R + trail":  (candidates("partial", backdrop=True, volfilter=True), RB),
 "(ref) V2 longs only":    (candidates("base", backdrop=True, volfilter=True, longs_only=True), RB),
}
rows = {}
for k, (T, kw) in V.items():
    P = select(T, **kw)
    m = metrics(P, A, B); rows[k] = m
    # bearish contribution inside the portfolio
    sh = P[(P.direction == "bearish") & P.status.isin(["win","loss"]) & (P.fill_date >= A) & (P.fill_date <= B)]
    m["short_trades"] = len(sh); m["short_avg_R"] = round(sh.r.mean(), 3) if len(sh) else None
    print(k, m, flush=True)
pd.DataFrame(rows).T.to_csv("dev_results.csv")
print(bench("SPY_BH", A, B))
