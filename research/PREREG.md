# Signal Desk research plan (written 2026-11-10 19:05 UK, before any results)

Data: Yahoo daily bars, max history. Engine scores and levels from the app's files, unchanged.
Development (tuning) period: watchlist assets, 2010-01-01 .. 2022-12-31.
Holdout: (a) watchlist 2023-01-01 .. 2026-11-10; (b) ~40 unseen assets 2010 .. 2026 (judged on 2010-2022 and 2023-2026 separately).
Costs: scorecard.COST per asset class. Risk 0.5% of starting equity per trade, no compounding.
Selection metric: Sharpe of daily equity (calendar days) in the development period. Ties -> lower max drawdown.

Variants (all on top of the current trade rules unless stated):
- V0a  current rules, every setup, one position per asset (no portfolio limit)
- V0b  current rules, max 3 open, first come first served (app default)
- V1   risk budget: rank same-day fills by |score|, max 6 open (3% total risk), max 2 per cluster
- V2   V1 + backdrop filter: stocks/indices long only if SPY > 200d, short only if SPY < 200d;
       crypto long only if BTC > 200d, short only if BTC < 200d; skip any entry when 20d/252d volatility > 1.5
Bearish research (on V2):
- B1   no shorts in stocks or indices
- B2   = V2's backdrop rule for shorts (already in V2); B2x: V1 + backdrop filter on shorts only
- B3   faster short exits: exit when score closes above -40, or after 20 bars
- B4   B1 + B3
Entry/exit (on V2):
- E1   wider stop: signal-break 1.5 ATR beyond the zone (instead of 0.75)
- E2   confirmation entry: after price trades into the zone, enter at next open after a close back out of it in the trend direction (within 10 bars)
- E3   half off at +2R, trail the rest 3 ATR from the best close; score-fade exit still applies
Final candidate: V2 + best bearish variant (if it beats V2 on dev Sharpe) + best entry/exit variant (if it beats V2 on dev Sharpe),
re-checked on dev, then judged ONCE on the holdout. No changes after seeing holdout results.

## Selection from development (recorded before running the holdout, 2026-11-10 ~19:40 UK)
Data fixes before selection: 319 bad bars cleaned (of 430,145); R measured against planned risk (limit to stop), as the app sizes.
Dev Sharpe: V2 0.01; B1 0.10, B2x 0.33, B3 -0.04, B4 0.04; E1 0.41, E2 -0.03, E3 -0.82.
Best bearish = B2x (beats V2). Best entry/exit = E1 (beats V2).
FINAL CANDIDATE = risk budget (V1) + backdrop filter on shorts only (B2x) + wider stop (E1). No volume/vol filter on longs.
