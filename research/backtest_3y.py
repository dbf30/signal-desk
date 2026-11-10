"""3-year walk-forward backtest of Signal Desk's swing setups, using the app's own engine files
(engine.py, levels.py, trades.py, scorecard.py rules) unchanged. No look-ahead: each day's setup is
built only from bars up to that day's close."""
import sys, json, time, pickle, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import numpy as np, pandas as pd
from run import WATCHLIST, fetch_yahoo
from engine import signal_frame
from levels import analyse_levels
from trades import simulate_trade, MAX_WAIT, MAX_HOLD
from scorecard import COST

OUT = os.path.dirname(os.path.abspath(__file__))
START, END = pd.Timestamp("2023-11-10"), pd.Timestamp("2026-11-10")

cache = os.path.join(OUT, "prices.pkl")
if os.path.exists(cache):
    px = pickle.load(open(cache, "rb"))
else:
    px = {}
    for y, sym, name, cls in WATCHLIST:
        px[sym] = fetch_yahoo(y, "10y").sort_index(); time.sleep(0.3)
    pickle.dump(px, open(cache, "wb"))

# scores exactly as run.py builds them (crypto gets SPY regime + BTC factor)
spy = px["SPY"]["close"]; ma = spy.rolling(200, min_periods=200).mean()
regime = np.sign(spy - ma).where(ma.notna())
btc_factor = signal_frame(px["BTC"], "crypto")["score"]
cls_of = {sym: cls for _, sym, _, cls in WATCHLIST}
scores = {}
for sym, df in px.items():
    cls = cls_of[sym]
    ctx = None
    if cls == "crypto":
        ctx = {"risk_regime": regime}
        if sym != "BTC":
            ctx["btc_factor"] = btc_factor
    scores[sym] = signal_frame(df, cls, ctx)["score"]

trades = []
for sym, df in px.items():
    cls = cls_of[sym]; sc = scores[sym]; win = 730 if cls == "crypto" else 504
    idx = df.index
    blocked_until = pd.Timestamp("1900-01-01")
    for i, d in enumerate(idx):
        if d < START or d > END: continue
        s = sc.iloc[i]
        if pd.isna(s) or abs(s) < 40 or d < blocked_until: continue
        hist = df.iloc[max(0, i + 1 - win): i + 1]
        lv = analyse_levels({"symbol": sym, "score": float(s)}, hist)
        if "zone" not in lv: continue
        setup = {"direction": lv["direction"], "zone": lv["zone"], "signal_break": lv["signal_break"]}
        bars = df.iloc[i + 1: i + 1 + MAX_WAIT + MAX_HOLD + 1]
        r = simulate_trade(setup, bars, list(sc.iloc[i + 1: i + 1 + len(bars)]), COST[cls])
        if r["status"] in ("win", "loss"):
            blocked_until = pd.Timestamp(r["exit_date"])
        elif r["status"] == "unfilled":
            blocked_until = bars.index[MAX_WAIT - 1]
        else:  # open or pending at the end of data
            blocked_until = pd.Timestamp("2100-01-01")
        trades.append({"symbol": sym, "asset_class": cls, "direction": lv["direction"], "signal_date": str(d)[:10],
                       "score": round(float(s), 1), "zone_lo": lv["zone"]["lo"], "zone_hi": lv["zone"]["hi"],
                       "stop": lv["signal_break"], **{k: r.get(k) for k in ("status", "entry", "exit", "fill_date", "exit_date", "r", "exit_reason")}})
    print(sym, sum(t["symbol"] == sym for t in trades), flush=True)

pd.DataFrame(trades).to_csv(os.path.join(OUT, "trades.csv"), index=False)
pickle.dump({"scores": scores}, open(os.path.join(OUT, "scores.pkl"), "wb"))
print("setups:", len(trades))
