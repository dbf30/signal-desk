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

VERSION = "swing-v1"       # trade rules in trades.py, unchanged since the 10 Nov 2026 study

COST = {"stock": 5e-4, "index": 1e-4, "fx": 1e-4, "commodity": 3e-4, "crypto": 10e-4, "bond": 1e-4}
ACTIVE = ("pending", "open")


def new_entries(data: dict, setups: dict, entries: list, regime: dict | None = None, model: dict | None = None) -> list:
    """regime / model (optional): stamp each new entry with the market regime and its grade on the signal day."""
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
        e = {"id": f"{s['symbol']}-{s['as_of']}", "symbol": s["symbol"], "asset_class": a["asset_class"],
             "direction": s["direction"], "signal_date": s["as_of"], "score": s["score"],
             "zone": {"lo": s["zone"]["lo"], "hi": s["zone"]["hi"]}, "signal_break": s["signal_break"],
             "status": "pending", "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "version": VERSION}
        if regime:
            e["regime"] = {"trend": regime.get("trend"), "overlay": regime.get("overlay")}
        if model:
            from plans import grade_for, setup_type
            z = s["zone"]
            g = grade_for(model, a["asset_class"], s["direction"], s["score"], bool(z.get("in_zone")), z.get("dist_atr") or 0.0,
                          s.get("reward_risk"), z.get("anchor_touches", 1), regime or {})
            e.update(grade=g["grade"], predicted_r=g["predicted_r"], grade_parts=g["parts"],
                     setup_type=setup_type(s["direction"] == "bullish", z.get("anchor_touches")))
        added.append(e)
    return added


def update_entry(e: dict, df: pd.DataFrame, score_by_date: dict) -> dict:
    df = df.sort_index()
    bars = df[df.index > pd.Timestamp(e["signal_date"])].iloc[:MAX_WAIT + MAX_HOLD + 1]
    scores = [score_by_date.get(str(d)[:10], float("nan")) for d in bars.index]
    r = simulate_trade(e, bars, scores, COST.get(e["asset_class"], 0.0))
    e.update({k: r.get(k) for k in ("status", "entry", "exit", "fill_date", "exit_date", "r", "exit_reason")})
    e["checked_through"] = str(bars.index[-1])[:10] if len(bars) else e["signal_date"]
    e.update(excursions(e, df))
    return e


def excursions(e: dict, df: pd.DataFrame) -> dict:
    """Best and worst point of a filled trade, in units of PLANNED risk (entry-zone edge to stop), and bars held.
    Measurement only: it never changes the result. Daily bars do not show the order of moves inside a bar, so:
    - on the fill bar the best point is taken from the close, not the high (the high may have come before the fill);
    - on a bar that ends the trade at the stop, the best point is not counted (the high may have come after the stop).
    A trade filled and stopped in the same bar has no measurable best point (mfe_r is None)."""
    if not e.get("fill_date") or e.get("entry") is None:
        return {}
    bull = e["direction"] == "bullish"
    z = e.get("zone") or {}
    limit = (z.get("hi") if bull else z.get("lo")) or e["entry"]
    risk = (limit - e["signal_break"]) if bull else (e["signal_break"] - limit)
    df = df.sort_index()
    b = df[df.index >= pd.Timestamp(e["fill_date"])]
    if e.get("exit_date"):
        b = b[b.index <= pd.Timestamp(e["exit_date"])]
    if not len(b) or not (risk > 0):
        return {}
    stopped = str(e.get("exit_reason") or "").startswith(("stop", "opened"))
    sgn = 1.0 if bull else -1.0
    entry = float(e["entry"])
    hi, lo, cl = (b[k].astype(float).values for k in ("high", "low", "close"))
    best, worst = [], []
    for i in range(len(b)):
        fav_px, adv_px = (hi[i], lo[i]) if bull else (lo[i], hi[i])
        last_stop = stopped and i == len(b) - 1
        if last_stop:
            worst.append(sgn * (float(e.get("exit") or adv_px) - entry))
        else:
            worst.append(sgn * (adv_px - entry))
            best.append(sgn * ((cl[i] if i == 0 else fav_px) - entry))
    return {"mfe_r": round(max(best) / risk, 2) if best else None, "mae_r": round(min(worst) / risk, 2), "bars_held": int(len(b))}


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
    ap.add_argument("--regime"); ap.add_argument("--model")
    a = ap.parse_args()
    data, setups = json.load(open(a.data)), json.load(open(a.setups))
    prev = {}
    if a.prev:
        try:
            prev = json.load(open(a.prev))
        except Exception as ex:
            print("no usable previous scorecard:", ex, file=sys.stderr)
    entries = prev.get("entries", [])
    regime, model = {}, {}
    for path, name in ((a.regime, "regime"), (a.model, "model")):
        if path:
            try:
                if name == "regime": regime = json.load(open(path))
                else: model = json.load(open(path))
            except Exception as ex:
                print(f"no usable {name} file:", ex, file=sys.stderr)
    if a.record:
        entries += new_entries(data, setups, entries, regime or None, model or None)
    if regime:      # give older entries the stock-market trend on their signal day, where the history reaches
        from regime import regime_on
        for e in entries:
            if "regime" not in e:
                t = regime_on(regime, e["signal_date"])
                if t:
                    e["regime"] = {"trend": t, "overlay": None, "backfilled": True}
    ysym = {sym: y for y, sym, _, _ in WATCHLIST}
    hist = {r["symbol"]: {h["date"]: h["score"] for h in r.get("history", []) if h.get("score") is not None}
            for r in data.get("assets", []) if r.get("status") == "ok"}
    errors = []
    for e in entries:
        if e["symbol"] not in ysym:
            continue
        if e["status"] not in ACTIVE:
            if e["status"] in ("win", "loss") and "mfe_r" not in e:     # one-off: measure trades closed before v2
                try:
                    e.update(excursions(e, fetch_yahoo(ysym[e["symbol"]], "1y")))
                    e.setdefault("mfe_r", None)
                except Exception as ex:
                    errors.append(f"{e['symbol']}: {ex}")
                time.sleep(0.3)
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
           "version": VERSION, "summary": summarise(entries), "entries": entries[-400:], "errors": errors}
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    s = out["summary"]
    print(f"scorecard: closed {s['all'].get('closed', 0)}  open {s['open']}  pending {s['pending']}  errors {len(errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
