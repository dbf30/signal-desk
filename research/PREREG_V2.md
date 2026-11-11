# Signal Desk v2 research plan (written 2026-11-11 ~17:10 UK, before any v2 results)

Context. Study 1 (PREREG.md) and Study 2 (PREREG_TF.md) were run on 10 Nov 2026. Their 2023-2026 holdout
and the 40 unseen markets have therefore been looked at once. Nothing below can un-see them, so:
- every choice in this plan is made on DEVELOPMENT data only;
- the old holdout is reported once per question as a "second look" and labelled as such;
- the real test of anything adopted here is the live shadow log that starts after this plan.

## Q1. Why do the live swing and intraday logs look the way they do? (descriptive, no rule changes)
a) Closed-only bias. Replay the live scorecard's recording rule (every |score| >= 40 setup, one active entry per
   asset) from 300 random start dates in 2010-2022 on the watchlist and record, 9 calendar days after the start:
   closed trades, their total R, and the marked R of trades still open. Report how often the closed total is
   <= the live figure and the distribution of (closed + open).
b) Horizon. For every filled development trade (base rules), the marked R at 5, 10, 20, 40 and 60 bars after the
   fill, by asset class and direction.
c) Cost drag. Round-trip cost as a fraction of planned risk: swing setups (development) vs intraday sessions.

## Q2. Swing setup grading (calibration, no change to entry/stop/exit rules: trades.py stays as it is)
Candidate factors, each cut at fixed points chosen before looking:
- group: asset class x direction
- score strength: |score| 40-55 / 55-70 / 70+
- room: reward:risk to the next level  <1.5 / 1.5-3 / 3+ / no level ahead
- stretch: price vs 20-day average in the trade's direction  >2 ATR ("stretched") or not
- distance to the zone at the signal: in zone / <=1 ATR / 1-2 ATR / >2 ATR
- volatility ratio (20d/252d): <=1.5 / >1.5
- backdrop: stocks+indices by SPY vs 200-day; crypto by BTC vs 200-day (with / against the trade)
- anchor quality: zone sits on a level with >=2 touches / 1 touch / no level (ATR fallback)
Rule for using a factor in the grade: on development (watchlist, fills 2010-2022) the best and worst buckets must
differ by >= 0.15R in average R with >= 150 filled trades in each, AND the sign of that difference must hold in
both halves of development (2010-2016, 2017-2022). Factors that fail are shown as context but score zero points.
Grade = points from the surviving factors; cut-offs fixed on development so that roughly the top fifth is A/A+.
Second look (once): average R by grade on (i) watchlist 2023-2026, (ii) unseen markets 2010-2026.
If grades do not order outcomes there, the app must say so next to every grade.

## Q3. Intraday crypto "London range breakout" (current rule = S0, engine/intraday.py unchanged)
Data: Yahoo hourly bars, 2024-11-12 .. 2026-11-11, 12 coins. Bias from the previous day's daily score.
Trades simulated with intraday.intraday_trade itself (cost 0.08%), so S0 is the live rule exactly.
Sanity check: S0 on 2-11 Nov 2026 must reproduce the app's live log.
Sets: DEV = BTC/ETH/SOL/XRP sessions before 2025-07-21. SECOND LOOK A = same coins from 2025-07-21 to 2026-11-01.
SECOND LOOK B = 8 other coins, whole period. (Both were used once on 2 Nov to adopt S0.)
Variants:
- S1 cost gate: skip the session when round-trip cost > X of the range risk, X in {10%, 20%, 30%}
- S2 stop floor: stop distance = max(range, k x daily ATR), k in {0.10, 0.15, 0.25}; entry unchanged
- S3 strong bias only: |score| >= 40
- S4 direction: longs only / shorts only (reported; adopted only if the other side loses in both DEV halves)
- S5 concentration cap: at most 2 coins a day, highest |score| first
Selection on DEV only, metric = Sharpe of the daily sum of R (days with no trade = 0), ties -> higher average R.
A variant is adopted only if it beats S0 on both the metric and average R per trade. At most one of S1/S2.
V2 = S0 + adopted variants. V2 then runs in the app as a SHADOW log beside S0; S0 stays the displayed rule
until the shadow log has >= 100 sessions.

## Not re-tested
Intraday rules for stocks, indices, forex and commodities: tested on 2 Nov, none held up. No new data exists that
would justify another search, and searching again on the same two years would be data-mining.

## Addendum, recorded 2026-11-11 ~18:05 UK, after development results and BEFORE any second look
Q3 (intraday), development result: S0 Sharpe 1.83, 0.262R (614 trades). Only S2 with k = 0.15 beat S0 on both
measures (Sharpe 2.82, 0.275R). S1 (all three), S2 k=0.10 and k=0.25, S3 and S5 failed. S4: shorts did better
(0.563R vs 0.131R) but longs were positive in both halves, so no direction is dropped. V2 = S0 + stop floor 0.15 ATR.
Finding outside the plan: the live log took its bias from the live score at each run, not from the previous close.
That is a logging bug, fixed in engine/intraday.py; it is not a rule change.

Q2 (grading), two choices made stricter after seeing how the development set is built, before the second look:
1. Unit = one trade per asset at a time (the scorecard's rule), 4,062 development trades, not all 51,477
   overlapping daily signals, which are near-copies of each other.
2. Every factor is tested on what is left after removing its asset-class x direction average, so a factor cannot
   pass just because it tags the best groups.
Development results on that basis: PASS group, backdrop, distance to zone, score band (40-55 better than 55+),
room (LESS room to the next level was better), anchor (zones with NO nearby level were better).
FAIL stretch (did not hold in both halves), volatility ratio (gap 0.14R).
Model, fixed now: predicted R = group average (shrunk as if 200 zero-R trades were added) + least-squares effects
of backdrop / location / freshness / overhead / anchor fitted together on the remainder (so overlapping factors
share credit), each effect halved. Grades by predicted R: A+ >= 0.50, A >= 0.30, B >= 0.12, C >= 0, else Avoid.
Development mix: A+ 6%, A 10%, B 10%, C 23%, Avoid 52%.
Second look, once: average R by grade on watchlist 2023-2026, unseen 2010-2022, unseen 2023-2026.
Pass mark, set now: in the three sets taken together, A-or-better must beat the rest by >= 0.15R AND Avoid must
average below zero. If it fails, grades are shown as "not confirmed on later data".


## Audit note, added 2026-11-11 19:02 UK by a later working session
The clock times in the two headings above were estimates and are wrong: file timestamps show this plan, the addendum
and every result file were written between 16:35 and 16:55 UTC on 11 Nov 2026. Two consequences, stated plainly:
- Q3 (intraday). The development table and the second-look tables were saved within the same minute, so the file
  record cannot show that the stop-floor variant was chosen before the second look was seen. The choice does follow
  the rule written above from the development numbers alone (0.15 ATR is the only variant that beats S0 on both
  measures), but the second-look figures should be read as supporting detail, not as a clean out-of-sample test.
  This is why v2 runs only as a shadow log.
- Q2 (grades). The model file was fitted and second-looked a minute apart. Same caution. The old holdout had
  already been used once on 10 Nov in any case.
Everything was re-run from the saved data on 11 Nov at about 18:50 UTC and reproduced byte for byte
(grade_model.json, intraday_v2_*.json). Code fixes made after that re-run (measurement and display only, no rule
changes): intraday.py print statement; scorecard.excursions now measures against planned risk and ignores moves whose
order inside a daily bar is unknowable; news.py clustering and agency-copy handling.
