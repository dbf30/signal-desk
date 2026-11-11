"""
Support / resistance levels and rule-based zones for Signal Desk.

Usage:  python3 levels.py --data data.json --out setups.json

Re-fetches two years of daily OHLC for every asset in data.json (via run.fetch_yahoo),
then for each asset finds:
  - support and resistance: clusters of swing highs/lows (a bar whose high/low is the
    extreme of the 5 bars either side) over the last ~year, plus the last 20 bars' range.
    Nearby swings (within 0.6 x ATR) merge into one level; "touches" = swings merged.
  - for assets whose score leans one way (|score| >= 15), a rule-based zone:
      bullish: the nearest support within 3 ATR (support - 0.25 ATR .. support + 0.5 ATR,
               capped at the current price); if none, a normal 0.75-1.5 ATR pullback.
      bearish: the mirror image at the nearest resistance.
    a signal-break level 0.75 ATR beyond the far edge of the zone, the next level in the
    signal's direction, and the reward:risk between them measured from the zone's middle.
These are mechanical reference levels, not recommendations.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from engine import atr_wilder, sma, rsi_wilder

PIVOT_WIN = 5
LOOKBACK = 260
MERGE_ATR = 0.6


def swing_points(d: pd.DataFrame, win: int = PIVOT_WIN) -> list[tuple[float, str, str]]:
    h, l = d["high"].values, d["low"].values
    out = []
    for i in range(win, len(d) - win):
        if h[i] == h[i - win:i + win + 1].max():
            out.append((float(h[i]), "high", str(d.index[i])[:10]))
        if l[i] == l[i - win:i + win + 1].min():
            out.append((float(l[i]), "low", str(d.index[i])[:10]))
    return out


def find_levels(df: pd.DataFrame, atr: float) -> list[dict]:
    d = df.iloc[-LOOKBACK:]
    raw = swing_points(d)
    last20 = d.iloc[-20:]
    raw.append((float(last20["high"].max()), "high", str(last20["high"].idxmax())[:10]))
    raw.append((float(last20["low"].min()), "low", str(last20["low"].idxmin())[:10]))
    raw.sort()
    clusters: list[list[tuple[float, str, str]]] = []
    for p in raw:
        if clusters and p[0] - clusters[-1][0][0] <= MERGE_ATR * atr:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = []
    for c in clusters:
        prices = [p[0] for p in c]
        levels.append({"price": float(np.median(prices)), "touches": len(c),
                       "last_touch": max(p[2] for p in c)})
    return levels


def _r(x, nd=6):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def analyse_levels(row: dict, df: pd.DataFrame) -> dict:
    df = df.sort_index()
    c = df["close"].astype(float)
    atr = float(atr_wilder(df["high"].astype(float), df["low"].astype(float), c).iloc[-1])
    price = float(c.iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return {"symbol": row["symbol"], "status": "no atr"}
    lv = find_levels(df, atr)
    sups = sorted([l for l in lv if l["price"] < price - 0.1 * atr], key=lambda l: -l["price"])
    ress = sorted([l for l in lv if l["price"] > price + 0.1 * atr], key=lambda l: l["price"])
    s20, s50, s200 = (float(sma(c, n).iloc[-1]) for n in (20, 50, 200))
    yr = df.iloc[-252:]
    hi52, lo52 = float(yr["high"].max()), float(yr["low"].min())
    rsi14 = float(rsi_wilder(c, 14).iloc[-1])
    score = row.get("score") or 0.0
    direction = "bullish" if score >= 15 else "bearish" if score <= -15 else None

    out = {
        "symbol": row["symbol"], "status": "ok", "as_of": str(df.index[-1])[:10],
        "price": _r(price), "atr": _r(atr), "atr_pct": round(100 * atr / price, 2),
        "direction": direction, "score": score, "label": row.get("label"),
        "confidence": row.get("confidence"),
        "supports": [{**l, "price": _r(l["price"]), "dist_atr": round((price - l["price"]) / atr, 2)} for l in sups[:3]],
        "resistances": [{**l, "price": _r(l["price"]), "dist_atr": round((l["price"] - price) / atr, 2)} for l in ress[:3]],
        "sma20": _r(s20), "sma50": _r(s50), "sma200": _r(s200),
        "high_52w": _r(hi52), "low_52w": _r(lo52), "rsi14": round(rsi14, 1) if np.isfinite(rsi14) else None,
        "notes": [],
    }
    if direction is None:
        return out

    bull = direction == "bullish"
    sgn = 1 if bull else -1
    near = sups if bull else ress                      # levels the zone sits on
    ahead = ress if bull else sups                     # levels in the signal's direction
    anchor = next((l for l in near if abs(price - l["price"]) <= 3 * atr), None)
    if anchor:
        a = anchor["price"]
        lo, hi = (a - 0.25 * atr, min(a + 0.5 * atr, price)) if bull else (max(a - 0.5 * atr, price), a + 0.25 * atr)
        basis = f"{'Support' if bull else 'Resistance'} at {a:.6g} ({anchor['touches']} touch{'es' if anchor['touches'] != 1 else ''}, last {anchor['last_touch']})"
    else:
        lo, hi = (price - 1.5 * atr, price - 0.75 * atr) if bull else (price + 0.75 * atr, price + 1.5 * atr)
        basis = f"No {'support' if bull else 'resistance'} within 3 daily ranges, so a normal 0.75-1.5 ATR {'pullback' if bull else 'bounce'}"
    brk = lo - 0.75 * atr if bull else hi + 0.75 * atr
    mid = (lo + hi) / 2
    tgt = next((l for l in ahead if (l["price"] - mid) * sgn > 0.25 * atr), None)
    if tgt:
        target = {"price": _r(tgt["price"]), "basis": f"next {'resistance' if bull else 'support'} ({tgt['touches']} touch{'es' if tgt['touches'] != 1 else ''})"}
        rr = round(abs(tgt["price"] - mid) / abs(mid - brk), 2)
    else:
        target = {"price": None, "basis": f"no {'resistance above' if bull else 'support below'} in the last year ({'at highs' if bull else 'at lows'})"}
        rr = None
    in_zone = lo <= price <= hi
    dist = 0.0 if in_zone else round(min(abs(price - lo), abs(price - hi)) / atr, 2)
    out.update({
        "zone": {"lo": _r(lo), "hi": _r(hi), "basis": basis, "in_zone": bool(in_zone), "dist_atr": dist,
                 "kind": "pullback" if bull else "bounce", "anchor_touches": int(anchor["touches"]) if anchor else 0},
        "signal_break": _r(brk), "target": target, "reward_risk": rr,
        "trend_flip": _r(s200) if np.isfinite(s200) else None,
    })
    stretch = (price - s20) / atr if np.isfinite(s20) else 0
    if bull and stretch > 2:
        out["notes"].append(f"Stretched: price is {stretch:.1f} daily ranges above its 20-day average. Uptrends often pause or dip back toward it.")
    if not bull and stretch < -2:
        out["notes"].append(f"Stretched: price is {-stretch:.1f} daily ranges below its 20-day average. Downtrends often bounce back toward it.")
    if np.isfinite(rsi14) and ((bull and rsi14 > 70) or (not bull and rsi14 < 30)):
        out["notes"].append(f"RSI(14) is {rsi14:.0f}, already stretched in the signal's direction.")
    if rr is not None and rr < 1.5:
        out["notes"].append(f"Only {rr:.1f}x reward for the risk to the next level. Room is tight.")
    if target["price"] is None:
        out["notes"].append(f"Price is at 1-year {'highs' if bull else 'lows'}, so there's no nearby level in the signal's direction to measure against.")
    if not in_zone and dist > 2:
        out["notes"].append(f"Price is {dist:.1f} daily ranges from the zone. It may never get there.")
    return out


def pick(setups: list[dict], n: int = 3) -> list[str]:
    cands = [s for s in setups if s.get("status") == "ok" and s.get("direction") and abs(s.get("score") or 0) >= 40
             and s.get("confidence") != "Low"]
    if len(cands) < 2:
        cands = [s for s in setups if s.get("status") == "ok" and s.get("direction") and abs(s.get("score") or 0) >= 25]
    rank = lambda s: abs(s["score"]) * (1.0 if s.get("confidence") == "High" else 0.85)
    return [s["symbol"] for s in sorted(cands, key=rank, reverse=True)[:n]]


def main() -> int:
    from run import WATCHLIST, fetch_yahoo
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="setups.json")
    a = ap.parse_args()
    data = json.load(open(a.data))
    ysym = {sym: y for y, sym, _, _ in WATCHLIST}
    setups, errors = [], []
    for row in data.get("assets", []):
        if row.get("status") != "ok" or row.get("stale") or row["symbol"] not in ysym:
            continue
        try:
            df = fetch_yahoo(ysym[row["symbol"]], "2y")
            setups.append(analyse_levels(row, df))
        except Exception as e:
            errors.append(f"{row['symbol']}: {e}")
        time.sleep(0.4)
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "picks": pick(setups), "assets": setups, "errors": errors}
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"levels ok: {sum(1 for s in setups if s.get('status') == 'ok')}  picks: {', '.join(out['picks']) or 'none'}  errors: {len(errors)}")
    for e in errors:
        print("ERROR", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
