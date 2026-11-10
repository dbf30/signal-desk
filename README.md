# Signal Desk

[![tests](https://github.com/dbf30/signal-desk/actions/workflows/tests.yml/badge.svg)](https://github.com/dbf30/signal-desk/actions/workflows/tests.yml) [![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

**Live demo:** [dbf30.github.io/signal-desk](https://dbf30.github.io/signal-desk/), a snapshot from 10 November 2026.

Signal Desk is a daily trend-scoring engine and dashboard for 33 markets across stocks, stock indices, FX, commodities, US Treasury futures and crypto. Each market gets a score from −100 (bearish) to +100 (bullish), built only from signals with published empirical support. Scheduled runs refresh the score from Yahoo Finance daily prices, alongside a catalyst feed of central-bank meetings, data releases, earnings and crypto token unlocks.

The project's main value is the research behind it. It tested whether the scores actually make money, and reported the results honestly.

## Research findings (November 2026)

The study was pre-registered: rules, markets and test periods were fixed before any results were seen. It used about 430,000 daily bars (2000–2026) across 73 markets, 40 of which were never used to design the rules. There was no look-ahead, every trade paid a per-asset trading cost, and the 2023–2026 holdout was tested once only.

| Strategy | Out-of-sample 2023–2026 | Verdict |
|---|---|---|
| Long-only trend portfolio, volatility-targeted | Sharpe 1.17, 8.0% a year, 7.1% max drawdown | Works, and beat the DBMF and KMLM managed-futures ETFs |
| Simply holding the same markets, no score | Sharpe 1.62 | The trend score did **not** beat this |
| Swing setups (zone entries) | Best pre-registered version: Sharpe 0.04 | No edge, so kept off live capital |
| Short setups | Lost money in every variant | Dropped |

Notes on the trend portfolio:
- **Position sizing:** position = score / 100 × 40% / the market's recent volatility.
- **Market exposure:** its correlation to the S&P 500 is 0.65. Its return beyond that market exposure was +1.2% a year out of sample.

Integrity checks:
- **Data cleaning:** 319 bad ticks were corrected out of 430,145 bars.
- **Simulator check:** the backtest simulator reproduced the live app's code on all 4,000 test trades.
- **Random signals:** random signals showed no edge.
- **Delayed entries:** delaying entries degraded results as expected.
- **Look-ahead test:** on pure random walks, the engine's own track-record check has a hit rate of about 50% (tested in `test_engine.py`).

**Reproducing the study:** all the code, the pre-registrations and the raw results are in [`research/`](research/README.md).
- The rules were written down before any results: [`PREREG.md`](research/PREREG.md) for the swing setups and [`PREREG_TF.md`](research/PREREG_TF.md) for the trend portfolio.
- The holdout figures above come from [`research/results/tf_holdout.json`](research/results/tf_holdout.json) and [`holdout_results.json`](research/results/holdout_results.json).
- The always-long comparison, S&P 500 correlation, delay test and random-signal check are printed by `tf_checks.py`.

**Known caveat:** free futures data is not adjusted for contract rolls, so prices jump each time a futures contract rolls over. This can make short trades look worse than they are.

## How it works

| File | Role |
|---|---|
| `engine/engine.py` | Signal engine: computes each signal and the weighted score per asset class, plus each asset's own track record |
| `engine/run.py` | Downloads daily bars from Yahoo Finance's chart API (standard library only), runs the engine, writes `data.json` and alerts |
| `engine/levels.py` | Support/resistance from clustered swing highs and lows, and rule-based entry zones for strongly scored assets |
| `engine/trades.py` | Trade rules shared by the historical test and the live scorecard (entry, stop, signal-fade exit, result in R) |
| `engine/scorecard.py` | Live scorecard: logs each new setup and follows it with the same rules as the backtest |
| `engine/intraday.py` | Intraday crypto "London range breakout" setup, the one intraday rule that survived testing |
| `web/index.html` | The dashboard, which reads the JSON files in `web/` (a snapshot from 10 Nov 2026) |

The signals and the research they come from:
- **12-1 month time-series momentum** (Moskowitz, Ooi & Pedersen, 2012) and **3-month momentum**, used for stocks and FX.
- **Price vs the 200-day moving average** (Faber, 2007), used for all markets.
- **50/200-day moving-average alignment**, used for stocks and FX.
- **Short-term reversal / RSI(2) extremes**, used for stocks only, with a small weight.
- **Crypto 1-week and 4-week momentum** (Liu & Tsyvinski, 2021).
- **Crypto market context:** the trend of US stocks and, for altcoins, Bitcoin's own score.

## Run

```bash
pip install numpy pandas
cd engine
python3 run.py --out ../web/data.json                 # fetch prices and score every market
python3 levels.py --data ../web/data.json --out ../web/setups.json
for t in test_*.py; do python3 "$t"; done             # 5 test files
```

The dashboard is deployed to GitHub Pages from `web/`. To view it locally, serve `web/` with any static file server (for example `python3 -m http.server -d web`).

## Limitations

- **The holdout is short.** 2023–2026 is less than four years, and it was a bull market. The unseen stocks and coins are today's survivors, and there are no financing or swap costs.
- **Data:** Yahoo Finance prices are free, but they have gaps and bad ticks, and futures are not roll-adjusted.
- **Not investment advice.** It's a personal research project.

## How this was built

Built with AI pair-programming (Claude). I set the goals and the research questions, reviewed the results, and can explain every component.
