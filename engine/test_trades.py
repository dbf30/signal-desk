import math
import pandas as pd
from trades import simulate_trade, MAX_WAIT, MAX_HOLD


def bars(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


L = {"direction": "bullish", "zone": {"lo": 98, "hi": 100}, "signal_break": 95}
S = {"direction": "bearish", "zone": {"lo": 100, "hi": 102}, "signal_break": 105}
N = float("nan")

# long fills at 100 (risk 5), score fades below 15 at bar 2's close -> exits at bar 3 open 112 -> +2.4R
b = bars([[103, 104, 99, 101], [101, 106, 100, 105], [105, 111, 104, 110], [112, 113, 111, 112]])
r = simulate_trade(L, b, [50, 50, 10, 10])
assert r["status"] == "win" and abs(r["r"] - 2.4) < 1e-9 and r["exit_reason"] == "signal faded", r
# gap below the limit -> fills at open 99 (risk 4)
r = simulate_trade(L, bars([[99, 99.5, 98, 99], [99, 100, 98.5, 100], [103, 104, 102, 103]]), [50, 5, 5])
assert r["entry"] == 99 and abs(r["r"] - 1.0) < 1e-9, r
# fill bar also hits the stop -> -1R
r = simulate_trade(L, bars([[101, 101, 94, 96]]), [50])
assert r["status"] == "loss" and abs(r["r"] + 1) < 1e-9, r
# gap through the stop -> exits at the worse open (93 -> -1.4R)
r = simulate_trade(L, bars([[101, 101, 99.5, 100], [93, 94, 92, 93]]), [50, 50])
assert r["status"] == "loss" and abs(r["r"] + 1.4) < 1e-9, r
# stop is checked before the signal exit on the same bar
r = simulate_trade(L, bars([[101, 101, 99.5, 100], [100, 101, 94, 96]]), [10, 10])
assert r["exit_reason"] == "stop", r
# unfilled / pending
assert simulate_trade(L, bars([[103, 104, 101, 103]] * MAX_WAIT), [50] * MAX_WAIT)["status"] == "unfilled"
assert simulate_trade(L, bars([[103, 104, 101, 103]] * 3), [50] * 3)["status"] == "pending"
# still running -> open, marked to the last close
r = simulate_trade(L, bars([[101, 101, 99.5, 100], [100, 103, 99, 102.5]]), [50, 50])
assert r["status"] == "open" and abs(r["r"] - 0.5) < 1e-9, r
# NaN scores never trigger the signal exit; time limit closes at the close MAX_HOLD bars after fill
rows = [[101, 101, 99.5, 100]] + [[100, 101, 99, 101]] * MAX_HOLD
r = simulate_trade(L, bars(rows), [N] * (MAX_HOLD + 1))
assert r["exit_reason"] == "time limit" and abs(r["r"] - 0.2) < 1e-9, r
# short mirror: fills at 100 (risk 5), score back above -15 -> exit at next open 90 -> +2R
r = simulate_trade(S, bars([[99, 101, 98, 100], [97, 98, 91, 92], [90, 91, 89, 90]]), [-50, -10, -10])
assert r["status"] == "win" and abs(r["r"] - 2.0) < 1e-9, r
# costs reduce R
r = simulate_trade(L, b, [50, 50, 10, 10], cost_frac=0.001)
assert abs(r["r"] - (2.4 - 0.001 * 100 * 2 / 5)) < 1e-9, r
print("ALL TESTS PASSED")
