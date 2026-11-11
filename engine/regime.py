"""
Market regime for Signal Desk: what kind of market the signals are operating in.

Usage:  python3 regime.py --data data.json --out regime.json

Deterministic, from data.json only (no extra downloads). Three layers:
  trend    - the US stock market's own trend (SPY, falling back to US500):
             Strong bullish / Moderate bullish / Sideways / Moderate bearish / Strong bearish
  overlay  - conditions that override the trend label when present:
             Unstable (a >3-sigma daily move in the last 5 bars, or volatility at 2x normal),
             High volatility (20-day volatility more than 1.5x the 1-year level),
             Risk-off (stocks leaning bearish while bonds or gold lean bullish)
  breadth  - share of markets leaning bullish / bearish and above their 200-day average

The regime does NOT switch signals on or off. It is stamped on every logged trade so results can be
split by regime, and it sets how demanding the checklist is (see POLICY).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone

TRENDS = ["Strong bullish", "Moderate bullish", "Sideways", "Moderate bearish", "Strong bearish"]
OVERLAYS = ["Unstable", "High volatility", "Risk-off"]

POLICY = {
    "Strong bullish": {"swing": "Pullbacks in established uptrends are the tested setup; normal selectivity.",
                       "intraday": "Normal selectivity. Trade with the daily bias only."},
    "Moderate bullish": {"swing": "Uptrend without full breadth: prefer markets whose own score is 40 or more.",
                         "intraday": "Normal selectivity. Trade with the daily bias only."},
    "Sideways": {"swing": "No market tailwind either way. Trend setups fail more often in ranges: expect more small losses.",
                 "intraday": "Breakouts fail more often in ranges. Expect more stop-outs."},
    "Moderate bearish": {"swing": "Stock-market headwind for long setups in stocks and indices. Other markets are judged on their own trend.",
                         "intraday": "Trade with the daily bias only."},
    "Strong bearish": {"swing": "Long setups in stocks and indices are against the market. Bearish setups have lost money in testing: 'step aside' is the tested response.",
                       "intraday": "Trade with the daily bias only."},
    "High volatility": {"swing": "Daily ranges are well above normal: stops are hit more easily and gaps are bigger. Size positions from the wider range.",
                        "intraday": "Ranges are wide, so each trade risks more price distance. Size down to keep risk fixed."},
    "Unstable": {"swing": "A shock move has just happened. Levels are often overshot. New entries deserve extra caution.",
                 "intraday": "Shock conditions: breakouts and reversals are both violent. Extra caution."},
    "Risk-off": {"swing": "Money is moving to bonds or gold and out of stocks. Long stock and crypto setups face a headwind.",
                 "intraday": "Trade with the daily bias only."},
}


def _trend(close, sma50, sma200, score) -> str | None:
    if close is None or sma200 is None or sma50 is None or score is None:
        return None
    above200, above50, golden = close > sma200, close > sma50, sma50 > sma200
    if above200 and golden and above50 and score >= 40:
        return "Strong bullish"
    if above200 and score >= 15:
        return "Moderate bullish"
    if not above200 and not golden and score <= -40:
        return "Strong bearish"
    if not above200 and score <= -15:
        return "Moderate bearish"
    return "Sideways"


def _shock(history: list[dict]) -> tuple[bool, float | None]:
    """True if any of the last 5 daily moves is more than 3 standard deviations of the prior 60."""
    c = [h["close"] for h in history if h.get("close")]
    if len(c) < 70:
        return False, None
    r = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    base = r[-65:-5]
    m = sum(base) / len(base)
    sd = math.sqrt(sum((x - m) ** 2 for x in base) / (len(base) - 1))
    if sd <= 0:
        return False, None
    z = max(abs(x) / sd for x in r[-5:])
    return z > 3.0, round(z, 2)


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def build(data: dict) -> dict:
    rows = {a["symbol"]: a for a in data.get("assets", []) if a.get("status") == "ok"}
    bench = rows.get("SPY") or rows.get("US500")
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "ok",
           "benchmark": bench["symbol"] if bench else None}
    if not bench:
        out.update(status="no benchmark", label="Unknown", trend=None, overlay=None, evidence=["No S&P 500 data this run."])
        return out

    trend = _trend(bench.get("price"), bench.get("sma50"), bench.get("sma200"), bench.get("score"))
    shock, z = _shock(bench.get("history", []))
    vr = bench.get("vol_ratio")

    def cls_avg(cls):
        return _avg([a.get("score") for a in rows.values() if a["asset_class"] == cls])

    eq_rows = [a for a in rows.values() if a["asset_class"] in ("stock", "index")]
    all_rows = list(rows.values())

    def breadth(rs):
        n = len(rs)
        if not n:
            return None
        return {"markets": n,
                "bullish_pct": round(100 * sum(a["score"] >= 15 for a in rs) / n),
                "bearish_pct": round(100 * sum(a["score"] <= -15 for a in rs) / n),
                "above_200d_pct": round(100 * sum(1 for a in rs if a.get("sma200") and a["price"] > a["sma200"]) / n)}

    eq_score = _avg([a["score"] for a in eq_rows])
    bond_score = cls_avg("bond")
    gold = rows.get("GOLD", {}).get("score")
    risk_off = eq_score is not None and eq_score <= -15 and ((bond_score is not None and bond_score >= 15) or (gold is not None and gold >= 15))

    overlay = None
    if shock or (vr is not None and vr >= 2.0):
        overlay = "Unstable"
    elif vr is not None and vr > 1.5:
        overlay = "High volatility"
    elif risk_off:
        overlay = "Risk-off"

    ev = []
    b = bench
    ev.append(f"{b['symbol']} {b['price']:.2f} is {'above' if b['price'] > b['sma200'] else 'below'} its 200-day average ({b['sma200']:.2f}) and "
              f"{'above' if b['price'] > b['sma50'] else 'below'} its 50-day ({b['sma50']:.2f}); trend score {b['score']:+.0f}.")
    if vr is not None:
        ev.append(f"20-day volatility is {vr:.2f}x its 1-year level" + (" (elevated)." if vr > 1.5 else " (normal)." if vr >= 0.7 else " (quiet)."))
    if z is not None:
        ev.append(f"Largest daily move in the last 5 bars: {z:.1f} standard deviations" + (" (shock)." if shock else "."))
    eb, ab = breadth(eq_rows), breadth(all_rows)
    if eb:
        ev.append(f"Stocks and indices: {eb['bullish_pct']}% lean bullish, {eb['bearish_pct']}% bearish, {eb['above_200d_pct']}% above their 200-day average ({eb['markets']} markets).")
    if ab:
        ev.append(f"All markets: {ab['bullish_pct']}% lean bullish, {ab['bearish_pct']}% bearish ({ab['markets']} markets).")
    if risk_off:
        ev.append("Stocks lean bearish while bonds or gold lean bullish: a risk-off pattern.")

    btc = rows.get("BTC")
    backdrop = {
        "equity": None if trend is None else ("up" if b["price"] > b["sma200"] else "down"),
        "crypto": None if not btc or not btc.get("sma200") else ("up" if btc["price"] > btc["sma200"] else "down"),
    }
    cross = {k: (None if v is None else round(v, 1)) for k, v in {
        "stocks_indices": eq_score, "bonds": bond_score, "gold": gold, "commodities": cls_avg("commodity"),
        "forex": cls_avg("fx"), "crypto": cls_avg("crypto")}.items()}

    # trend label for each of the benchmark's last 180 bars, so older log entries can be given a regime
    hist = []
    for h in bench.get("history", []):
        t = _trend(h.get("close"), h.get("sma50"), h.get("sma200"), h.get("score"))
        if t:
            hist.append({"date": h["date"], "trend": t})

    label = overlay or trend or "Unknown"
    out.update({
        "label": label, "trend": trend, "overlay": overlay,
        "as_of": bench.get("as_of"), "stale": bool(bench.get("stale")),
        "evidence": ev, "vol_ratio": vr, "shock_sigma": z,
        "breadth": {"equity": eb, "all": ab}, "cross_asset": cross, "backdrop": backdrop,
        "policy": POLICY.get(label, {}), "trend_policy": POLICY.get(trend, {}) if overlay else None,
        "history": hist,
    })
    return out


def regime_on(regime: dict, date: str) -> str | None:
    """Trend label on or just before `date` (YYYY-MM-DD), from regime['history']."""
    best = None
    for h in regime.get("history", []):
        if h["date"] <= date:
            best = h["trend"]
        else:
            break
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="regime.json")
    a = ap.parse_args()
    out = build(json.load(open(a.data)))
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    print(f"regime: {out.get('label')} (trend {out.get('trend')}, overlay {out.get('overlay')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
