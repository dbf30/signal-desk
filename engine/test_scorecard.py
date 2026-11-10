import pandas as pd
from scorecard import new_entries, update_entry, summarise

data = {"assets": [
    {"symbol": "AAA", "status": "ok", "asset_class": "stock"},
    {"symbol": "BBB", "status": "ok", "asset_class": "fx"},
    {"symbol": "CCC", "status": "ok", "asset_class": "stock", "stale": True}]}
setups = {"assets": [
    {"symbol": "AAA", "status": "ok", "as_of": "2024-01-01", "score": 55, "direction": "bullish",
     "zone": {"lo": 98, "hi": 100}, "signal_break": 95},
    {"symbol": "BBB", "status": "ok", "as_of": "2024-01-01", "score": 20, "direction": "bullish",
     "zone": {"lo": 1, "hi": 2}, "signal_break": 0.5},                      # too weak
    {"symbol": "CCC", "status": "ok", "as_of": "2024-01-01", "score": 70, "direction": "bullish",
     "zone": {"lo": 1, "hi": 2}, "signal_break": 0.5}]}                      # stale prices
e = new_entries(data, setups, [])
assert [x["symbol"] for x in e] == ["AAA"], e
# no duplicate while active, nor for the same signal date
assert new_entries(data, setups, e) == []
closed = [dict(e[0], status="win")]
assert new_entries(data, setups, closed) == []          # same date already recorded

idx = pd.date_range("2024-01-01", periods=5, freq="B")
df = pd.DataFrame({"open": [100, 103, 101, 105, 112], "high": [101, 104, 106, 111, 113],
                   "low": [99, 99, 100, 104, 111], "close": [100, 101, 105, 110, 112]}, index=idx)
scores = {"2024-01-02": 50, "2024-01-03": 50, "2024-01-04": 10, "2024-01-05": 10}
x = update_entry(dict(e[0]), df, scores)
# bars after 2024-01-01: fill 01-02 at 100 (low 99), exit at 01-05 open 112 after score 10 at 01-04 close
assert x["status"] == "win" and x["fill_date"] == "2024-01-02" and x["exit_date"] == "2024-01-05", x
assert abs(x["r"] - (12 / 5 - 5e-4 * 100 * 2 / 5)) < 1e-9, x
s = summarise([x, dict(x, r=-1.0, status="loss", asset_class="fx")])
assert s["all"]["closed"] == 2 and s["all"]["win_rate"] == 0.5 and set(s["groups"]) == {"stock:bullish", "fx:bullish"}
print("ALL TESTS PASSED")
