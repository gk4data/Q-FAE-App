# Intraday focus-universe policy

Status: approved design; the 100-stock evidence universe is active, while automatic focus-list promotion and demotion remain to be implemented.

## Decision

Q-FAE will use the first 30 minutes to establish an initial leadership view, but it will not permanently discard stocks that are quiet at the open. Trading attention may narrow; market-data collection and point-in-time evidence recording must continue across the complete configured universe throughout the session.

This separation prevents late breakouts, sector rotations, news reactions, VWAP reclaims and failed early leaders from disappearing from the research dataset. It also avoids training the future backtest only on stocks that already looked attractive at 9:45 AM.

## Market-day flow

1. **9:15–9:45 AM — discovery:** process and record all 100 approved stocks each completed minute.
2. **9:45 AM — provisional classification:** create the first Focus, Challenger and Background groups from information available through the completed 9:44 minute.
3. **After 9:45 AM — continuous rotation:** maintain full point-in-time recording for all stocks. Give Focus stocks the highest UI and decision priority while scanning every other stock once per completed minute for promotion triggers.
4. **After market close:** retain every group's evidence and outcomes. Reconcile the official close and evaluate whether early Focus membership improved forward returns after costs.

## Groups

| Group | Provisional size | Treatment |
| --- | ---: | --- |
| Focus | 15–20 | Full evidence, rank explanation and prominent UI treatment every minute. |
| Challengers | 15–25 | Full monitoring with promotion eligibility; kept visible near the Focus list. |
| Background | Remaining stocks | Lightweight UI treatment, but live data, essential features and evidence continue to be recorded. |

Group sizes are operating defaults, not model truths. They must be calibrated from stored point-in-time outcomes.

## Promotion evidence

A Background or Challenger stock may enter Focus when persistent evidence supports one or more of the following:

- a valid 5/15/30-minute opening-range breakout or retest;
- improving relative strength versus NIFTY and the mapped sector;
- price holding above or reclaiming VWAP with a positive slope;
- accelerating same-minute RVOL and directional volume;
- improving liquidity with acceptable spread, depth and estimated slippage;
- a new official company announcement or other timestamped catalyst;
- an Opportunity Score crossing the configured review threshold with adequate coverage;
- confirmation in at least two of the latest three completed minutes.

## Demotion and hard exclusion

Use hysteresis so a single noisy minute does not cause constant list turnover. A provisional starting rule is to demote only after five consecutive completed minutes of material deterioration, a failed signal-persistence state, or a newly rejected risk gate.

Hard exclusion for the rest of the session is permitted only for objective data or tradability failures, including:

- invalid/delisted instrument or halted trading;
- stale or materially incomplete live data;
- unacceptable spread, visible-book slippage or traded value;
- circuit proximity or another rejected risk/tradability gate;
- a confirmed surveillance or corporate restriction once those inputs are implemented.

Weak first-30-minute performance alone is never a hard-exclusion reason.

## Evidence and backtesting requirements

- Store group membership, promotion/demotion time, trigger reasons, score, coverage and model version at every transition.
- Continue storing the normal per-minute evidence observation for all 100 stocks, regardless of group.
- Simulate any entry no earlier than the minute after the classification or promotion signal.
- Compare Focus, Challenger and Background forward outcomes to measure missed late movers and false early leaders.
- Include spread, slippage, fees and execution delay before deciding final thresholds or group sizes.
- Do not allow a future focus controller to change live scoring weights automatically.

## Implementation sequence

1. Collect full-universe evidence and measure one-minute processing latency with 100 stocks.
2. Add durable, timestamped focus-group transition records.
3. Implement the 9:45 classification and one-minute promotion/demotion evaluator.
4. Add Focus, Challenger and Background filters to the dashboard.
5. Calibrate group sizes and transition rules through walk-forward backtesting.

