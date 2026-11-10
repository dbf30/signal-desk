"""Generalised version of trades.simulate_trade. With default params it must reproduce it exactly.
Returns the trade plus a daily mark path (R at each close, last value = final R incl. costs)."""
import math
import numpy as np

MAX_WAIT = 10


def simulate(bull, lo, hi, stop, atr, o, h, l, c, sc, dates, cost_frac,
             exit_level=15.0, max_hold=60, entry="limit", partial=False):
    limit = hi if bull else lo
    n = len(o)
    out = {"status": "pending", "entry": None, "fill_i": None, "exit_i": None, "r": None, "path": None}
    fill_i = None
    if entry == "limit":
        for i in range(min(MAX_WAIT, n)):
            if (bull and l[i] <= limit) or (not bull and h[i] >= limit):
                entry_px = min(o[i], limit) if bull else max(o[i], limit)
                fill_i = i
                break
    else:  # confirm: price trades into the zone, then closes back out in trend direction -> enter next open
        touched = False
        for i in range(min(MAX_WAIT, n)):
            if (bull and l[i] <= hi) or (not bull and h[i] >= lo):
                touched = True
            if touched and ((bull and c[i] > hi) or (not bull and c[i] < lo)):
                if i + 1 < n:
                    entry_px = o[i + 1]; fill_i = i + 1
                break
            if (bull and c[i] < stop) or (not bull and c[i] > stop):
                break  # level failed before confirming
    if fill_i is None:
        if n >= MAX_WAIT:
            out["status"] = "unfilled"
        return out
    risk = (entry_px - stop) if bull else (stop - entry_px)
    out.update(entry=float(entry_px), fill_i=fill_i)
    if not (risk > 0):
        out.update(status="loss", exit_i=fill_i, r=-1.0, path=[(fill_i, -1.0)])
        return out
    cost_r = cost_frac * entry_px * 2 / risk
    sgn = 1 if bull else -1
    R = lambda px: sgn * (px - entry_px) / risk
    banked, size = 0.0, 1.0          # partial: R banked from the first half, size still open
    cur_stop = stop
    best = c[fill_i]
    path = []

    def done(px, i, reason):
        r = round(banked + size * R(px) - cost_r, 3)
        path.append((i, r))
        out.update(status="win" if r > 0 else "loss", exit_i=i, r=r, exit=float(px), reason=reason, path=path)
        return out

    # fill bar
    if (bull and l[fill_i] <= cur_stop) or (not bull and h[fill_i] >= cur_stop):
        return done(cur_stop, fill_i, "stop")
    if partial and R(h[fill_i] if bull else l[fill_i]) >= 2 and size == 1.0:
        banked, size = 1.0, 0.5
    path.append((fill_i, banked + size * R(c[fill_i])))
    if partial:
        best = c[fill_i]
        if size < 1.0:
            cur_stop = max(cur_stop, best - 3 * atr) if bull else min(cur_stop, best + 3 * atr)
    for i in range(fill_i + 1, min(n, fill_i + max_hold + 1)):
        if bull and o[i] <= cur_stop: return done(o[i], i, "stop (gap)")
        if bull and l[i] <= cur_stop: return done(cur_stop, i, "stop")
        if not bull and o[i] >= cur_stop: return done(o[i], i, "stop (gap)")
        if not bull and h[i] >= cur_stop: return done(cur_stop, i, "stop")
        s = sc[i - 1]
        if s is not None and not (isinstance(s, float) and math.isnan(s)) and ((bull and s < exit_level) or (not bull and s > -exit_level)):
            return done(o[i], i, "signal faded")
        if partial and size == 1.0:
            tgt = entry_px + sgn * 2 * risk
            if (bull and h[i] >= tgt) or (not bull and l[i] <= tgt):
                px = max(o[i], tgt) if bull else min(o[i], tgt)
                banked, size = 0.5 * R(px), 0.5
        path.append((i, banked + size * R(c[i])))
        if partial and size < 1.0:
            best = max(best, c[i]) if bull else min(best, c[i])
            cur_stop = max(cur_stop, best - 3 * atr) if bull else min(cur_stop, best + 3 * atr)
    last = fill_i + max_hold
    if last < n:
        path.pop()  # replace the last mark with the exit
        return done(c[last], last, "time limit")
    r = round(banked + size * R(c[-1]) - cost_r, 3)
    path[-1] = (path[-1][0], r)
    out.update(status="open", r=r, path=path)
    return out
