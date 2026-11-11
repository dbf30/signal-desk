"""
Performance analytics for Signal Desk: what the LIVE logs show, split every useful way, with honest error bars.

Usage:  python3 analytics.py --scorecard scorecard.json --intraday intraday.json [--model grade_model.json]
                             [--baseline baseline.json] --out performance.json

Three kinds of number appear in the app and are never mixed:
  live      trades logged by the app since 2 Nov 2026 and followed with the tested rules (paper, not an account)
  backtest  the same rules on history (research/), quoted beside the live figure for comparison
  shadow    a candidate rule logged beside the live one, not yet adopted
Everything is in R: 1R = the amount risked on the trade.

Sample-size labels: under 30 closed trades "too few to conclude", 30-99 "early", 100+ "meaningful".
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone

BACKTEST = {   # from research/results (see README): what the tested rules did on data not used to choose them
    "swing": {"avg_r": 0.052, "win_rate": 0.186, "trades": 167, "set": "watchlist 2023-2026, the app's rules, max 3 open (holdout_results.json)"},
    "intraday": {"avg_r": 0.082, "win_rate": 0.258, "trades": 1157, "set": "BTC/ETH/SOL/XRP 21 Jul 2025 - 1 Nov 2026 (intraday_v2 second look A)"},
    "intraday_shadow": {"avg_r": 0.146, "win_rate": 0.337, "trades": 1157, "set": "same sessions with the 0.15 ATR stop floor"},
}


def reliability(n: int) -> str:
    return "too few to conclude" if n < 30 else "early" if n < 100 else "meaningful"


def wilson(k: int, n: int, z: float = 1.645) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def boot_ci(rs: list[float], reps: int = 2000) -> list[float] | None:
    """90% bootstrap interval for the average R. Fixed seed, so the same trades always give the same interval."""
    if len(rs) < 5:
        return None
    rng = random.Random(20261111)
    n = len(rs)
    means = sorted(sum(rs[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [round(means[int(0.05 * reps)], 3), round(means[int(0.95 * reps) - 1], 3)]


def block(trades: list[dict]) -> dict:
    """trades: [{"r": float, "date": "YYYY-MM-DD", "days": int|None}] closed trades, any order."""
    ts = sorted([t for t in trades if t.get("r") is not None], key=lambda t: t.get("date") or "")
    n = len(ts)
    if n == 0:
        return {"closed": 0, "reliability": reliability(0)}
    rs = [t["r"] for t in ts]
    w, l = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    days = [t["days"] for t in ts if t.get("days") is not None]
    return {
        "closed": n, "reliability": reliability(n),
        "win_rate": round(len(w) / n, 3), "win_rate_ci90": wilson(len(w), n),
        "avg_win_r": round(sum(w) / len(w), 3) if w else None, "avg_loss_r": round(sum(l) / len(l), 3) if l else None,
        "expectancy_r": round(sum(rs) / n, 3), "expectancy_ci90": boot_ci(rs),
        "profit_factor": round(sum(w) / abs(sum(l)), 2) if l and sum(l) != 0 else None,
        "total_r": round(sum(rs), 2), "max_drawdown_r": round(dd, 2),
        "avg_hold_days": round(sum(days) / len(days), 1) if days else None,
        "best_r": round(max(rs), 2), "worst_r": round(min(rs), 2),
    }


def split(trades: list[dict], key) -> dict:
    out: dict[str, list] = {}
    for t in trades:
        out.setdefault(str(key(t) or "not recorded"), []).append(t)
    return {k: block(v) for k, v in sorted(out.items())}


def curve(trades: list[dict]) -> list[dict]:
    pts, eq = [], 0.0
    for t in sorted([t for t in trades if t.get("r") is not None and t.get("date")], key=lambda t: t["date"]):
        eq += t["r"]
        if pts and pts[-1]["date"] == t["date"]:
            pts[-1]["r"] = round(eq, 2)
        else:
            pts.append({"date": t["date"], "r": round(eq, 2)})
    return pts


def _days(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    from datetime import date
    pa, pb = (date(*(int(x) for x in s[:10].split("-"))) for s in (a, b))
    return (pb - pa).days


def swing(sc: dict) -> dict:
    es = sc.get("entries", [])
    closed = [{"r": e["r"], "date": e.get("exit_date"), "days": _days(e.get("fill_date"), e.get("exit_date")), "e": e}
              for e in es if e.get("status") in ("win", "loss") and e.get("r") is not None]
    open_ = [e for e in es if e.get("status") == "open"]
    open_r = round(sum(e.get("r") or 0.0 for e in open_), 2)
    b = block(closed)
    stops = [t for t in closed if str(t["e"].get("exit_reason", "")).startswith(("stop", "opened"))]
    fast = [t for t in stops if (t["e"]["bars_held"] <= 2 if t["e"].get("bars_held") is not None else (t["days"] is not None and t["days"] <= 1))]
    mfe = [t["e"]["mfe_r"] for t in stops if t["e"].get("mfe_r") is not None]
    return {
        "signals_logged": len(es), "filled": sum(1 for e in es if e.get("fill_date")),
        "pending": sum(1 for e in es if e.get("status") == "pending"), "unfilled": sum(1 for e in es if e.get("status") == "unfilled"),
        "closed": b, "open": {"count": len(open_), "marked_r": open_r,
                              "in_profit": sum(1 for e in open_ if (e.get("r") or 0) > 0)},
        "closed_plus_open_r": round((b.get("total_r") or 0.0) + open_r, 2),
        "by_grade": split(closed, lambda t: t["e"].get("grade")),
        "by_setup_type": split(closed, lambda t: f"{t['e']['asset_class']} {t['e']['direction']}"),
        "by_asset_class": split(closed, lambda t: t["e"]["asset_class"]),
        "by_direction": split(closed, lambda t: "long" if t["e"]["direction"] == "bullish" else "short"),
        "by_regime": split(closed, lambda t: (t["e"].get("regime") or {}).get("overlay") or (t["e"].get("regime") or {}).get("trend")),
        "by_exit": split(closed, lambda t: t["e"].get("exit_reason")),
        "entry_timing": {"stopped": len(stops), "stopped_within_2_bars": len(fast),
                         "stopped_never_reached_plus_half_r": sum(1 for m in mfe if m < 0.5), "stopped_with_excursion_data": len(mfe)},
        "curve": curve(closed),
        "note": ("Read closed and open together. Losers close within days and winners run for weeks, so early on the closed "
                 "trades are nearly all losers: in 300 replays on 2010-2022 the closed total was negative 9 days after the "
                 "start 96% of the time, while closed plus open was positive on average."),
    }


def intraday(it: dict) -> dict:
    def rows(hs):
        return [{"r": h["r"], "date": h["session_date"], "days": 0, "h": h} for h in hs if h.get("r") is not None]
    v1 = rows(it.get("history", []))
    fixed = [t for t in v1 if t["h"].get("bias_rule") == "prev_close"]
    before = [t for t in v1 if t["h"].get("bias_rule") != "prev_close"]
    sh = rows((it.get("shadow") or {}).get("history", []))
    days = sorted({t["date"] for t in v1})
    by_day = {}
    for t in v1:
        by_day[t["date"]] = by_day.get(t["date"], 0.0) + t["r"]
    return {
        "closed": block(v1), "sessions": len(days),
        "independent_days_note": f"{len(v1)} trades came from {len(days)} sessions. The four coins move together, so treat this as about {len(days)} independent results, not {len(v1)}.",
        "since_bias_fix": block(fixed), "before_bias_fix": block(before),
        "by_coin": split(v1, lambda t: t["h"]["symbol"]),
        "by_direction": split(v1, lambda t: "long" if t["h"].get("bias") == "bullish" else "short"),
        "by_day": [{"date": d, "r": round(r, 2)} for d, r in sorted(by_day.items())],
        "shadow": {"version": (it.get("shadow") or {}).get("version"), "rule": (it.get("shadow") or {}).get("rule"),
                   "closed": block(sh), "min_sessions": (it.get("shadow") or {}).get("min_sessions"),
                   "same_sessions_v1": block([t for t in fixed if (t["h"]["symbol"], t["date"]) in {(s["h"]["symbol"], s["date"]) for s in sh}])},
        "curve": curve(v1),
    }


def questions(sw: dict, it: dict) -> list[dict]:
    def ans(q, b, text):
        return {"question": q, "answer": text, "trades": b.get("closed", 0) if isinstance(b, dict) else b}
    out = []
    g = sw["by_grade"]
    graded = {k: v for k, v in g.items() if k != "not recorded"}
    n_g = sum(v["closed"] for v in graded.values())
    out.append({"question": "Do A+ and A setups beat lower grades?", "trades": n_g,
                "answer": ("Live: no graded trade has closed yet; grades were introduced on 11 Nov 2026." if n_g == 0 else
                           "Live: " + ", ".join(f"{k} {v['expectancy_r']:+.2f}R ({v['closed']})" for k, v in graded.items()) + ". " + ("Too few to conclude." if n_g < 30 else ""))
                          + " Backtest on later and unseen data: A+ +1.10R, A +0.12R, B -0.22R, C -0.09R, Avoid -0.34R (8,670 trades)."})
    d = sw["by_direction"]
    out.append({"question": "Do bearish setups work?", "trades": (d.get("short") or {}).get("closed", 0),
                "answer": (f"Live: shorts {d['short']['expectancy_r']:+.2f}R over {d['short']['closed']} closed. " if d.get("short") else "Live: no short has closed. ")
                          + "Backtest: shorts lost in every asset class (-0.39R over 3,070 trades on later and unseen data)."})
    c, o = sw["closed"], sw["open"]
    out.append({"question": "Which strategy has the better expectancy so far?", "trades": c.get("closed", 0) + it["closed"].get("closed", 0),
                "answer": f"Live swing: {c.get('total_r', 0):+.1f}R closed plus {o['marked_r']:+.1f}R open on {c.get('closed', 0)} closed and {o['count']} open trades. "
                          f"Live intraday: {it['closed'].get('total_r', 0) or 0:+.1f}R over {it['closed'].get('closed', 0)} trades in {it['sessions']} sessions. "
                          "Neither sample is big enough to rank them. In backtests both are small: swing about +0.05R a trade, intraday about +0.08R."})
    et = sw["entry_timing"]
    if et["stopped"]:
        out.append({"question": "Are entries too early?", "trades": et["stopped"],
                    "answer": f"{et['stopped_within_2_bars']} of {et['stopped']} stopped trades were out within 2 bars"
                              + (f", and {et['stopped_never_reached_plus_half_r']} of {et['stopped_with_excursion_data']} never got to +0.5R" if et["stopped_with_excursion_data"] else "")
                              + ". In the 20-year test 15-21% of trades stopped within one bar, so some of this is normal for limit orders placed into pullbacks."})
    r = sw["by_regime"]
    if r:
        out.append({"question": "How do results differ by market regime?", "trades": c.get("closed", 0),
                    "answer": "Live: " + ", ".join(f"{k}: {v['expectancy_r']:+.2f}R ({v['closed']})" for k, v in r.items() if v.get("closed")) + ". Too few to conclude." if c.get("closed", 0) < 30 else
                              "Live: " + ", ".join(f"{k}: {v['expectancy_r']:+.2f}R ({v['closed']})" for k, v in r.items() if v.get("closed")) + "."})
    sh = it["shadow"]["closed"]
    out.append({"question": "Is the wider intraday stop (shadow rule) better?", "trades": sh.get("closed", 0),
                "answer": (f"Shadow log: {sh['expectancy_r']:+.2f}R over {sh['closed']} trades, against {it['shadow']['same_sessions_v1'].get('expectancy_r', 0) or 0:+.2f}R for the current rule on the same sessions. " if sh.get("closed") else "Shadow log started 11 Nov 2026: no closed session yet. ")
                          + f"It needs {it['shadow'].get('min_sessions') or 100} sessions before a decision. Backtest: +0.15R against +0.08R a trade."})
    return out


def build(sc: dict, it: dict, baseline: dict | None) -> dict:
    sw, itd = swing(sc), intraday(it)
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "live_since": sc.get("started") or it.get("started"),
            "kind": "Live paper log: every signal the app produced, followed with the tested rules. Not an account statement.",
            "swing": sw, "intraday": itd, "backtest": BACKTEST, "questions": questions(sw, itd), "baseline": baseline}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scorecard", required=True); ap.add_argument("--intraday", required=True)
    ap.add_argument("--baseline"); ap.add_argument("--out", required=True)
    a = ap.parse_args()

    def load(p):
        try:
            return json.load(open(p)) if p else {}
        except Exception:
            return {}
    out = build(load(a.scorecard), load(a.intraday), load(a.baseline) or None)
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    s, i = out["swing"]["closed"], out["intraday"]["closed"]
    print(f"performance: swing closed {s.get('closed', 0)} ({s.get('total_r', 0)}R), open {out['swing']['open']['count']} ({out['swing']['open']['marked_r']}R); intraday {i.get('closed', 0)} ({i.get('total_r', 0)}R)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
