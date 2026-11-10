"""
Intraday setups (flat by session end), tested Nov 2026 on ~2 years of hourly data (research/intraday_sim.py).

Adopted (positive in the later half of the data and on unseen coins, after costs):
CRYPTO "London range breakout": when the daily score is >= +15 (or <= -15), the 08:00-09:00 UK hourly
  bar sets the range; a stop order at its high (low for bearish) from 09:00, stop at the other side of
  the range, exit at 20:00 UK.

Not adopted:
- Index "open drive" (enter at the cash open in the daily trend's direction, 0.25 ATR stop, 2R target)
  looked good only on European/Asian cash indices, whose first hourly 'open' is often stale (the UK100
  open sat within 0.05% of the previous close on a typical day), so those fills weren't really
  available. On tradeable prices (US index futures, SPY/QQQ/IWM) it lost slightly.
- Forex, commodities and single stocks: no rule held up. The published "last half-hour momentum"
  effect also lost money on US stocks and index ETFs after costs.
- Entering deeper (a limit further from the open, nearer the stop) did worse everywhere: those fills
  mostly happen on days the trend reverses.

Usage: python3 intraday.py --data data.json --out intraday.json [--prev intraday.json]
"""
from __future__ import annotations
import argparse, json, sys, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd

UK, NY = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
COST = {"index": 6e-5, "crypto": 80e-5}
RULES = {
    "crypto": {"name": "London range breakout", "bias": 15, "kind": "orb", "stop_atr": None, "target_r": None},
}
# kept for reference/tests only; not adopted (see above)
INDEX_RULE = {"name": "Open drive", "bias": 40, "kind": "open", "stop_atr": 0.25, "target_r": 2.0}
US_FUT = {"US500", "NAS100", "US30", "US2000"}


def intraday_trade(o, h, l, c, bull: bool, kind: str, atr: float, stop_atr, target_r, cost: float, complete: bool) -> dict:
    """Same fill rules as the test. o/h/l/c: session bars so far. Returns status and prices."""
    n = len(o)
    out = {"status": "waiting", "entry": None, "stop": None, "target": None, "r": None}
    if kind == "open":
        if n == 0:
            return out
        E = o[0]; S = E - stop_atr * atr if bull else E + stop_atr * atr; start = 0
    else:
        if n == 0:
            out["status"] = "range forming"; return out
        E = h[0] if bull else l[0]; S = l[0] if bull else h[0]; start = 1
        out.update(entry=float(E), stop=float(S))
        if n == 1:
            out["status"] = "range forming" if not complete else "no fill"; return out
    fi = None
    for i in range(start, n):
        if kind == "open":
            fi, entry = 0, o[0]; break
        if bull and o[i] >= E: fi, entry = i, o[i]; break
        if not bull and o[i] <= E: fi, entry = i, o[i]; break
        if bull and h[i] >= E: fi, entry = i, E; break
        if not bull and l[i] <= E: fi, entry = i, E; break
    if fi is None:
        out["status"] = "no fill" if complete else "waiting for entry"; return out
    risk = (entry - S) if bull else (S - entry)
    T = None if target_r is None else (entry + target_r * risk if bull else entry - target_r * risk)
    out.update(entry=float(entry), stop=float(S), target=None if T is None else float(T))
    if risk <= 0:
        out.update(status="stopped", r=-1.0); return out
    cr = cost * entry / risk
    R = lambda px: round(((px - entry) if bull else (entry - px)) / risk - cr, 3)
    if (bull and l[fi] <= S) or (not bull and h[fi] >= S):
        out.update(status="stopped", r=R(S)); return out
    for i in range(fi + 1, n):
        if bull:
            if o[i] <= S: out.update(status="stopped", r=R(o[i])); return out
            if l[i] <= S: out.update(status="stopped", r=R(S)); return out
            if T is not None and o[i] >= T: out.update(status="target hit", r=R(o[i])); return out
            if T is not None and h[i] >= T: out.update(status="target hit", r=R(T)); return out
        else:
            if o[i] >= S: out.update(status="stopped", r=R(o[i])); return out
            if h[i] >= S: out.update(status="stopped", r=R(S)); return out
            if T is not None and o[i] <= T: out.update(status="target hit", r=R(o[i])); return out
            if T is not None and l[i] <= T: out.update(status="target hit", r=R(T)); return out
    if complete:
        out.update(status="closed at session end", r=R(c[-1]))
    else:
        out.update(status="in trade", r=R(c[-1]))
    return out


def session_window(sym: str, cls: str, day):
    """(start, end) of the session as UTC timestamps for a local date `day`."""
    if cls == "index" and sym in US_FUT:
        s = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY); e = datetime(day.year, day.month, day.day, 16, 0, tzinfo=NY)
    elif cls == "index":   # GER40 / UK100 cash hours (UK time)
        s = datetime(day.year, day.month, day.day, 8, 0, tzinfo=UK); e = datetime(day.year, day.month, day.day, 16, 30, tzinfo=UK)
    else:                  # crypto, London session
        s = datetime(day.year, day.month, day.day, 8, 0, tzinfo=UK); e = datetime(day.year, day.month, day.day, 20, 0, tzinfo=UK)
    return pd.Timestamp(s).tz_convert("UTC"), pd.Timestamp(e).tz_convert("UTC")


def session_bars(hdf: pd.DataFrame, sym: str, cls: str, day):
    s, e = session_window(sym, cls, day)
    b = hdf[(hdf.index >= s) & (hdf.index < e)]
    if cls == "index" and sym in US_FUT:      # hourly futures bars start on the hour: first one at/after 09:30 NY
        b = b[b.index >= s]
    return b, s, e


def fetch_hourly(ysym: str) -> pd.DataFrame:
    last = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            url = f"https://{host}/v8/finance/chart/{urllib.request.quote(ysym)}?range=5d&interval=60m"
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
                res = json.load(r)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close")},
                              index=pd.to_datetime(res["timestamp"], unit="s", utc=True)).dropna()
            return df[~df.index.duplicated(keep="last")]
        except Exception as ex:
            last = ex
    raise RuntimeError(f"{ysym}: {last}")


def plan_for(row: dict, hdf: pd.DataFrame, now: pd.Timestamp) -> dict:
    cls, sym = row["asset_class"], row["symbol"]
    rule = RULES[cls]; score = row["score"]; price = row["price"]
    atr = (row.get("atr14_pct") or 0) / 100 * price
    tz = NY if (cls == "index" and sym in US_FUT) else UK
    day = now.tz_convert(tz).date()
    s, e = session_window(sym, cls, day)
    if now >= e:   # today's session is over: show the next one, keep today's result
        done_bars, _, _ = session_bars(hdf, sym, cls, day)
    else:
        done_bars = None
    out = {"symbol": sym, "asset_class": cls, "rule": rule["name"], "score": score, "atr": round(atr, 6),
           "session_date": str(day), "session_start_utc": s.isoformat(), "session_end_utc": e.isoformat(),
           "bias": "bullish" if score >= rule["bias"] else "bearish" if score <= -rule["bias"] else None}
    if out["bias"] is None:
        out["status"] = "no setup (daily score not strong enough)"
        return out
    bull = out["bias"] == "bullish"
    bars, _, _ = session_bars(hdf, sym, cls, day)
    complete = now >= e
    t = intraday_trade(bars["open"].values, bars["high"].values, bars["low"].values, bars["close"].values,
                       bull, rule["kind"], atr, rule["stop_atr"], rule["target_r"], COST[cls], complete)
    if now < s:
        t["status"] = "waiting for session open"
    out.update(t)
    if rule["kind"] == "open":
        out["plan"] = {"stop_points": round(rule["stop_atr"] * atr, 6), "target_points": round(rule["stop_atr"] * atr * rule["target_r"], 6),
                       "example_entry": price, "example_stop": round(price - rule["stop_atr"] * atr if bull else price + rule["stop_atr"] * atr, 6),
                       "example_target": round(price + 2 * rule["stop_atr"] * atr if bull else price - 2 * rule["stop_atr"] * atr, 6)}
    return out


def main() -> int:
    from run import WATCHLIST
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--out", required=True); ap.add_argument("--prev")
    a = ap.parse_args()
    data = json.load(open(a.data))
    prev = {}
    if a.prev:
        try: prev = json.load(open(a.prev))
        except Exception as ex: print("no usable previous intraday file:", ex, file=sys.stderr)
    ysym = {sym: y for y, sym, _, cls in WATCHLIST if cls in RULES}
    now = pd.Timestamp.now(tz="UTC")
    plans, errors = [], []
    for row in data.get("assets", []):
        if row.get("symbol") not in ysym or row.get("status") != "ok" or row.get("stale"):
            continue
        try:
            plans.append(plan_for(row, fetch_hourly(ysym[row["symbol"]]), now))
        except Exception as ex:
            errors.append(f"{row['symbol']}: {ex}")
        time.sleep(0.3)
    hist = {(h["symbol"], h["session_date"]): h for h in prev.get("history", [])}
    for p in plans:
        if not prev:     # first run: start the live log from the next session, not one already under way
            break
        if p.get("r") is not None and p.get("status") in ("stopped", "target hit", "closed at session end"):
            hist[(p["symbol"], p["session_date"])] = {k: p.get(k) for k in ("symbol", "asset_class", "session_date", "bias", "entry", "stop", "target", "status", "r")}
    history = sorted(hist.values(), key=lambda h: (h["session_date"], h["symbol"]))[-300:]
    rs = [h["r"] for h in history]
    out = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "started": prev.get("started") or now.strftime("%Y-%m-%d"),
           "plans": plans, "history": history,
           "summary": {"closed": len(rs), "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
                       "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else None},
           "errors": errors}
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    print(f"intraday: plans {len(plans)}  live sessions logged {len(rs)}  errors {len(errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
