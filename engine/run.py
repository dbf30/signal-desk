"""
Fetch daily bars from Yahoo Finance's chart API (stdlib only), run the engine, write data.json.

Usage:  python3 run.py [--prev previous_data.json] [--out data.json]
Writes alerts (one per line) to alerts.txt next to the output.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from engine import analyse, alerts, signal_frame

WATCHLIST = [
    # (yahoo symbol, display symbol, name, asset class)
    ("SPY", "SPY", "S&P 500 (ETF)", "stock"),
    ("QQQ", "QQQ", "Nasdaq 100 (ETF)", "stock"),
    ("AAPL", "AAPL", "Apple", "stock"),
    ("MSFT", "MSFT", "Microsoft", "stock"),
    ("NVDA", "NVDA", "Nvidia", "stock"),
    ("AMZN", "AMZN", "Amazon", "stock"),
    ("TSLA", "TSLA", "Tesla", "stock"),
    ("ES=F", "US500", "S&P 500 futures (ES, CME)", "index"),
    ("NQ=F", "NAS100", "Nasdaq 100 futures (NQ, CME)", "index"),
    ("YM=F", "US30", "Dow Jones futures (YM, CBOT)", "index"),
    ("RTY=F", "US2000", "Russell 2000 futures (RTY, CME)", "index"),
    ("^GDAXI", "GER40", "DAX 40 index (Germany)", "index"),
    ("^FTSE", "UK100", "FTSE 100 index (UK)", "index"),
    ("EURUSD=X", "EUR/USD", "Euro / US dollar", "fx"),
    ("GBPUSD=X", "GBP/USD", "Pound / US dollar", "fx"),
    ("JPY=X", "USD/JPY", "US dollar / Yen", "fx"),
    ("AUDUSD=X", "AUD/USD", "Aussie / US dollar", "fx"),
    ("GC=F", "GOLD", "Gold futures ($/oz, COMEX)", "commodity"),
    ("SI=F", "SILVER", "Silver futures ($/oz, COMEX)", "commodity"),
    ("CL=F", "WTI", "WTI crude oil futures ($/barrel, NYMEX)", "commodity"),
    ("NG=F", "NATGAS", "Natural gas futures ($/MMBtu, NYMEX)", "commodity"),
    ("HG=F", "COPPER", "Copper futures ($/lb, COMEX)", "commodity"),
    ("ZC=F", "CORN", "Corn futures (cents/bushel, CBOT)", "commodity"),
    ("ZW=F", "WHEAT", "Wheat futures (cents/bushel, CBOT)", "commodity"),
    ("ZS=F", "SOYBEAN", "Soybean futures (cents/bushel, CBOT)", "commodity"),
    ("ZT=F", "ZT", "2-year US Treasury note futures (CBOT)", "bond"),
    ("ZF=F", "ZF", "5-year US Treasury note futures (CBOT)", "bond"),
    ("ZN=F", "ZN", "10-year US Treasury note futures (CBOT)", "bond"),
    ("ZB=F", "ZB", "30-year US Treasury bond futures (CBOT)", "bond"),
    ("BTC-USD", "BTC", "Bitcoin", "crypto"),
    ("ETH-USD", "ETH", "Ethereum", "crypto"),
    ("SOL-USD", "SOL", "Solana", "crypto"),
    ("XRP-USD", "XRP", "XRP", "crypto"),
]

HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


def fetch_yahoo(sym: str, rng: str = "10y") -> pd.DataFrame:
    last_err = None
    for host in HOSTS:
        url = f"https://{host}/v8/finance/chart/{urllib.request.quote(sym)}?range={rng}&interval=1d&includeAdjustedClose=true"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.load(r)
            res = j["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(None).normalize()
            df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"],
                               "close": q["close"], "volume": q.get("volume")}, index=idx)
            if adj and len(adj) == len(df):
                # use split/dividend-adjusted closes; scale OHLC by the same factor
                f = pd.Series(adj, index=idx) / df["close"]
                for col in ("open", "high", "low", "close"):
                    df[col] = df[col] * f
            df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            if len(df) < 50:
                raise ValueError(f"only {len(df)} bars")
            return df
        except Exception as e:  # try the next host
            last_err = e
    raise RuntimeError(f"{sym}: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev", default=None)
    ap.add_argument("--out", default="data.json")
    a = ap.parse_args()

    prev_rows = {}
    if a.prev:
        try:
            with open(a.prev) as f:
                prev_rows = {r["symbol"]: r for r in json.load(f).get("assets", [])}
        except Exception as e:
            print("no usable previous data:", e, file=sys.stderr)

    rows, errors = [], []
    ctx = {}   # crypto market context: US stocks' trend (from SPY) and Bitcoin's chart score
    for ysym, sym, name, cls in WATCHLIST:
        try:
            df = fetch_yahoo(ysym)
            if ysym == "SPY":
                c = df["close"].sort_index()
                ma = c.rolling(200, min_periods=200).mean()
                ctx["risk_regime"] = np.sign(c - ma).where(ma.notna())
            context = None
            if cls == "crypto":
                context = {"risk_regime": ctx.get("risk_regime")}
                if ysym == "BTC-USD":
                    ctx["btc_factor"] = signal_frame(df.sort_index(), "crypto")["score"]
                else:
                    context["btc_factor"] = ctx.get("btc_factor")
            row = analyse(sym, name, cls, df, context)
            row["source"] = f"Yahoo Finance daily bars ({ysym})"
            rows.append(row)
        except Exception as e:
            errors.append(str(e))
            if sym in prev_rows:  # keep last good row, marked stale
                old = dict(prev_rows[sym]); old["stale"] = True; rows.append(old)
        time.sleep(0.4)

    al = alerts(prev_rows, rows)
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assets": rows,
        "alerts": al,
        "errors": errors,
    }
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    outdir = a.out.rsplit("/", 1)[0] + "/" if "/" in a.out else ""
    with open(outdir + "alerts.txt", "w") as f:
        f.write("\n".join(al))
    # small file holding just the labels, read back next run to detect changes
    state = {"generated_at": out["generated_at"],
             "assets": [{k: r.get(k) for k in ("symbol", "status", "label", "score")} for r in rows]}
    with open(outdir + "state.json", "w") as f:
        json.dump(state, f, separators=(",", ":"))
    ok = sum(1 for r in rows if r.get("status") == "ok" and not r.get("stale"))
    print(f"assets ok: {ok}/{len(WATCHLIST)}  alerts: {len(al)}  errors: {len(errors)}")
    for e in errors:
        print("ERROR", e)
    for m in al:
        print("ALERT", m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
