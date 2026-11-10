# Signal Desk trend-following portfolio test (written 2026-11-10 19:35 UK, before any results)

Idea: use the app's daily score (engine.py, unchanged) directly as a long/short position in every market,
sized by volatility, held in a portfolio. No zones, no limit orders, no stops.

Data: same cleaned Yahoo daily closes as the swing research (data.pkl). Calendar days; non-trading days = 0 return.
Data-quality rule: an asset's daily return is capped at +/-6x its own trailing 63-day daily volatility
(continuous futures on Yahoo are not roll-adjusted, and WTI went negative in 2020).
Execution: position set from the score at the close of the last trading day of each week, earned from the next day.
No look-ahead. Costs: scorecard.COST per asset class, charged on every unit of notional traded.
Sizing: each asset's notional = weight x (40% / its trailing 63-day annualised volatility), averaged over the assets
with a score that day (Moskowitz, Ooi & Pedersen 2012 construction).

Variants:
- T1 continuous: weight = score / 100 (-1..+1)
- T2 labels: weight = +1 if score >= 15, -1 if score <= -15, else 0
- Long-only versions of the chosen one, to answer the bearish question.

Selection on development only (watchlist, 2010-01-01 .. 2022-12-31), by Sharpe (daily, x sqrt(365)):
1. Pick T1 or T2.
2. Keep shorts only if long/short Sharpe > long-only Sharpe in development.
3. Leverage: one fixed multiplier so development volatility = 10% a year; the same multiplier is used in the holdout.
Then judge ONCE: watchlist 2023-01-01 .. 2026-11-10; 40 unseen assets 2010-2022 and 2023-2026; both together.
Benchmarks: SPY buy-and-hold, DBMF and KMLM (managed-futures ETFs), same calendar and Sharpe method.
Robustness on the final version only: costs doubled; short leg reported on its own.

## Selection from development (recorded before the holdout run)
Dev Sharpe: T1 L/S 0.75, T1 long-only 0.98, T2 L/S 0.70, T2 long-only 0.98.
1. T1 beats T2 (0.75 vs 0.70, long/short). 2. Long-only beats long/short for T1 (0.98 vs 0.75) -> shorts dropped.
3. T1 long-only dev vol 8.9% -> leverage 10/8.9 = 1.124.
FINAL = T1 long-only, leverage 1.124.
