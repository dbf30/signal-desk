"""
Signal engine for stocks, forex and crypto (daily bars).

Only signals with published empirical support are scored:
  - Time-series momentum, 12-1 month (Moskowitz, Ooi & Pedersen 2012)      stocks, FX
  - 3-month momentum                                                     stocks, FX
  - Price vs 200-day moving average (Faber 2007; trend-following lit.)   all
  - 50/200-day moving-average alignment                                  stocks, FX
  - Short-term reversal / RSI(2) extremes (short-term reversal lit.)     stocks only, small weight
  - Crypto 1-week and 4-week momentum, attention (Liu & Tsyvinski 2021)  crypto
  - Crypto market context (added Nov 2026 after Signal Desk's own tests): US stocks' trend
    (S&P 500 vs its 200-day average) and, for altcoins, Bitcoin's own score; 15% each.
    Liu, Tsyvinski & Wu (2022) crypto market factor; crypto-equity correlation since 2020.
Candlestick and chart-pattern signals are deliberately NOT scored: bootstrap
studies (Marshall, Young & Rose 2006) found no predictive power. News/social sentiment
(Fear & Greed, GDELT news tone/volume, big-account news, Wikipedia attention) was tested in
Nov 2026 and did not improve the score, so it is shown as context only.

Output score is -100 (strong bearish) .. +100 (strong bullish).
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

# ---------------------------------------------------------------- weights
WEIGHTS = {
    "stock": {"mom_12_1": 0.30, "mom_3m": 0.20, "trend_200": 0.25, "ma_align": 0.15, "reversal": 0.10},
    "fx":    {"mom_12_1": 0.35, "mom_3m": 0.25, "trend_200": 0.25, "ma_align": 0.15},
    # commodity futures: same trend blend as FX, fixed before testing (Moskowitz, Ooi & Pedersen 2012
    # found time-series momentum in all 24 commodity futures they tested)
    "commodity": {"mom_12_1": 0.35, "mom_3m": 0.25, "trend_200": 0.25, "ma_align": 0.15},
    # stock index futures/CFDs: same blend as single stocks; government bond futures: same as FX
    "index": {"mom_12_1": 0.30, "mom_3m": 0.20, "trend_200": 0.25, "ma_align": 0.15, "reversal": 0.10},
    "bond": {"mom_12_1": 0.35, "mom_3m": 0.25, "trend_200": 0.25, "ma_align": 0.15},
    "crypto": {"mom_1w": 0.30, "mom_4w": 0.25, "trend_50": 0.20, "trend_200": 0.15, "attention": 0.10},
}

LABELS = [(40, "Bullish"), (15, "Leaning bullish"), (-15, "Neutral"), (-40, "Leaning bearish"), (-101, "Bearish")]

SIGNAL_TEXT = {
    "mom_12_1": "12-month trend (skip last month)",
    "mom_3m": "3-month momentum",
    "trend_200": "Price vs 200-day average",
    "trend_50": "Price vs 50-day average",
    "ma_align": "50-day vs 200-day average",
    "reversal": "Short-term stretch (RSI-2)",
    "mom_1w": "1-week momentum",
    "mom_4w": "4-week momentum",
    "attention": "Volume / attention surge",
    "risk_regime": "US stocks' trend (S&P 500 vs 200-day)",
    "btc_factor": "Bitcoin's trend (crypto market)",
}

CONTEXT_W = 0.15          # weight of each crypto context signal (tested, fixed in advance)


def _blend_context(out: pd.DataFrame, context: dict) -> pd.DataFrame:
    """new score = (0.70 * chart score + 0.15 * 100 * risk_regime + 0.15 * btc_factor) / available weight"""
    idx = out.index
    num = out["score"] * (1 - 2 * CONTEXT_W)
    den = pd.Series(1 - 2 * CONTEXT_W, index=idx)
    for key in ("risk_regime", "btc_factor"):
        s = context.get(key)
        if s is None:
            continue
        x = s.sort_index().reindex(idx, method="ffill")
        if key == "btc_factor":
            x = x / 100.0
        out[key] = x
        num = num + np.where(x.notna(), 100 * CONTEXT_W * x, 0.0)
        den = den + np.where(x.notna(), CONTEXT_W, 0.0)
    out["chart_score"] = out["score"]
    out["ctx_den"] = den
    out["score"] = np.where(out["chart_score"].notna(), num / den, np.nan)
    return out


def label_for(score: float) -> str:
    for threshold, name in LABELS:
        if score >= threshold:
            return name
    return "Bearish"


# ---------------------------------------------------------------- indicators
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi_wilder(close: pd.Series, n: int) -> pd.Series:
    """Wilder's RSI: first average is a simple mean of n changes, then Wilder smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = pd.Series(np.nan, index=close.index)
    avg_loss = pd.Series(np.nan, index=close.index)
    if len(close) <= n:
        return avg_gain
    avg_gain.iloc[n] = gain.iloc[1:n + 1].mean()
    avg_loss.iloc[n] = loss.iloc[1:n + 1].mean()
    g, l = avg_gain.iloc[n], avg_loss.iloc[n]
    for i in range(n + 1, len(close)):
        g = (g * (n - 1) + gain.iloc[i]) / n
        l = (l * (n - 1) + loss.iloc[i]) / n
        avg_gain.iloc[i], avg_loss.iloc[i] = g, l
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    out[(avg_loss == 0) & avg_gain.notna()] = 100.0
    return out


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    out = pd.Series(np.nan, index=close.index)
    if len(close) <= n:
        return out
    a = tr.iloc[1:n + 1].mean()
    out.iloc[n] = a
    for i in range(n + 1, len(close)):
        a = (a * (n - 1) + tr.iloc[i]) / n
        out.iloc[i] = a
    return out


# ---------------------------------------------------------------- signal series
def _z_tanh(logret: pd.Series, vol: pd.Series, horizon: int) -> pd.Series:
    """Momentum expressed in units of its own volatility over the horizon, squashed to -1..1."""
    return np.tanh(logret / (vol * math.sqrt(horizon)))


def signal_frame(df: pd.DataFrame, asset_class: str, context: dict | None = None) -> pd.DataFrame:
    """df: index = date (ascending), columns open, high, low, close, volume (volume may be NaN).
    context (crypto only, optional): {"risk_regime": Series of -1/0/+1 on its own dates,
    "btc_factor": Series of Bitcoin's chart score -100..100}. Both are forward-filled onto df's dates.
    Returns a frame of per-signal values in -1..1 plus the weighted score, for every bar."""
    c = df["close"].astype(float)
    lr = np.log(c).diff()
    vol20 = lr.rolling(20, min_periods=20).std()
    vol63 = lr.rolling(63, min_periods=63).std()
    vol252 = lr.rolling(252, min_periods=200).std()
    sma50, sma200 = sma(c, 50), sma(c, 200)
    out = pd.DataFrame(index=df.index)

    if asset_class in ("stock", "fx", "commodity", "index", "bond"):
        out["mom_12_1"] = _z_tanh(np.log(c.shift(21) / c.shift(252)), vol252, 231)
        out["mom_3m"] = _z_tanh(np.log(c / c.shift(63)), vol63, 63)
        out["trend_200"] = _z_tanh(np.log(c / sma200), vol20, 20)
        slope200 = np.sign(sma200 - sma200.shift(20))
        align = np.sign(sma50 - sma200)
        out["ma_align"] = np.where(align == slope200, align, align * 0.5)
        out.loc[sma200.isna(), "ma_align"] = np.nan
        if asset_class in ("stock", "index"):
            r2 = rsi_wilder(c, 2)
            rev = pd.Series(0.0, index=c.index)
            rev[r2 < 10] = (10 - r2[r2 < 10]) / 10
            rev[r2 > 90] = -(r2[r2 > 90] - 90) / 10
            rev[r2.isna()] = np.nan
            out["reversal"] = rev
            out["rsi2"] = r2
    elif asset_class == "crypto":
        out["mom_1w"] = _z_tanh(np.log(c / c.shift(7)), vol63, 7)
        out["mom_4w"] = _z_tanh(np.log(c / c.shift(28)), vol63, 28)
        out["trend_50"] = _z_tanh(np.log(c / sma50), vol20, 20)
        out["trend_200"] = _z_tanh(np.log(c / sma200), vol20, 20)
        v = df["volume"].astype(float) if "volume" in df else pd.Series(np.nan, index=df.index)
        if v.notna().sum() > 120 and (v > 0).sum() > 120:
            v7, v90 = v.rolling(7).mean(), v.rolling(90).mean()
            v90sd = v.rolling(90).std()
            volz = (v7 - v90) / (v90sd / math.sqrt(7))
            out["attention"] = np.tanh(volz.clip(lower=0) / 4) * np.sign(np.log(c / c.shift(7)))
        else:
            out["attention"] = np.nan
    else:
        raise ValueError(f"unknown asset class {asset_class}")

    w = WEIGHTS[asset_class]
    cols = list(w)
    vals = out[cols]
    wvec = pd.Series(w)
    avail = vals.notna().mul(wvec, axis=1).sum(axis=1)
    raw = vals.fillna(0).mul(wvec, axis=1).sum(axis=1)
    # Renormalise if an optional signal (attention) is missing; require core coverage >= 75%.
    out["score"] = np.where(avail >= 0.75, 100 * raw / avail, np.nan)
    out["vol20"], out["vol252"] = vol20, vol252
    out["sma50"], out["sma200"] = sma50, sma200
    out["rsi14"] = rsi_wilder(c, 14)
    if asset_class == "crypto" and context:
        out = _blend_context(out, context)
    return out


# ---------------------------------------------------------------- honesty check (backtest)
def backtest(sig: pd.DataFrame, close: pd.Series, horizon: int, threshold: float = 15.0) -> dict:
    """How often did the label call the next `horizon` bars' direction correctly, vs just
    guessing 'up' every time? Uses only bars with a full signal history."""
    fwd = np.log(close.shift(-horizon) / close)
    d = pd.DataFrame({"score": sig["score"], "fwd": fwd}).dropna()
    # sample every `horizon` bars so outcomes don't overlap (keeps stats honest)
    d = d.iloc[::horizon]
    if len(d) < 20:
        return {"samples": int(len(d))}
    bull, bear = d[d.score >= threshold], d[d.score <= -threshold]
    base_up = float((d.fwd > 0).mean())
    calls = pd.concat([bull.fwd > 0, bear.fwd < 0])
    return {
        "samples": int(len(d)),
        "horizon_bars": horizon,
        "base_rate_up": round(base_up, 3),
        "bull_calls": int(len(bull)),
        "bull_hit": round(float((bull.fwd > 0).mean()), 3) if len(bull) else None,
        "bear_calls": int(len(bear)),
        "bear_hit": round(float((bear.fwd < 0).mean()), 3) if len(bear) else None,
        "overall_hit": round(float(calls.mean()), 3) if len(calls) else None,
        "avg_fwd_when_bull": round(float(bull.fwd.mean()) * 100, 2) if len(bull) else None,
        "avg_fwd_when_bear": round(float(bear.fwd.mean()) * 100, 2) if len(bear) else None,
        "from": str(d.index[0])[:10],
        "to": str(d.index[-1])[:10],
    }


# ---------------------------------------------------------------- summary for one asset
def analyse(symbol: str, name: str, asset_class: str, df: pd.DataFrame, context: dict | None = None) -> dict:
    df = df.sort_index()
    sig = signal_frame(df, asset_class, context)
    last = sig.iloc[-1]
    c = df["close"].astype(float)
    w = WEIGHTS[asset_class]
    score = last["score"]
    if pd.isna(score):
        return {"symbol": symbol, "name": name, "asset_class": asset_class, "status": "not enough history",
                "bars": int(len(df))}

    reasons = []
    den = float(last["ctx_den"]) if "ctx_den" in last and pd.notna(last.get("ctx_den")) else None
    avail_core = sum(wt for k, wt in w.items() if pd.notna(last.get(k)))
    core_scale = ((1 - 2 * CONTEXT_W) / den if den else 1.0) / (avail_core or 1.0)
    for k, wt in w.items():
        v = last.get(k)
        if pd.isna(v):
            continue
        reasons.append({"signal": SIGNAL_TEXT[k], "key": k, "value": round(float(v), 2), "weight": round(wt * core_scale, 3),
                        "contribution": round(100 * wt * core_scale * float(v), 1)})
    for k in ("risk_regime", "btc_factor"):
        v = last.get(k)
        if den and v is not None and pd.notna(v):
            reasons.append({"signal": SIGNAL_TEXT[k], "key": k, "value": round(float(v), 2), "weight": round(CONTEXT_W / den, 3),
                            "contribution": round(100 * CONTEXT_W / den * float(v), 1)})
    reasons.sort(key=lambda r: -abs(r["contribution"]))

    agree = sum(r["weight"] for r in reasons if np.sign(r["value"]) == np.sign(score))
    total = sum(r["weight"] for r in reasons)
    vol_ratio = float(last["vol20"] / last["vol252"]) if pd.notna(last["vol252"]) and last["vol252"] > 0 else None
    flags = []
    if vol_ratio and vol_ratio > 1.5:
        flags.append("Volatility is running well above normal: signals are less reliable and swings are bigger.")
    if asset_class == "fx":
        flags.append("FX: Signal Desk's own test found no edge for these signals on currencies since 2021 (calls right about 50% of the time). Treat as no conviction.")
    if asset_class == "stock" and score <= -15:
        flags.append("Tested since 1980: after bearish stock signals, prices still rose more often than not (calls right 42%). Read this as 'step aside', not 'will fall'.")
    if asset_class == "crypto" and score <= -15:
        flags.append("Tested: shorting crypto on bearish signals lost money; staying out did much better than holding (worst drop -39% vs -87%).")
    if asset_class == "index" and score <= -15:
        flags.append("Tested since 2005: bearish setups on stock indices lost money on average; read bearish as 'step aside', not 'will fall'.")
    if asset_class == "bond":
        flags.append("Tested: on Treasury futures and bond funds this trend score worked best as 'hold or step aside' (since 2016 Sharpe 0.53 vs 0.17 just holding; worst fall -9% vs -31%).")
    if asset_class == "commodity":
        flags.append("Commodities: Signal Desk's test found this trend score beat holding before 2016 but has had little edge since (gold has been the most consistent). Treat as low conviction.")
        flags.append("Prices are the front-month futures contract, which can jump when it rolls to the next month, especially oil and natural gas.")
    rsi14 = float(last["rsi14"]) if pd.notna(last["rsi14"]) else None
    if rsi14 is not None and (rsi14 > 75 or rsi14 < 25):
        flags.append(f"RSI(14) is {rsi14:.0f}: price is stretched short-term, so chasing it here carries pullback risk.")

    conf = agree / total if total else 0
    if vol_ratio and vol_ratio > 1.5:
        conf *= 0.8
    if asset_class in ("fx", "commodity"):
        conf *= 0.85
    confidence = "High" if conf >= 0.8 and abs(score) >= 40 else "Medium" if conf >= 0.6 else "Low"

    prev = sig["score"].dropna()
    score_5d_ago = float(prev.iloc[-6]) if len(prev) > 6 else None
    horizon = 20 if asset_class != "crypto" else 28

    atr = atr_wilder(df["high"].astype(float), df["low"].astype(float), c).iloc[-1]
    return {
        "symbol": symbol, "name": name, "asset_class": asset_class, "status": "ok",
        "as_of": str(df.index[-1])[:10],
        "price": round(float(c.iloc[-1]), 6),
        "chg_1d_pct": round(100 * float(c.iloc[-1] / c.iloc[-2] - 1), 2),
        "score": round(float(score), 1),
        "label": label_for(float(score)),
        "score_5d_ago": round(score_5d_ago, 1) if score_5d_ago is not None else None,
        "label_5d_ago": label_for(score_5d_ago) if score_5d_ago is not None else None,
        "confidence": confidence,
        "agreement_pct": round(100 * agree / total) if total else None,
        "rsi14": round(rsi14, 1) if rsi14 is not None else None,
        "sma50": round(float(last["sma50"]), 6) if pd.notna(last["sma50"]) else None,
        "sma200": round(float(last["sma200"]), 6) if pd.notna(last["sma200"]) else None,
        "atr14_pct": round(100 * float(atr / c.iloc[-1]), 2) if pd.notna(atr) else None,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
        "reasons": reasons,
        "flags": flags,
        "backtest": backtest(sig, c, horizon),
        "history": [
            {"date": str(i)[:10], "close": round(float(c.loc[i]), 6),
             "sma50": None if pd.isna(sig.loc[i, "sma50"]) else round(float(sig.loc[i, "sma50"]), 6),
             "sma200": None if pd.isna(sig.loc[i, "sma200"]) else round(float(sig.loc[i, "sma200"]), 6),
             "score": None if pd.isna(sig.loc[i, "score"]) else round(float(sig.loc[i, "score"]), 1)}
            for i in df.index[-180:]
        ],
    }


def alerts(prev_rows: dict[str, dict], new_rows: list[dict]) -> list[str]:
    """Alert when an asset moves into or out of a full Bullish/Bearish state, or flips sign strongly."""
    msgs = []
    for r in new_rows:
        if r.get("status") != "ok":
            continue
        p = prev_rows.get(r["symbol"])
        if not p or p.get("status") != "ok":
            continue
        a, b = p["label"], r["label"]
        if a == b:
            continue
        strong = {"Bullish", "Bearish"}
        if b in strong or a in strong or (p["score"] * r["score"] < 0 and abs(r["score"]) >= 15):
            msgs.append(f"{r['symbol']}: {a} -> {b} (score {p['score']:+.0f} -> {r['score']:+.0f})")
    return msgs
