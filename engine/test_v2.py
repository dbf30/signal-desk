"""Tests for the v2 modules: regime.py, plans.py, analytics.py and the scorecard additions."""
import json, math
import pandas as pd
from regime import build as regime_build, regime_on, _trend
from plans import grade_for, swing_signal, intraday_signal, portfolio, briefing, build as plans_build, backdrop_for
from analytics import block, wilson, boot_ci, swing as a_swing, intraday as a_intraday, build as a_build
from scorecard import excursions, new_entries

# ---------------------------------------------------------------- regime
assert _trend(110, 105, 100, 50) == "Strong bullish" and _trend(101, 105, 100, 20) == "Moderate bullish"
assert _trend(90, 95, 100, -50) == "Strong bearish" and _trend(95, 97, 100, -20) == "Moderate bearish"
assert _trend(101, 99, 100, 5) == "Sideways" and _trend(None, 1, 1, 1) is None


def asset(sym, cls, score, price=110.0, sma50=105.0, sma200=100.0, vr=1.0, hist=None):
    hist = hist or [{"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "close": 100 + i * 0.05 + (0.3 if i % 2 else -0.3), "sma50": 99.0, "sma200": 95.0, "score": 45.0} for i in range(120)]
    return {"symbol": sym, "name": sym, "asset_class": cls, "status": "ok", "score": score, "label": "x", "price": price, "sma50": sma50,
            "sma200": sma200, "vol_ratio": vr, "as_of": "2026-11-10", "history": hist, "flags": [], "confidence": "High"}

D = {"assets": [asset("SPY", "stock", 50), asset("AAPL", "stock", 60), asset("ZN", "bond", -50), asset("GOLD", "commodity", -20), asset("BTC", "crypto", -40, price=90, sma200=100)]}
r = regime_build(D)
assert r["label"] == "Strong bullish" and r["overlay"] is None and r["backdrop"] == {"equity": "up", "crypto": "down"}, r
assert r["breadth"]["equity"]["bullish_pct"] == 100 and r["history"] and regime_on(r, "2026-03-01") == "Strong bullish" and regime_on(r, "2020-01-01") is None
D2 = {"assets": [asset("SPY", "stock", 50, vr=1.7)]}
assert regime_build(D2)["label"] == "High volatility" and regime_build(D2)["trend"] == "Strong bullish"
shock = [dict(h) for h in D["assets"][0]["history"]]; shock[-2]["close"] *= 0.93
assert regime_build({"assets": [asset("SPY", "stock", 50, hist=shock)]})["label"] == "Unstable"
D3 = {"assets": [asset("SPY", "stock", -30, price=90, sma50=95), asset("ZN", "bond", 40)]}
assert regime_build(D3)["label"] == "Risk-off" and regime_build(D3)["trend"] == "Moderate bearish"
assert regime_build({"assets": []})["label"] == "Unknown"

# ---------------------------------------------------------------- grades
M = {"groups": {"stock:bullish": 0.415, "stock:bearish": -0.276, "fx:bullish": -0.044}, "group_raw": {"stock:bullish": 0.525}, "group_n": {"stock:bullish": 753},
     "intercept": -0.134, "cuts": {"A+": 0.5, "A": 0.3, "B": 0.12, "C": 0.0},
     "factors": {"backdrop": {"n/a": 0.0, "against": -0.169, "with": -0.007}, "location": {"within 2 ATR": 0.0, "beyond 2 ATR": -0.247, "in zone": 0.089},
                 "freshness": {"score 55+": 0.0, "score 40-55": 0.098}, "overhead": {"far": 0.0, "close": 0.045, "none ahead": 0.063}, "anchor": {"level": 0.0, "no level": 0.213}}}
g = grade_for(M, "stock", "bullish", 45, True, 0.0, None, 0, r)
assert abs(g["predicted_r"] - (0.415 - 0.134 - 0.007 + 0.089 + 0.098 + 0.063 + 0.213)) < 1e-9 and g["grade"] == "A+", g
assert [p["factor"] for p in g["parts"]] == ["history", "baseline", "backdrop", "location", "freshness", "overhead", "anchor"]
assert abs(sum(p["effect"] for p in g["parts"]) - g["predicted_r"]) < 2e-3          # the parts add up to the prediction
g2 = grade_for(M, "stock", "bullish", 80, False, 2.5, 4.0, 2, r)
assert g2["grade"] == "C" and abs(g2["predicted_r"] - (0.415 - 0.134 - 0.007 - 0.247)) < 1e-9, g2
assert grade_for(M, "stock", "bearish", -50, True, 0, 1.0, 1, r)["grade"] == "Avoid"
assert grade_for(M, "fx", "bullish", 45, True, 0, 1.0, 0, r)["parts"][2]["value"] == "n/a"
assert grade_for({}, "stock", "bullish", 45, True, 0, 1.0, 0, r)["grade"] is None
part = grade_for(M, "stock", "bullish", 45, True, 0.0, None, 0, r, only={"backdrop", "freshness"})
assert [p["factor"] for p in part["parts"]] == ["history", "baseline", "backdrop", "freshness"]
assert backdrop_for("stock", False, r)[0] == "against" and backdrop_for("crypto", False, r)[0] == "with" and backdrop_for("fx", True, r)[0] == "n/a"

# ---------------------------------------------------------------- lifecycle
A = D["assets"][1]
S = {"symbol": "AAPL", "status": "ok", "as_of": "2026-11-10", "price": 110.0, "atr": 2.0, "direction": "bullish", "score": 60.0,
     "zone": {"lo": 104.0, "hi": 106.0, "basis": "Support at 105 (2 touches, last 2026-10-01)", "in_zone": False, "dist_atr": 2.0, "anchor_touches": 2},
     "signal_break": 102.5, "reward_risk": 2.0, "resistances": [{"price": 114.0}, {"price": 118.0}], "supports": [{"price": 105.0}], "high_52w": 118.0, "low_52w": 70.0}
TODAY = "2026-11-11"
s = swing_signal(S, A, None, M, r, {}, {}, {}, TODAY)
assert s["state"] == "WATCHING" and s["chasing"] and s["entry"]["price"] == 106.0 and s["stop"] == 102.5 and s["distance"]["atr"] == 2.0, s
assert [t["price"] for t in s["targets"]] == [114.0, 118.0] and s["targets"][0]["rr"] == round(8 / 3.5, 2) and s["direction"] == "long"
near = dict(S, price=107.0); assert swing_signal(near, A, None, M, r, {}, {}, {}, TODAY)["state"] == "APPROACHING ENTRY"
weak = dict(S, score=30.0); w = swing_signal(weak, A, None, M, r, {}, {}, {}, TODAY); assert w["state"] == "WATCHING" and w["grade"] is None
E = {"id": "AAPL-2026-11-05", "symbol": "AAPL", "asset_class": "stock", "direction": "bullish", "signal_date": "2026-11-05", "score": 60.0,
     "zone": {"lo": 104.0, "hi": 106.0}, "signal_break": 102.5, "status": "pending", "grade": "A", "predicted_r": 0.33, "grade_parts": []}
p = swing_signal(S, A, E, M, r, {}, {}, {}, TODAY); assert p["state"] == "WATCHING" and p["grade"] == "A" and p["grade_basis"] == "when logged"
o = swing_signal(S, A, dict(E, status="open", entry=106.0, fill_date="2026-11-06", r=0.8), M, r, {}, {}, {}, TODAY)
assert o["state"] == "ENTRY TRIGGERED" and o["distance"] is None and not o["chasing"]
x = swing_signal(S, A, dict(E, status="loss", entry=106.0, exit_date="2026-11-10", exit_reason="stop", r=-1.02), M, r, {}, {}, {}, TODAY)
assert x["state"] == "INVALIDATED" and x["outcome"]["r"] == -1.02
f = swing_signal(S, A, dict(E, status="win", entry=106.0, exit_date="2026-11-10", exit_reason="signal faded", r=2.1), M, r, {}, {}, {}, TODAY)
assert f["state"] == "EXPIRED"
u = swing_signal(S, A, dict(E, status="unfilled", checked_through="2026-11-10"), M, r, {}, {}, {}, TODAY); assert u["state"] == "EXPIRED"
assert swing_signal(S, A, dict(E, status="loss", exit_date="2026-10-20", exit_reason="stop", r=-1), M, r, {}, {}, {}, TODAY) is None   # old news drops off
old = dict(E); old.pop("grade"); old.pop("predicted_r")
assert "partial" in swing_signal(S, A, dict(old, status="open", entry=106.0, fill_date="2026-11-06", r=0.1), M, r, {}, {}, {}, TODAY)["grade_basis"]
ev = swing_signal(S, A, None, M, r, {}, {"earnings": [{"symbol": "AAPL", "date": "2026-11-12", "when": "after close"}], "macro_events": [{"date": "2026-12-25", "event": "far"}]}, {}, TODAY)
assert len(ev["events"]) == 1 and any("earnings" in k for k in ev["risks"])
short = swing_signal(dict(S, direction="bearish", score=-60.0, zone=dict(S["zone"], lo=112.0, hi=114.0), signal_break=115.5), dict(A, score=-60.0), None, M, r, {}, {}, {}, TODAY)
assert short["direction"] == "short" and short["entry"]["price"] == 112.0 and short["grade"] == "Avoid" and short["targets"][0]["price"] == 105.0

P = {"symbol": "BTC", "asset_class": "crypto", "bias": "bearish", "status": "waiting for entry", "entry": 100.0, "stop": 100.3, "score": -30.0, "session_date": TODAY}
i = intraday_signal(P, D["assets"][4], r)
assert i["state"] == "APPROACHING ENTRY" and i["grade"] is None and i["entry"]["type"] == "stop" and any("Narrow range" in k for k in i["risks"])
assert intraday_signal(dict(P, status="stopped", r=-1.2), D["assets"][4], r)["state"] == "INVALIDATED"
assert intraday_signal(dict(P, bias=None), D["assets"][4], r) is None

sigs = [dict(o, symbol="SPY", cluster="US stocks"), dict(o, symbol="QQQ", cluster="US stocks")]
pf = portfolio(sigs); assert pf["open_trades"] == 2 and pf["crowded"][0]["symbols"] == ["QQQ", "SPY"] and pf["risk_if_all_stops_hit_from_here_r"] == 3.6
b = briefing([s], r, portfolio([s])); assert b["headline"] == "No A-grade setup right now" and b["no_trade_reasons"]

SET = {"assets": [S]}; SC = {"entries": [dict(E, status="open", entry=106.0, fill_date="2026-11-06", r=0.5)]}
out1 = plans_build(D, SET, {"entries": [E]}, r, M, {}, {"plans": [P]}, {}, {}, {})
out2 = plans_build(D, SET, SC, r, M, {}, {"plans": [dict(P, status="in trade", r=0.4)]}, {}, {}, out1)
assert {(t["symbol"], t["from"], t["to"]) for t in out2["transitions"]} == {("AAPL", "WATCHING", "ENTRY TRIGGERED"), ("BTC", "APPROACHING ENTRY", "ENTRY TRIGGERED")}
assert plans_build(D, SET, SC, r, M, {}, {}, {}, {}, out2)["transitions"] == []     # nothing changed: no repeat notification
assert out2["signals"][0]["state"] == "ENTRY TRIGGERED" and sum(out2["counts"].values()) == len(out2["signals"])
first = plans_build(D, SET, SC, r, M, {}, {}, {}, {}, {})              # first ever run: an already-open trade is dated from its fill
assert first["signals"][0]["state_since"] == "2026-11-06T00:00:00Z" and first["transitions"] == [], first["signals"][0]["state_since"]

# ---------------------------------------------------------------- analytics
b = block([{"r": 2.0, "date": "2026-01-01", "days": 10}, {"r": -1.0, "date": "2026-01-02", "days": 2}, {"r": -1.0, "date": "2026-01-03", "days": 1}, {"r": 3.0, "date": "2026-01-04", "days": 20}])
assert b["closed"] == 4 and b["win_rate"] == 0.5 and b["expectancy_r"] == 0.75 and b["profit_factor"] == 2.5 and b["total_r"] == 3.0
assert b["max_drawdown_r"] == -2.0 and b["avg_win_r"] == 2.5 and b["avg_loss_r"] == -1.0 and b["avg_hold_days"] == 8.2 and b["reliability"] == "too few to conclude"
assert block([])["closed"] == 0 and boot_ci([1, 2]) is None and boot_ci([1.0] * 10) == [1.0, 1.0]
assert boot_ci([-1, -1, 3, -1, 2, -1, 4]) == boot_ci([-1, -1, 3, -1, 2, -1, 4])            # deterministic
lo, hi = wilson(0, 12); assert lo == 0.0 and 0.15 < hi < 0.2
SCX = {"started": "2026-11-02", "entries": [
    {"symbol": "A", "asset_class": "stock", "direction": "bullish", "status": "loss", "r": -1.0, "fill_date": "2026-11-03", "exit_date": "2026-11-03", "exit_reason": "stop", "grade": "A", "regime": {"trend": "Sideways", "overlay": None}, "bars_held": 1, "mfe_r": 0.2},
    {"symbol": "B", "asset_class": "fx", "direction": "bearish", "status": "win", "r": 2.0, "fill_date": "2026-11-03", "exit_date": "2026-11-09", "exit_reason": "signal faded"},
    {"symbol": "C", "asset_class": "stock", "direction": "bullish", "status": "open", "r": 1.5, "fill_date": "2026-11-04"},
    {"symbol": "D", "asset_class": "stock", "direction": "bullish", "status": "pending"}]}
sw = a_swing(SCX)
assert sw["closed"]["closed"] == 2 and sw["open"] == {"count": 1, "marked_r": 1.5, "in_profit": 1} and sw["closed_plus_open_r"] == 2.5
assert sw["by_grade"]["A"]["closed"] == 1 and sw["by_grade"]["not recorded"]["closed"] == 1 and sw["by_regime"]["Sideways"]["closed"] == 1
assert sw["by_direction"]["short"]["expectancy_r"] == 2.0 and sw["entry_timing"] == {"stopped": 1, "stopped_within_2_bars": 1, "stopped_never_reached_plus_half_r": 1, "stopped_with_excursion_data": 1}
IT = {"history": [{"symbol": "BTC", "session_date": "2026-11-02", "bias": "bearish", "r": 3.0}, {"symbol": "ETH", "session_date": "2026-11-02", "bias": "bearish", "r": -1.1},
                  {"symbol": "BTC", "session_date": "2026-11-12", "bias": "bearish", "r": -1.2, "bias_rule": "prev_close"}],
      "shadow": {"version": "v2", "min_sessions": 100, "history": [{"symbol": "BTC", "session_date": "2026-11-12", "bias": "bearish", "r": 0.4}]}}
ia = a_intraday(IT)
assert ia["closed"]["closed"] == 3 and ia["sessions"] == 2 and ia["since_bias_fix"]["closed"] == 1 and ia["before_bias_fix"]["closed"] == 2
assert ia["shadow"]["closed"]["expectancy_r"] == 0.4 and ia["shadow"]["same_sessions_v1"]["expectancy_r"] == -1.2
full = a_build(SCX, IT, {"x": 1}); assert full["baseline"] == {"x": 1} and len(full["questions"]) >= 5 and json.dumps(full)
assert a_build({}, {}, None)["swing"]["closed"]["closed"] == 0

# ---------------------------------------------------------------- scorecard additions
idx = pd.date_range("2026-11-03", periods=4, freq="B")
bars = pd.DataFrame({"open": [100, 101, 103, 102], "high": [102, 104, 106, 103], "low": [99, 100, 101, 98], "close": [101, 103, 102, 99]}, index=idx)
ex = excursions({"direction": "bullish", "entry": 100.0, "signal_break": 98.0, "fill_date": "2026-11-03", "exit_date": "2026-11-05"}, bars)
assert ex == {"mfe_r": 3.0, "mae_r": -0.5, "bars_held": 3}, ex
ex = excursions({"direction": "bearish", "entry": 100.0, "signal_break": 104.0, "fill_date": "2026-11-04"}, bars)
assert ex == {"mfe_r": 0.5, "mae_r": -1.5, "bars_held": 3}, ex
assert excursions({"direction": "bullish", "entry": None}, bars) == {}
# a stop exit: the exit bar's high is not counted (it may have come after the stop); planned risk comes from the zone edge
ex = excursions({"direction": "bullish", "entry": 100.0, "zone": {"lo": 99.0, "hi": 100.0}, "signal_break": 98.0, "fill_date": "2026-11-03",
                 "exit_date": "2026-11-06", "exit": 98.0, "exit_reason": "stop"}, bars)
assert ex == {"mfe_r": 3.0, "mae_r": -1.0, "bars_held": 4}, ex
# a gap fill near the stop does not inflate the figures: risk is still zone edge to stop (2.0), not entry to stop (0.5)
ex = excursions({"direction": "bullish", "entry": 98.5, "zone": {"lo": 99.0, "hi": 100.0}, "signal_break": 98.0, "fill_date": "2026-11-04"}, bars)
assert ex["mfe_r"] == round((106 - 98.5) / 2, 2), ex
# filled and stopped in the same bar: no measurable best point
ex = excursions({"direction": "bullish", "entry": 100.0, "zone": {"lo": 99.0, "hi": 100.0}, "signal_break": 98.5, "fill_date": "2026-11-06",
                 "exit_date": "2026-11-06", "exit": 98.5, "exit_reason": "stop"}, bars)
assert ex == {"mfe_r": None, "mae_r": -1.0, "bars_held": 1}, ex
ne = new_entries({"assets": [A]}, {"assets": [S]}, [], r, M)
assert len(ne) == 1 and ne[0]["grade"] in ("A+", "A", "B", "C", "Avoid") and ne[0]["regime"]["trend"] == "Strong bullish" and ne[0]["version"] == "swing-v1" and ne[0]["setup_type"] == "Pullback to support"
legacy = new_entries({"assets": [A]}, {"assets": [S]}, []); assert "grade" not in legacy[0] and legacy[0]["zone"] == {"lo": 104.0, "hi": 106.0}
print("ALL TESTS PASSED")
