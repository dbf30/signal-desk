# Signal Desk research

The scripts behind the Signal Desk Research Report (10 Nov 2026). They test the app's swing setups (Study 1) and the daily score used as a trend-following portfolio (Study 2). Rules were written down before each test, tuned on 2010–2022 and judged once on 2023–2026 and on 40 markets never used in building anything.

`engine/` holds an unchanged copy of the app's engine (`engine.py`, `run.py`, `levels.py`, `trades.py`, `scorecard.py`, `intraday.py`) so results are reproducible against the exact code tested.

## Requirements

Python 3.11+, `numpy`, `pandas`, and network access to `query1.finance.yahoo.com` / `query2.finance.yahoo.com`.

## Run order

All outputs are written next to the scripts. The intermediate `.pkl` files are large and are not committed.

| Step | Script | What it does | Output |
| --- | --- | --- | --- |
| 1 | `data.py` | Downloads daily history from 2000 for 73 markets + benchmarks, cleans bad ticks, computes the engine's scores | `data.pkl` |
| 2 | `setups.py` | Builds every daily setup (score at ±40 or beyond) and checks it against `levels.analyse_levels` | `setups.pkl` |
| 3 | `gen.py` | Simulates every setup under each trade-rule variant and checks `sim.py` against `trades.simulate_trade` | `sim_*.pkl` |
| 4 | `dev.py` | Study 1: all pre-registered variants on 2010–2022 | `dev_results.csv` |
| 5 | `holdout.py` | Study 1: the selected version, once, on 2023–2026 and unseen markets | `holdout_results.json` |
| 6 | `tf.py` | Study 2: trend-portfolio variants on 2010–2022 | `tf_dev.json` |
| 7 | `tf_hold.py` | Study 2: the selected version, once, on the holdout + benchmarks | `tf_holdout.json` |
| 8 | `tf_checks.py` | Always-long comparison, S&P 500 beta, one-week delay test, random-signal placebo | printed |

### v2 study (11 Nov 2026, `PREREG_V2.md`)

| Step | Script | What it does | Output |
| --- | --- | --- | --- |
| 9 | `features.py` | Adds setup features (distance to zone, room to next level, anchor touches, stretch, volatility ratio, backdrop) | `features.pkl` |
| 10 | `swing_v2.py dev` | Q1: closed-only bias replay, marked R by horizon, cost drag. Q2: factor tables on development data | `results/swing_v2_dev.json` |
| 11 | `grade_model.py fit` then `second` | Fits the grade model on 2010–2022 watchlist trades, then checks grades once on later and unseen data | `results/grade_model.json` |
| 12 | `grade_checks.py`, `grade_residuals.py` | Within-group checks, A+ by asset class and by year | `results/grade_checks.txt` |
| 13 | `fetch_hourly.py` | Two years of hourly bars for 12 coins | `hourly.pkl` |
| 14 | `intraday_v2.py DEV` etc. | Q3: the live intraday rule and five pre-listed variants | `results/intraday_v2_*.json` |

Read the audit note at the end of `PREREG_V2.md` before relying on the "second look" figures.

`sim.py` (trade simulator) and `portfolio.py` (selection, mark-to-market, metrics) are modules used by the steps above.

`backtest_3y.py` and `backtest_3y_stats.py` are the first quick three-year backtest of the current rules. It predates the data cleaning and the planned-risk fix, and is superseded by the scripts above.

## Pre-registration

`PREREG.md` (Study 1) and `PREREG_TF.md` (Study 2) list the variants and the selection rule, plus the development results recorded before each holdout run. `results/` holds the outputs from the 10 Nov 2026 run.

## Known limitations

- Yahoo continuous futures are not roll-adjusted.
- The unseen stocks and coins are today's survivors.
- The 2023–2026 holdout is short and was a bull market.
- There are no financing or swap costs.

See the report's Limitations section for details.
