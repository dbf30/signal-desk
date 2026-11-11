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

# --- v2 additions (11 Nov 2026) ---
from intraday import bias_score, plan_for
# stop floor: range 100-105 (risk 5 from a 105 entry); floor 8 -> stop 97. Without it bar 3 stops out; with it, it survives.
o, h, l, c = A([102, 105.2, 104]), A([105, 106, 107]), A([100, 104.5, 99]), A([103, 105.5, 106])
r0 = intraday_trade(o, h, l, c, True, "orb", 0, None, None, 0.0, True)
assert r0["status"] == "stopped" and r0["stop"] == 100, r0
r1 = intraday_trade(o, h, l, c, True, "orb", 0, None, None, 0.0, True, stop_floor=8.0)
assert r1["stop"] == 105.2 - 8 or r1["stop"] == 97.0, r1
assert r1["status"] == "closed at session end" and r1["r"] > 0, r1
# a floor smaller than the range changes nothing
assert intraday_trade(o, h, l, c, True, "orb", 0, None, None, 0.0, True, stop_floor=1.0) == r0
# bear mirror
r2 = intraday_trade(A([103, 99.5]), A([105, 100]), A([100, 96]), A([102, 97]), False, "orb", 0, None, None, 0.0, True, stop_floor=9.0)
assert r2["entry"] == 99.5 and r2["stop"] == 109.0, r2

# bias comes from the last completed daily bar before the session, not the live score
row = {"symbol": "BTC", "asset_class": "crypto", "score": -30.0, "price": 100.0, "atr14_pct": 2.0,
       "history": [{"date": "2026-11-01", "score": -9.2}, {"date": "2026-11-02", "score": -30.0}]}
assert bias_score(row, date(2026, 11, 2)) == (-9.2, "2026-11-01")
assert bias_score(row, date(2026, 11, 3)) == (-30.0, "2026-11-02")
assert bias_score({"score": 20.0, "history": []}, date(2026, 11, 2)) == (20.0, None)
idx = pd.date_range("2026-11-02 08:00", periods=12, freq="h", tz="UTC")
hb = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 95.0, "close": 96.0}, index=idx)
p = plan_for(row, hb, pd.Timestamp("2026-11-02 21:00", tz="UTC"))
# the coin fell all day and the live score is now -30, but the bias was fixed at -9.2: no setup may be logged
assert p["bias"] is None and p["bias_rule"] == "prev_close" and p["score"] == -9.2, p
p = plan_for(row, hb.set_axis(idx + pd.Timedelta(days=1)), pd.Timestamp("2026-11-03 21:00", tz="UTC"))
assert p["bias"] == "bearish" and p["shadow"]["version"] == "intraday-v2-stopfloor" and p["version"] == "intraday-v1", p
assert p["shadow"]["stop"] >= p["stop"], p   # the shadow stop is never tighter than the live one (bearish: higher)
print("ALL TESTS PASSED")
