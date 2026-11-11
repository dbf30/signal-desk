"""
Signal lifecycle, trade plans and grades for Signal Desk.

Usage:  python3 plans.py --data data.json --setups setups.json --scorecard scorecard.json --regime regime.json
                         --model grade_model.json [--stats setup_stats.json] [--intraday intraday.json]
                         [--catalysts catalysts.json] [--news news.json] [--prev signals.json] --out signals.json

Nothing here changes a trading rule. Entries, stops and exits are still the tested ones in trades.py and
intraday.py; this module describes each signal's state, lays the plan out in full, and grades it.

States
  WATCHING           a setup is forming, or its limit order is resting more than 1 daily range from price
  APPROACHING ENTRY  the order is live and price is within 1 daily range of it
  ENTRY TRIGGERED    the order filled; the trade is open
  INVALIDATED        the stop (signal-break level) was hit
  EXPIRED            the order was never filled in 10 bars, or the trade ended because the signal faded / timed out

Grade (swing only). Predicted R per trade from grade_model.json: the asset-class x direction average on
2010-2022 (shrunk toward zero) plus five effects fitted together on what was left over, each halved:
backdrop, location, freshness, overhead, anchor. A+ >= 0.50R, A >= 0.30R, B >= 0.12R, C >= 0, else Avoid.
A grade is a ranking from history, not a probability that a trade wins. Most of a grade comes from WHICH market
and direction it is: on later data nearly every A+ was a bullish crypto or bullish stock setup.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

STATES = ["ENTRY TRIGGERED", "APPROACHING ENTRY", "WATCHING", "INVALIDATED", "EXPIRED"]
MIN_SCORE_SHOW = 25          # developing setups below this are not listed
APPROACH_ATR = 1.0
CHASE_ATR = 1.0
RECENT_DAYS = 5              # closed signals stay on the board this many days

CLUSTER = {}
for _s in ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "US500", "NAS100", "US30", "US2000"]: CLUSTER[_s] = "US stocks"
for _s in ["GER40", "UK100"]: CLUSTER[_s] = "European stocks"
for _s in ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]: CLUSTER[_s] = "US dollar"
for _s in ["ZT", "ZF", "ZN", "ZB"]: CLUSTER[_s] = "US interest rates"
for _s in ["GOLD", "SILVER"]: CLUSTER[_s] = "Precious metals"
for _s in ["WTI", "NATGAS"]: CLUSTER[_s] = "Energy"
for _s in ["COPPER"]: CLUSTER[_s] = "Industrial metals"
for _s in ["CORN", "WHEAT", "SOYBEAN"]: CLUSTER[_s] = "Grains"
for _s in ["BTC", "ETH", "SOL", "XRP"]: CLUSTER[_s] = "Crypto"

FACTOR_TEXT = {
    ("backdrop", "with"): "The wider market backs this trade ({what} is {dir} its 200-day average).",
    ("backdrop", "against"): "The wider market is against this trade ({what} is {dir} its 200-day average).",
    ("location", "in zone"): "Price is inside the entry zone now.",
    ("location", "within 2 ATR"): "Price is outside the entry zone; the order has to wait for a pullback.",
    ("location", "beyond 2 ATR"): "Price is more than 2 daily ranges from the zone. These entries did worst in testing.",
    ("freshness", "score 40-55"): "The signal is fresh (score 40-55). Fresh signals did better than long-running ones.",
    ("freshness", "score 55+"): "The score is already 55 or more. Late entries into a mature move did worse.",
    ("overhead", "close"): "The next level is close. In testing that did not hurt: strong trends run through nearby levels.",
    ("overhead", "none ahead"): "No level ahead in the last year (at 1-year extremes).",
    ("overhead", "far"): "A long way to the next level. Counter to the usual rule of thumb, these did worse in testing.",
    ("anchor", "no level"): "No nearby level to lean on, so the zone is a plain 0.75-1.5 ATR pullback. These did best in testing.",
    ("anchor", "level"): "The zone sits on a tested support/resistance level.",
}


def _load(path):
    if not path:
        return {}
    try:
        return json.load(open(path))
    except Exception:
        return {}


def backdrop_for(asset_class: str, bull: bool, regime: dict) -> tuple[str, str | None, str | None]:
    """('with' | 'against' | 'n/a', benchmark name, 'above'/'below')."""
    b = (regime or {}).get("backdrop") or {}
    key, what = ("equity", "the S&P 500") if asset_class in ("stock", "index") else ("crypto", "Bitcoin") if asset_class == "crypto" else (None, None)
    if not key or b.get(key) not in ("up", "down"):
        return "n/a", None, None
    up = b[key] == "up"
    return ("with" if up == bull else "against"), what, ("above" if up else "below")


def grade_for(model: dict, asset_class: str, direction: str, score: float, in_zone: bool, dist_atr: float,
              rr, anchor_touches: int, regime: dict, only: set | None = None) -> dict:
    """Predicted R and grade for one swing setup, with every part of the sum shown.
    only: if given, the factors that are known; the others are left out of the sum (used for old log entries)."""
    if not model or "groups" not in model:
        return {"grade": None, "predicted_r": None, "parts": [], "note": "No grade model available."}
    bull = direction == "bullish"
    group = f"{asset_class}:{direction}"
    bd, what, dirn = backdrop_for(asset_class, bull, regime)
    levels = {
        "backdrop": bd,
        "location": "in zone" if in_zone else "within 2 ATR" if (dist_atr or 0) <= 2 else "beyond 2 ATR",
        "freshness": "score 40-55" if abs(score) < 55 else "score 55+",
        "overhead": "none ahead" if rr is None else "close" if rr < 1.5 else "far",
        "anchor": "no level" if not anchor_touches else "level",
    }
    gbase, icpt = float(model["groups"].get(group, 0.0)), float(model.get("intercept", 0.0))
    n = (model.get("group_n") or {}).get(group)
    raw = (model.get("group_raw") or {}).get(group, 0)
    parts = [{"factor": "history", "value": group, "effect": round(gbase, 3),
              "text": f"{'Bullish' if bull else 'Bearish'} setups in this asset class averaged {raw:+.2f}R on 2010-2022"
                      + (f" ({n} trades)" if n else "") + f"; counted as {gbase:+.2f}R after allowing for the small sample."},
             {"factor": "baseline", "value": "typical setup", "effect": round(icpt, 3),
              "text": "Starting point for a setup with none of the helpful features below (most setups have none)."}]
    pred = gbase + icpt
    for f, lv in levels.items():
        if only is not None and f not in only:
            continue
        eff = float((model["factors"].get(f) or {}).get(lv, 0.0))
        pred += eff
        txt = FACTOR_TEXT.get((f, lv), "")
        if f == "backdrop":
            txt = txt.format(what=what, dir=dirn) if what else "No market backdrop is used for this asset class."
        parts.append({"factor": f, "value": lv, "effect": round(eff, 3), "text": txt})
    cuts = model.get("cuts", {"A+": 0.5, "A": 0.3, "B": 0.12, "C": 0.0})
    g = "A+" if pred >= cuts["A+"] else "A" if pred >= cuts["A"] else "B" if pred >= cuts["B"] else "C" if pred >= cuts["C"] else "Avoid"
    return {"grade": g, "predicted_r": round(pred, 3), "parts": parts, "group": group}


def setup_type(bull: bool, anchor_touches) -> str:
    if anchor_touches is None:
        return "Pullback entry" if bull else "Bounce entry"
    if anchor_touches:
        return "Pullback to support" if bull else "Bounce to resistance"
    return "Pullback in trend (no nearby level)" if bull else "Bounce in downtrend (no nearby level)"


def _events_for(sym: str, cls: str, cat: dict, today: str, days: int = 3) -> list[dict]:
    out = []

    def near(d):
        return isinstance(d, str) and today <= d[:10] <= _plus(today, days)
    for e in cat.get("earnings", []) or []:
        if e.get("symbol") == sym and near(e.get("date")):
            out.append({"date": e["date"], "title": f"{sym} earnings ({e.get('when') or 'time not given'})", "kind": "earnings", "source": e.get("source")})
    if cls != "crypto":
        for e in cat.get("macro_events", []) or []:
            if near(e.get("date")):
                out.append({"date": e["date"], "time_uk": e.get("time_uk"), "title": e.get("event"), "kind": "macro", "source": e.get("source")})
    for e in cat.get("commodity_events", []) or []:
        if sym in (e.get("affects") or []) and near(e.get("date")):
            out.append({"date": e["date"], "time_uk": e.get("time_uk"), "title": e.get("event"), "kind": "commodity", "source": e.get("source")})
    for e in cat.get("unlocks", []) or []:
        if cls == "crypto" and str(e.get("token", "")).upper().startswith(sym) and near(e.get("date")):
            out.append({"date": e["date"], "title": f"{sym} token unlock: {e.get('detail', '')}"[:140], "kind": "unlock", "source": e.get("source")})
    return sorted(out, key=lambda e: (e["date"], e.get("time_uk") or ""))[:4]


def _plus(day: str, n: int) -> str:
    from datetime import date, timedelta
    y, m, d = (int(x) for x in day[:10].split("-"))
    return str(date(y, m, d) + timedelta(days=n))


def _days_between(a: str, b: str) -> int:
    from datetime import date
    pa, pb = (date(*(int(x) for x in s[:10].split("-"))) for s in (a, b))
    return (pb - pa).days


def swing_signal(s: dict, a: dict, entry: dict | None, model: dict, regime: dict, stats: dict, cat: dict, news: dict, today: str) -> dict | None:
    """s: today's row from setups.json; a: the asset row from data.json; entry: its scorecard entry, if any."""
    bull_now = s.get("direction") == "bullish"
    active = entry is not None and entry.get("status") in ("pending", "open")
    closed = entry is not None and entry.get("status") in ("win", "loss", "unfilled")
    direction = entry["direction"] if entry else s.get("direction")
    if direction is None:
        return None
    bull = direction == "bullish"
    price, atr = s["price"], s["atr"]
    z = s.get("zone") or {}
    if entry:                                   # a logged signal keeps the levels it was logged with
        lo, hi, stop = entry["zone"]["lo"], entry["zone"]["hi"], entry["signal_break"]
        basis = z.get("basis") if (z and abs((z.get("lo") or 0) - lo) < 1e-9) else "Levels fixed when the signal was logged on " + entry["signal_date"]
    elif z:
        lo, hi, stop, basis = z["lo"], z["hi"], s["signal_break"], z.get("basis")
    else:
        return None
    limit = hi if bull else lo
    risk = (limit - stop) if bull else (stop - limit)
    if not risk or risk <= 0:
        return None
    sgn = 1 if bull else -1
    in_zone = lo <= price <= hi
    gap_atr = round(sgn * (price - limit) / atr, 2)          # > 0: price still has to come back to the order
    dist = {"atr": 0.0 if in_zone else abs(gap_atr), "pct": round(100 * abs(price - limit) / price, 2),
            "side": "in zone" if in_zone else ("needs a pullback" if gap_atr > 0 else "through the zone")}

    # ---- state
    outcome = None
    if entry and entry.get("status") == "open":
        state = "ENTRY TRIGGERED"
        why = f"Filled at {entry['entry']:.6g} on {entry.get('fill_date')}. Marked at {entry.get('r', 0):+.2f}R."
    elif entry and entry.get("status") == "pending":
        state = "APPROACHING ENTRY" if dist["atr"] <= APPROACH_ATR else "WATCHING"
        why = (f"Limit order at {limit:.6g} is live" + (", price is in the zone." if in_zone else f", price is {dist['atr']} daily range{'s' if dist['atr'] != 1 else ''} away.")
               + f" Valid for 10 bars from {entry['signal_date']}.")
    elif closed:
        ref = entry.get("exit_date") or entry.get("checked_through") or entry["signal_date"]
        if _days_between(ref, today) > RECENT_DAYS:
            return None
        if entry["status"] == "unfilled":
            state, why = "EXPIRED", "Price never reached the entry zone within 10 bars."
        elif str(entry.get("exit_reason", "")).startswith("stop") or entry.get("exit_reason") == "opened beyond stop":
            state, why = "INVALIDATED", f"Stop hit on {entry.get('exit_date')}: {entry.get('r', 0):+.2f}R."
        else:
            state, why = "EXPIRED", f"Closed on {entry.get('exit_date')} ({entry.get('exit_reason')}): {entry.get('r', 0):+.2f}R."
        outcome = {"r": entry.get("r"), "exit_reason": entry.get("exit_reason"), "exit_date": entry.get("exit_date")}
    else:
        strong = abs(s.get("score") or 0) >= 40
        if strong:
            state = "APPROACHING ENTRY" if dist["atr"] <= APPROACH_ATR else "WATCHING"
            why = "New signal. The order is logged at the next US close and is live from the following bar."
        else:
            state = "WATCHING"
            why = f"Developing: score {s['score']:+.0f}. A setup needs {'+40 or more' if bull else '-40 or less'}."

    # ---- grade: the one stamped when logged, otherwise today's reading
    if entry and entry.get("grade"):
        g = {"grade": entry["grade"], "predicted_r": entry.get("predicted_r"), "parts": entry.get("grade_parts") or [], "basis": "when logged"}
    elif not entry and abs(s.get("score") or 0) < 40:
        g = {"grade": None, "predicted_r": None, "parts": [], "basis": "not graded until the score reaches 40"}
    else:
        if entry:   # logged before grades existed: only what is known about the signal day is used
            g = grade_for(model, a["asset_class"], direction, entry["score"], False, 1.0, 2.0, 1, regime, only={"backdrop", "freshness"})
            g["basis"] = "partial: logged before grades existed, so only history, backdrop and score band count"
        else:
            g = grade_for(model, a["asset_class"], direction, s["score"], in_zone, dist["atr"], s.get("reward_risk"),
                          z.get("anchor_touches", 1), regime)
            g["basis"] = "today's reading; fixed when the signal is logged at the US close"

    # ---- reference targets: the next two levels in the trade's direction (no fixed target is part of the tested rules)
    lv = sorted([l["price"] for l in (s.get("resistances") if bull else s.get("supports")) or [] if sgn * (l["price"] - limit) > 0.25 * atr],
                key=lambda p: sgn * p)
    ext = s.get("high_52w") if bull else s.get("low_52w")
    if ext is not None and sgn * (ext - limit) > 0.25 * atr and all(abs(ext - p) > 0.25 * atr for p in lv):
        lv.append(ext); lv.sort(key=lambda p: sgn * p)
    targets = [{"price": p, "rr": round(abs(p - limit) / risk, 2), "basis": ("next " if i == 0 else "second ") + ("resistance" if bull else "support")
                + (" (1-year extreme)" if p == ext else "")} for i, p in enumerate(lv[:2])]

    group = f"{a['asset_class']}:{direction}"
    hold = ((stats.get("groups") or {}).get(group) or {}).get("hold") or {}
    strengths = [p["text"] for p in g["parts"] if p["effect"] > 0.02 and p["text"] and p["factor"] != "baseline"]
    weaknesses = [p["text"] for p in g["parts"] if p["effect"] < -0.02 and p["text"] and p["factor"] != "baseline"]
    risks = list(a.get("flags") or [])
    chase = (not in_zone) and gap_atr > CHASE_ATR and state in ("WATCHING", "APPROACHING ENTRY")
    if chase:
        risks.insert(0, f"Price is {gap_atr:.1f} daily ranges {'above' if bull else 'below'} the entry zone. Entering here is chasing: the tested entry is the limit order in the zone, and entries far from it did worst.")
    if entry and active and (a.get("score") is not None) and sgn * a["score"] < 15:
        risks.insert(0, f"The score has faded to {a['score']:+.0f} since the signal. An open trade exits at the next open; a resting order is still live under the tested rules.")
    ov = (regime or {}).get("overlay")
    if ov and (regime.get("policy") or {}).get("swing"):
        risks.append(f"Market regime: {ov}. {regime['policy']['swing']}")
    events = _events_for(a["symbol"], a["asset_class"], cat, today)
    for e in events:
        risks.append(f"{e['title']} on {e['date']}{(' at ' + e['time_uk'] + ' UK') if e.get('time_uk') else ''}: prices can jump straight through levels.")
    nb = (news.get("by_symbol") or {}).get(a["symbol"])
    return {
        "id": entry["id"] if entry else f"{a['symbol']}-forming", "symbol": a["symbol"], "name": a.get("name"), "asset_class": a["asset_class"],
        "cluster": CLUSTER.get(a["symbol"], a["asset_class"]), "strategy": "swing", "version": (entry or {}).get("version") or "swing-v1",
        "direction": "long" if bull else "short",
        "setup_type": (entry or {}).get("setup_type") or setup_type(bull, z.get("anchor_touches") if (z and not entry) else None),
        "state": state, "state_reason": why, "outcome": outcome,
        "price": price, "price_as_of": s.get("as_of"), "score": a.get("score"), "label": a.get("label"),
        "signal_date": (entry or {}).get("signal_date"),
        "entry_zone": {"lo": lo, "hi": hi, "basis": basis}, "entry": {"type": "limit", "price": limit,
                                                                     "trigger": f"Fills when price trades {'down' if bull else 'up'} to {limit:.6g}. A bar that opens through it fills at the open."},
        "distance": dist if state in ("WATCHING", "APPROACHING ENTRY") else None, "chasing": bool(chase),
        "stop": stop, "invalidation": f"A trade through {stop:.6g} ends the trade (0.75 daily ranges beyond the far edge of the zone).",
        "risk_per_unit": round(risk, 6), "targets": targets,
        "exit_rule": f"Tested exit: the next open after the score closes {'below +15' if bull else 'above -15'}, or after 60 bars. No fixed target: in testing, taking profit at the next level removed the edge.",
        "hold": {"loser_median_bars": hold.get("loser_median_bars"), "winner_median_bars": hold.get("winner_median_bars")},
        "grade": g["grade"], "predicted_r": g["predicted_r"], "grade_basis": g.get("basis"), "grade_parts": g["parts"],
        "strengths": strengths, "weaknesses": weaknesses, "risks": risks[:8], "events": events,
        "news": nb["top"] if nb else None,
        "trade": None if not entry else {k: entry.get(k) for k in ("status", "entry", "fill_date", "r", "mfe_r", "mae_r", "exit", "exit_date", "exit_reason")},
        "atr": atr,
    }


INTRA_STATE = {"waiting for session open": "WATCHING", "range forming": "WATCHING", "waiting for entry": "APPROACHING ENTRY",
               "in trade": "ENTRY TRIGGERED", "stopped": "INVALIDATED", "closed at session end": "EXPIRED", "no fill": "EXPIRED",
               "target hit": "EXPIRED"}


def intraday_signal(p: dict, a: dict, regime: dict) -> dict | None:
    if not p.get("bias"):
        return None
    bull = p["bias"] == "bullish"
    st = INTRA_STATE.get(p.get("status"), "WATCHING")
    e, s = p.get("entry"), p.get("stop")
    risks = ["Four coins usually move together: taking all of them is close to one position four times the size."]
    if e and s and a.get("price"):
        cost_share = 0.0008 * e / abs(e - s) if e != s else None
        if cost_share and cost_share > 0.2:
            risks.insert(0, f"Narrow range: trading costs are about {round(100 * cost_share)}% of the risk on this trade.")
    ov = (regime or {}).get("overlay")
    if ov and (regime.get("policy") or {}).get("intraday"):
        risks.append(f"Market regime: {ov}. {regime['policy']['intraday']}")
    return {
        "id": f"{p['symbol']}-intraday-{p['session_date']}", "symbol": p["symbol"], "name": a.get("name"), "asset_class": p["asset_class"],
        "cluster": CLUSTER.get(p["symbol"], "Crypto"), "strategy": "intraday", "version": p.get("version") or "intraday-v1",
        "direction": "long" if bull else "short", "setup_type": "London range breakout",
        "state": st, "state_reason": {"WATCHING": "The 08:00-09:00 UK range is still forming.", "APPROACHING ENTRY": "Stop order is live at the edge of the 08:00-09:00 UK range.",
                                      "ENTRY TRIGGERED": f"Filled. Marked at {p.get('r') or 0:+.2f}R. Exit at 20:00 UK.",
                                      "INVALIDATED": f"Stopped out: {p.get('r') or 0:+.2f}R.", "EXPIRED": f"Session over: {p.get('status')}" + (f", {p['r']:+.2f}R." if p.get("r") is not None else ".")}[st],
        "outcome": {"r": p.get("r"), "exit_reason": p.get("status")} if st in ("INVALIDATED", "EXPIRED") else None,
        "price": a.get("price"), "price_as_of": a.get("as_of"), "score": p.get("score"), "label": a.get("label"), "signal_date": p["session_date"],
        "entry_zone": None, "entry": {"type": "stop", "price": e, "trigger": f"Stop order at the {'high' if bull else 'low'} of the 08:00-09:00 UK hourly bar, live from 09:00 UK."},
        "distance": None, "chasing": False, "stop": s, "invalidation": "The other side of the 08:00-09:00 UK range.",
        "targets": [], "exit_rule": "Tested exit: 20:00 UK the same day. No target.",
        "hold": {"session": "09:00-20:00 UK"},
        "grade": None, "predicted_r": None, "grade_basis": "One rule, tested as a whole: about +0.08R a trade on later data and other coins. Not graded.",
        "grade_parts": [], "strengths": [f"Daily score {p.get('score'):+.0f} at the previous close sets the direction."], "weaknesses": [],
        "risks": risks, "events": [], "news": None,
        "trade": {"status": p.get("status"), "entry": e, "r": p.get("r")}, "shadow": p.get("shadow"), "atr": p.get("atr"),
    }


def portfolio(signals: list[dict]) -> dict:
    live = [s for s in signals if s["state"] in ("ENTRY TRIGGERED", "APPROACHING ENTRY") and s["strategy"] == "swing"]
    open_ = [s for s in live if s["state"] == "ENTRY TRIGGERED"]
    by = {}
    for s in live:
        by.setdefault((s["cluster"], s["direction"]), []).append(s["symbol"])
    crowded = [{"cluster": c, "direction": d, "symbols": sorted(v)} for (c, d), v in sorted(by.items()) if len(v) >= 2]
    giveback = sum(max(0.0, (s["trade"] or {}).get("r") or 0.0) + 1.0 for s in open_)
    notes = [f"{len(x['symbols'])} {x['direction']} signals in {x['cluster']} ({', '.join(x['symbols'])}): they tend to win and lose together, so treat them as one position when sizing."
             for x in crowded]
    return {"open_trades": len(open_), "orders_near_entry": len(live) - len(open_),
            "initial_risk_r": float(len(open_)), "risk_if_all_stops_hit_from_here_r": round(giveback, 2),
            "crowded": crowded, "notes": notes,
            "sizing": "Set risk per trade and the maximum number of open trades in the Funded account tab. Nothing here assumes an account size."}


def briefing(signals: list[dict], regime: dict, port: dict) -> dict:
    sw = [s for s in signals if s["strategy"] == "swing"]
    live = [s for s in sw if s["state"] in ("APPROACHING ENTRY", "WATCHING") and s["grade"]]
    good = [s for s in live if s["grade"] in ("A+", "A")]
    lines = []
    if regime.get("label"):
        lines.append(f"Market regime: {regime['label']}" + (f" on top of a {regime['trend'].lower()} trend" if regime.get("overlay") and regime.get("trend") else "") + ".")
    c = {st: sum(1 for s in signals if s["state"] == st) for st in STATES}
    lines.append(f"{c['ENTRY TRIGGERED']} open, {c['APPROACHING ENTRY']} approaching entry, {c['WATCHING']} watching, {c['INVALIDATED']} invalidated and {c['EXPIRED']} expired in the last {RECENT_DAYS} days.")
    if good:
        best = sorted(good, key=lambda s: -(s["predicted_r"] or 0))[:3]
        lines.append("Best-graded setups not yet filled: " + ", ".join(f"{s['symbol']} {s['direction']} ({s['grade']})" for s in best) + ".")
    reasons = []
    if not good:
        if not live:
            reasons.append("No setup with a score of 40 or more is waiting for an entry.")
        else:
            short = [s for s in live if s["direction"] == "short"]
            if short:
                reasons.append(f"{len(short)} of {len(live)} waiting setups are bearish. Bearish setups lost money in every asset class in testing, so none grades above C.")
            weak = [s for s in live if s["direction"] == "long"]
            if weak:
                reasons.append(f"{len(weak)} bullish setup{'s' if len(weak) != 1 else ''} ({', '.join(s['symbol'] for s in weak[:5])}) grade B or lower: their asset class has little or no measured edge, or the entry is poorly placed.")
        lines.append("No A-grade setup is waiting. That is a normal result: about half of all setups grade Avoid.")
    for n in port.get("notes", [])[:2]:
        lines.append(n)
    return {"headline": (f"{len(good)} A-grade setup{'s' if len(good) != 1 else ''} waiting" if good else "No A-grade setup right now"),
            "lines": lines, "no_trade_reasons": reasons}


def build(data, setups, scorecard, regime, model, stats, intraday, cat, news, prev) -> dict:
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    rows = {a["symbol"]: a for a in data.get("assets", []) if a.get("status") == "ok"}
    latest = {}
    for e in scorecard.get("entries", []):
        cur = latest.get(e["symbol"])
        act = e.get("status") in ("pending", "open")
        if cur is None or act or (cur.get("status") not in ("pending", "open") and e["signal_date"] >= cur["signal_date"]):
            if cur is None or not (cur.get("status") in ("pending", "open") and not act):
                latest[e["symbol"]] = e
    signals = []
    for s in setups.get("assets", []):
        a = rows.get(s.get("symbol"))
        if not a or s.get("status") != "ok":
            continue
        e = latest.get(s["symbol"])
        if e is None and (not s.get("zone") or abs(s.get("score") or 0) < MIN_SCORE_SHOW):
            continue
        sig = swing_signal(s, a, e, model, regime, stats, cat, news, today)
        if sig:
            signals.append(sig)
    for p in (intraday or {}).get("plans", []):
        a = rows.get(p.get("symbol"))
        sig = intraday_signal(p, a, regime) if a else None
        if sig:
            signals.append(sig)
    old = {s["id"]: s for s in (prev or {}).get("signals", [])}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    transitions = []
    for s in signals:
        o = old.get(s["id"])
        if o and o.get("state") == s["state"] and o.get("state_since"):
            s["state_since"] = o["state_since"]
        elif not o and s["strategy"] == "swing" and s["state"] == "ENTRY TRIGGERED" and (s.get("trade") or {}).get("fill_date"):
            s["state_since"] = s["trade"]["fill_date"] + "T00:00:00Z"       # first sight of an older open trade: date it from its fill
        elif not o and s["strategy"] == "swing" and s["state"] in ("INVALIDATED", "EXPIRED") and (s.get("outcome") or {}).get("exit_date"):
            s["state_since"] = s["outcome"]["exit_date"] + "T00:00:00Z"
        else:
            s["state_since"] = stamp
        if o and o.get("state") != s["state"]:
            transitions.append({"id": s["id"], "symbol": s["symbol"], "strategy": s["strategy"], "direction": s["direction"],
                                "from": o.get("state"), "to": s["state"], "grade": s.get("grade")})
        elif not o and prev and s["state"] in ("APPROACHING ENTRY", "ENTRY TRIGGERED"):
            transitions.append({"id": s["id"], "symbol": s["symbol"], "strategy": s["strategy"], "direction": s["direction"],
                                "from": None, "to": s["state"], "grade": s.get("grade")})
    order = {st: i for i, st in enumerate(STATES)}
    gr = {"A+": 0, "A": 1, "B": 2, "C": 3, "Avoid": 4, None: 5}
    signals.sort(key=lambda s: (order[s["state"]], gr.get(s["grade"], 5), -(abs(s.get("score") or 0))))
    port = portfolio(signals)
    return {"generated_at": stamp, "regime": {k: regime.get(k) for k in ("label", "trend", "overlay")},
            "signals": signals, "portfolio": port, "brief": briefing(signals, regime, port), "transitions": transitions,
            "counts": {st: sum(1 for s in signals if s["state"] == st) for st in STATES},
            "grade_model": {k: model.get(k) for k in ("cuts", "fitted_on")} if model else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    for k in ("data", "setups", "scorecard", "regime", "model", "out"):
        ap.add_argument("--" + k, required=k in ("data", "setups", "out"))
    for k in ("stats", "intraday", "catalysts", "news", "prev"):
        ap.add_argument("--" + k)
    a = ap.parse_args()
    out = build(json.load(open(a.data)), json.load(open(a.setups)), _load(a.scorecard), _load(a.regime), _load(a.model),
                _load(a.stats), _load(a.intraday), _load(a.catalysts), _load(a.news), _load(a.prev))
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    with open((a.out.rsplit("/", 1)[0] + "/" if "/" in a.out else "") + "transitions.txt", "w") as f:
        f.write("\n".join(f"{t['symbol']} {t['strategy']} {t['direction']}: {t['from'] or 'new'} -> {t['to']}" + (f" (grade {t['grade']})" if t.get("grade") else "")
                          for t in out["transitions"]))
    print(f"signals: {len(out['signals'])}  " + "  ".join(f"{k} {v}" for k, v in out["counts"].items()) + f"  transitions {len(out['transitions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
