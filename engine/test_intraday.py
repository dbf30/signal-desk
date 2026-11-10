import numpy as np, pandas as pd
from intraday import intraday_trade, session_window, session_bars
from datetime import date

A = np.array
# open drive, bull: entry 100 at open, atr 8 -> stop 98, target 104 (2R)
r = intraday_trade(A([100, 101, 103]), A([101, 104.5, 104]), A([99.5, 100.5, 102]), A([101, 104, 103]), True, "open", 8, 0.25, 2.0, 0.0, False)
assert r["status"] == "target hit" and r["entry"] == 100 and r["stop"] == 98 and r["target"] == 104 and abs(r["r"] - 2) < 1e-9, r
# stopped on the first bar -> -1R
r = intraday_trade(A([100]), A([100.5]), A([97.5]), A([98]), True, "open", 8, 0.25, 2.0, 0.0, False)
assert r["status"] == "stopped" and abs(r["r"] + 1) < 1e-9, r
# session ends without stop/target -> closed at session end
r = intraday_trade(A([100, 101]), A([101, 102]), A([99, 100.5]), A([101, 101.5]), True, "open", 8, 0.25, 2.0, 0.0, True)
assert r["status"] == "closed at session end" and abs(r["r"] - 0.75) < 1e-9, r
# still running -> in trade
r = intraday_trade(A([100, 101]), A([101, 102]), A([99, 100.5]), A([101, 101.5]), True, "open", 8, 0.25, 2.0, 0.0, False)
assert r["status"] == "in trade", r
# bear open drive mirrors
r = intraday_trade(A([100, 99]), A([100.5, 99.5]), A([99, 95.5]), A([99, 96]), False, "open", 8, 0.25, 2.0, 0.0, False)
assert r["status"] == "target hit" and r["stop"] == 102 and r["target"] == 96, r
# ORB bull: range 100-105 from first bar, breaks on bar 3, exits at session end
o, h, l, c = A([102, 104, 105.5]), A([105, 104.8, 108]), A([100, 103, 105]), A([103, 104, 107])
assert intraday_trade(o[:1], h[:1], l[:1], c[:1], True, "orb", 0, None, None, 0.0, False)["status"] == "range forming"
assert intraday_trade(o[:2], h[:2], l[:2], c[:2], True, "orb", 0, None, None, 0.0, False)["status"] == "waiting for entry"
r = intraday_trade(o, h, l, c, True, "orb", 0, None, None, 0.0, True)
# bar 3 opens above 105 -> fills at open 105.5, risk 5.5, closes 107 -> +0.2727R
assert r["entry"] == 105.5 and r["status"] == "closed at session end" and abs(r["r"] - 1.5 / 5.5) < 1e-3, r
# ORB never triggers and the session ends -> no fill
r = intraday_trade(A([102, 103]), A([105, 104]), A([100, 101]), A([103, 102]), True, "orb", 0, None, None, 0.0, True)
assert r["status"] == "no fill", r
# costs reduce R
r = intraday_trade(A([100, 101, 103]), A([101, 104.5, 104]), A([99.5, 100.5, 102]), A([101, 104, 103]), True, "open", 8, 0.25, 2.0, 0.001, False)
assert abs(r["r"] - (2 - 0.001 * 100 / 2)) < 1e-9, r

# session windows: US futures 09:30-16:00 New York; first hourly bar used is 10:00 NY
s, e = session_window("US500", "index", date(2026, 11, 3))
assert str(s) == "2026-11-03 14:30:00+00:00" and str(e) == "2026-11-03 21:00:00+00:00", (s, e)
idx = pd.date_range("2026-11-03 13:00", periods=9, freq="h", tz="UTC")
df = pd.DataFrame({"open": range(9), "high": range(9), "low": range(9), "close": range(9)}, index=idx)
b, _, _ = session_bars(df, "US500", "index", date(2026, 11, 3))
assert str(b.index[0]) == "2026-11-03 15:00:00+00:00" and str(b.index[-1]) == "2026-11-03 20:00:00+00:00", b.index
s, e = session_window("BTC", "crypto", date(2026, 7, 1))   # summer: 08:00 UK = 07:00 UTC
assert str(s) == "2026-07-01 07:00:00+00:00" and str(e) == "2026-07-01 19:00:00+00:00", (s, e)
print("ALL TESTS PASSED")
