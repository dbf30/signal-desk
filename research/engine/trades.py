"""
Trade rules for Signal Desk setups, shared by the historical test and the live scorecard.

Tested Nov 2026 (research/setup_sim*.py, 2005-2026, ~100 assets): a fixed target at the next
support/resistance had no edge (about 0R per trade), while letting the trade run until the signal
fades was clearly positive for bullish setups in stocks, indices, bonds, commodities and crypto.
So the rules are:
- Signal: |score| >= 40 with a zone from levels.analyse_levels.
- Entry: limit order at the near edge of the zone (long: zone top, short: zone bottom), valid for
  MAX_WAIT bars. A bar that opens through the order fills at the open.
- Stop: the signal-break level. Fill bar trading through the stop = loss (conservative). A bar
  opening beyond the stop exits at that worse open.
- Exit: at the next open after the score closes back inside +/-15 (signal over), or at the close
  MAX_HOLD bars after the fill.
- Result in R (entry-to-stop risk), after a round-trip cost.
"""
from __future__ import annotations
import math
import pandas as pd

MAX_WAIT = 10
MAX_HOLD = 60
EXIT_LEVEL = 15


def simulate_trade(setup: dict, bars: pd.DataFrame, scores, cost_frac: float = 0.0) -> dict:
    """bars: OHLC strictly after the signal bar (oldest first). scores: the score at each of those
    bars' closes (same length; NaN allowed). Returns status unfilled / pending / open / win / loss."""
    bull = setup["direction"] == "bullish"
    lo, hi = setup["zone"]["lo"], setup["zone"]["hi"]
    stop = setup["signal_break"]
    limit = hi if bull else lo
    o, h, l, c = (bars[k].astype(float).values for k in ("open", "high", "low", "close"))
    sc = list(scores)
    idx = list(bars.index)
    out = {"status": "pending", "entry": None, "exit": None, "fill_date": None, "exit_date": None, "r": None,
           "stop": float(stop), "exit_reason": None}
    fill_i = None
    for i in range(min(MAX_WAIT, len(bars))):
        if (bull and l[i] <= limit) or (not bull and h[i] >= limit):
            entry = min(o[i], limit) if bull else max(o[i], limit)
            fill_i = i
            break
    if fill_i is None:
        if len(bars) >= MAX_WAIT:
            out["status"] = "unfilled"
        return out
    risk = (entry - stop) if bull else (stop - entry)
    out.update(entry=float(entry), fill_date=str(idx[fill_i])[:10])
    if not (risk > 0):
        out.update(status="loss", exit=float(stop), exit_date=str(idx[fill_i])[:10], r=-1.0, exit_reason="opened beyond stop")
        return out
    cost_r = cost_frac * entry * 2 / risk

    def done(px, i, reason):
        pnl = (px - entry) if bull else (entry - px)
        r = round(pnl / risk - cost_r, 3)
        out.update(status="win" if r > 0 else "loss", exit=float(px), exit_date=str(idx[i])[:10], r=r, exit_reason=reason)
        return out

    if (bull and l[fill_i] <= stop) or (not bull and h[fill_i] >= stop):
        return done(stop, fill_i, "stop")
    for i in range(fill_i + 1, min(len(bars), fill_i + MAX_HOLD + 1)):
        if bull and o[i] <= stop: return done(o[i], i, "stop (gap)")
        if bull and l[i] <= stop: return done(stop, i, "stop")
        if not bull and o[i] >= stop: return done(o[i], i, "stop (gap)")
        if not bull and h[i] >= stop: return done(stop, i, "stop")
        s = sc[i - 1]
        if s is not None and not (isinstance(s, float) and math.isnan(s)) and ((bull and s < EXIT_LEVEL) or (not bull and s > -EXIT_LEVEL)):
            return done(o[i], i, "signal faded")
    last = fill_i + MAX_HOLD
    if last < len(bars):
        return done(c[last], last, "time limit")
    # still running: mark to last close
    pnl = (c[-1] - entry) if bull else (entry - c[-1])
    out.update(status="open", r=round(pnl / risk - cost_r, 3), exit=None)
    return out
