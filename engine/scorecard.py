"""
Live scorecard: records every Signal Desk setup (|score| >= 40 with a zone) and follows it with the
same rules as the historical test (trades.py), so live results can be compared with the backtest.

Usage:  python3 scorecard.py --data data.json --setups setups.json [--prev scorecard.json]
                             --out scorecard.json [--record]
--record adds new setups (the scheduled task passes it on the 21:40 UK run only, after the US close).
Without it, existing entries are only updated.
"""
from __future__ import annotations
import argparse, json, math, sys, time
from datetime import datetime, timezone
import pandas as pd

from trades import simulate_trade, MAX_WAIT, MAX_HOLD

COST = {"stock": 5e-4, "index": 1e-4, "fx": 1e-4, "commodity": 3e-4, "crypto": 10e-4, "bond": 1e-4}
ACTIVE = ("pending", "open")


def new_entries(data: dict, setups: dict, entries: list) -> list:
    rows = {a["symbol"]: a for a in data.get("assets", []) if a.get("status") == "ok" and not a.get("stale")}
    active = {e["symbol"] for e in entries if e["status"] in ACTIVE}
    seen = {(e["symbol"], e["signal_date"]) for e in entries}
    added = []
    for s in setups.get("assets", []):
        a = rows.get(s.get("symbol"))
        if not a or s.get("status") != "ok" or "zone" not in s or abs(s.get("score") or 0) < 40:
            continue
        if s["symbol"] in active or (s["symbol"], s["as_of"]) in seen:
            continue
        added.append({"id": f"{s['symbol']}-{s['as_of']}", "symbol": s["symbol"], "asset_class": a["asset_class"],
                      "direction": s["direction"], "signal_date": s["as_of"], "score": s["score"],
                      "zone": {"lo": s["zone"]["lo"], "hi": s["zone"]["hi"]}, "signal_break": s["signal_break"],
                      "status": "pending", "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return added


def update_entry(e: dict, df: pd.DataFrame, score_by_date: dict) -> dict:
    df = df.sort_index()
    bars = df[df.index > pd.Timestamp(e["signal_date"])].iloc[:MAX_WAIT + MAX_HOLD + 1]
    scores = [score_by_date.get(str(d)[:10], float("nan")) for d in bars.index]
    r = simulate_trade(e, bars, scores, COST.get(e["asset_class"], 0.0))
    e.update({k: r.get(k) for k in ("status", "entry", "exit", "fill_date", "exit_date", "r", "exit_reason")})
    e["checked_through"] = str(bars.index[-1])[:10] if len(bars) else e["signal_date"]
    return e


def summarise(entries: list) -> dict:
    closed = [e for e in entries if e["status"] in ("win", "loss")]
    def block(xs):
        if not xs:
            return {"closed": 0}
        rs = [x["r"] for x in xs]
        return {"closed": len(xs), "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3),
                "avg_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 2)}
    by = {}
    for e in closed:
        by.setdefault(f"{e['asset_class']}:{e['direction']}", []).append(e)
    return {"all": block(closed), "groups": {k: block(v) for k, v in by.items()},
            "open": sum(e["status"] == "open" for e in entries), "pending": sum(e["status"] == "pending" for e in entries),
            "unfilled": sum(e["status"] == "unfilled" for e in entries)}


def main() -> int:
    from run import WATCHLIST, fetch_yahoo
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--setups", required=True)
    ap.add_argument("--prev"); ap.add_argument("--out", required=True); ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    data, setups = json.load(open(a.data)), json.load(open(a.setups))
    prev = {}
    if a.prev:
        try:
            prev = json.load(open(a.prev))
        except Exception as ex:
            print("no usable previous scorecard:", ex, file=sys.stderr)
    entries = prev.get("entries", [])
    if a.record:
        entries += new_entries(data, setups, entries)
    ysym = {sym: y for y, sym, _, _ in WATCHLIST}
    hist = {r["symbol"]: {h["date"]: h["score"] for h in r.get("history", []) if h.get("score") is not None}
            for r in data.get("assets", []) if r.get("status") == "ok"}
    errors = []
    for e in entries:
        if e["status"] not in ACTIVE or e["symbol"] not in ysym:
            continue
        try:
            df = fetch_yahoo(ysym[e["symbol"]], "1y")
            update_entry(e, df, {**e.get("scores_seen", {}), **hist.get(e["symbol"], {})})
            # keep the scores used, so later runs can still see them after they leave the 180-bar history
            sc = hist.get(e["symbol"], {})
            e["scores_seen"] = {d: v for d, v in {**e.get("scores_seen", {}), **sc}.items() if d > e["signal_date"]}
        except Exception as ex:
            errors.append(f"{e['symbol']}: {ex}")
        time.sleep(0.3)
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "started": prev.get("started") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "summary": summarise(entries), "entries": entries[-400:], "errors": errors}
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    s = out["summary"]
    print(f"scorecard: closed {s['all'].get('closed', 0)}  open {s['open']}  pending {s['pending']}  errors {len(errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
