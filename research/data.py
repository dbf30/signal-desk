"""Fetch max history for watchlist + unseen assets + benchmarks; compute scores (engine.signal_frame, unchanged)."""
import sys, os, time, pickle
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import numpy as np, pandas as pd
from run import WATCHLIST, fetch_yahoo
from engine import signal_frame

OUT = os.path.dirname(os.path.abspath(__file__))

UNSEEN = [
    ("JPM","JPM","stock"),("XOM","XOM","stock"),("JNJ","JNJ","stock"),("PG","PG","stock"),("KO","KO","stock"),
    ("HD","HD","stock"),("CAT","CAT","stock"),("WMT","WMT","stock"),("INTC","INTC","stock"),("CSCO","CSCO","stock"),
    ("^N225","JP225","index"),("^HSI","HK50","index"),("^STOXX50E","EU50","index"),("^AXJO","AUS200","index"),
    ("CAD=X","USD/CAD","fx"),("NZDUSD=X","NZD/USD","fx"),("CHF=X","USD/CHF","fx"),("EURJPY=X","EUR/JPY","fx"),
    ("HO=F","HEATOIL","commodity"),("RB=F","GASOLINE","commodity"),("PL=F","PLATINUM","commodity"),("PA=F","PALLADIUM","commodity"),
    ("KC=F","COFFEE","commodity"),("SB=F","SUGAR","commodity"),("CC=F","COCOA","commodity"),("CT=F","COTTON","commodity"),
    ("LE=F","CATTLE","commodity"),("HE=F","HOGS","commodity"),
    ("TLT","TLT","bond"),("IEF","IEF","bond"),("TIP","TIP","bond"),("LQD","LQD","bond"),
    ("ADA-USD","ADA","crypto"),("DOGE-USD","DOGE","crypto"),("LTC-USD","LTC","crypto"),("BCH-USD","BCH","crypto"),
    ("LINK-USD","LINK","crypto"),("BNB-USD","BNB","crypto"),("XLM-USD","XLM","crypto"),("TRX-USD","TRX","crypto"),
]
BENCH = [("SPY","SPY_BH"),("DBMF","DBMF"),("KMLM","KMLM")]

import json, urllib.request
def fetch_daily(sym):
    """same parsing as run.fetch_yahoo, but with an explicit daily date range (range=max returns monthly bars)"""
    last = None
    for host in ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]:
        url = f"https://{host}/v8/finance/chart/{urllib.request.quote(sym)}?period1=946684800&period2=1794355200&interval=1d&includeAdjustedClose=true"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                j = json.load(r)
            res = j["chart"]["result"][0]; q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(None).normalize()
            df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "volume": q.get("volume")}, index=idx)
            if adj and len(adj) == len(df):
                f = pd.Series(adj, index=idx) / df["close"]
                for col in ("open", "high", "low", "close"):
                    df[col] = df[col] * f
            df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            return df
        except Exception as e:
            last = e
    raise RuntimeError(f"{sym}: {last}")

FIXES = {}
def clean(df, sym):
    """Remove bad ticks: wicks or opens more than 5 typical ranges from the bar body / both closes, and one-day close spikes that fully revert."""
    df = df.copy(); n0 = 0
    for _ in range(2):
        pc = df["close"].shift(1); nc = df["close"].shift(-1)
        tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
        a = tr.rolling(20, min_periods=5).median().shift(1)
        spike = ((df.close - pc).abs() > 6 * a) & ((nc - pc).abs() < 2 * a)
        df.loc[spike, "close"] = ((pc + nc) / 2)[spike]; n0 += int(spike.sum())
        bad_open = ((df.open - pc).abs() > 5 * a) & ((df.open - df.close).abs() > 5 * a)
        df.loc[bad_open, "open"] = pc[bad_open]; n0 += int(bad_open.sum())
        bh = df[["open", "close"]].max(axis=1); bl = df[["open", "close"]].min(axis=1)
        hi_bad = df.high > bh + 5 * a; lo_bad = df.low < bl - 5 * a
        df.loc[hi_bad, "high"] = bh[hi_bad]; df.loc[lo_bad, "low"] = bl[lo_bad]; n0 += int(hi_bad.sum() + lo_bad.sum())
        df["high"] = df[["high", "open", "close"]].max(axis=1); df["low"] = df[["low", "open", "close"]].min(axis=1)
    FIXES[sym] = n0
    return df

def get(y):
    for _ in range(3):
        try:
            return fetch_daily(y).sort_index()
        except Exception as e:
            err = e; time.sleep(2)
    raise err

assets = {}
for y, sym, name, cls in WATCHLIST:
    assets[sym] = {"cls": cls, "set": "watch", "df": clean(get(y), sym)}; time.sleep(0.3)
for y, sym, cls in UNSEEN:
    try:
        assets[sym] = {"cls": cls, "set": "unseen", "df": clean(get(y), sym)}
    except Exception as e:
        print("skip", sym, e)
    time.sleep(0.3)
bench = {}
for y, sym in BENCH:
    bench[sym] = get(y)["close"]

spy = assets["SPY"]["df"]["close"]; ma = spy.rolling(200, min_periods=200).mean()
regime = np.sign(spy - ma).where(ma.notna())
btc = assets["BTC"]["df"]["close"]; bma = btc.rolling(200, min_periods=200).mean()
btc_regime = np.sign(btc - bma).where(bma.notna())
btc_factor = signal_frame(assets["BTC"]["df"], "crypto")["score"]
for sym, a in assets.items():
    ctx = None
    if a["cls"] == "crypto":
        ctx = {"risk_regime": regime}
        if sym != "BTC":
            ctx["btc_factor"] = btc_factor
    sf = signal_frame(a["df"], a["cls"], ctx)
    a["score"] = sf["score"]
    a["volratio"] = sf["vol20"] / sf["vol252"]
    print(sym, a["cls"], a["set"], str(a["df"].index[0])[:10], len(a["df"]), flush=True)

pickle.dump({"assets": assets, "bench": bench, "spy_regime": regime, "btc_regime": btc_regime}, open(os.path.join(OUT, "data.pkl"), "wb"))
print("saved", len(assets)); print("bar fixes:", {k: v for k, v in FIXES.items() if v}, "total", sum(FIXES.values()), "of", sum(len(a["df"]) for a in assets.values()))
