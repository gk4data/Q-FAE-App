# Intraday focus-universe policy

Status: rolling liquidity admission is implemented; intraday Focus/Challenger/Background promotion and demotion remain to be implemented.

## Rolling liquidity admission

Before intraday focus selection, Q-FAE classifies every approved stock from completed daily candles using **traded value**, not raw share volume. Daily traded value is approximated as daily typical price (`(high + low + close) / 3`) multiplied by daily volume, which makes unlike share prices more comparable.

| Tier | Current pilot rule | Runtime treatment |
| --- | --- | --- |
| Active | Traded in at least 18 of the latest 20 NIFTY sessions, 20-session median traded value is at least Rs 5 crore, and the rolling median spread is at most 25 bps. | Live subscription, features, evidence and opportunity ranking, subject to the live slippage gate. |
| Watch-only | Trading continuity passes, but median traded value is below Rs 5 crore, median spread exceeds 25 bps, or spread history is still unavailable. | Live subscription and daily observation, but excluded from opportunity ranking. |
| Dormant | Traded in fewer than 18 of the latest 20 NIFTY sessions. | Excluded from live subscription and opportunity ranking; daily history still refreshes. |

Daily spread medians are calculated from Q-FAE's recorded minute evidence and stored in PostgreSQL after reconciliation. The rolling spread window therefore builds prospectively; missing spread history is never treated as a pass. The live D5 order book must also support a Rs 1 lakh reference order with estimated worst-side slippage no greater than 20 bps, otherwise the stock is ineligible for ranking.

Preparation continues to refresh daily history for all approved stocks, including Dormant stocks. This preserves the reactivation path and avoids permanently deleting a company from the approved universe.

Only normal NSE `EQ` company shares with market capitalization of at least Rs 500 crore and a latest completed close of at least Rs 20 are inside the approved universe. The daily provider-led refresh starts from Upstox's BOD master, rejects suspended securities, uses NSE's security-type flag to remove ETFs and other non-company instruments, and calculates market cap from official issued capital and the latest completed close. Missing inputs are excluded rather than guessed. SME `SM`, `ST`, and `SZ` series and trade-for-trade `BE` and `BZ` series are rejected before preparation, live subscription, evidence calculation, ranking, and dashboard display. No manually maintained stock-list workbook is used.

## Decision

Q-FAE will use the first 30 minutes to establish an initial leadership view, but it will not permanently discard liquidity-Active stocks that are quiet at the open. Trading attention may narrow; market-data collection and point-in-time evidence recording must continue across the complete Active universe throughout the session. Watch-only stocks remain streamed for observation, while Dormant stocks keep daily history for later reactivation.

This separation prevents late breakouts, sector rotations, news reactions, VWAP reclaims and failed early leaders from disappearing from the research dataset. It also avoids training the future backtest only on stocks that already looked attractive at 9:45 AM.

## Market-day flow

1. **9:15–9:45 AM — discovery:** process and record all liquidity-Active approved stocks each completed minute and observe Watch-only stocks.
2. **9:45 AM — provisional classification:** create the first Focus, Challenger and Background groups from information available through the completed 9:44 minute.
3. **After 9:45 AM — continuous rotation:** maintain full point-in-time recording for all Active stocks. Give Focus stocks the highest UI and decision priority while scanning every other Active stock once per completed minute for promotion triggers.
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
- Continue storing the normal per-minute evidence observation for all liquidity-Active stocks, regardless of intraday group; retain daily history for Watch-only and Dormant stocks.
- Simulate any entry no earlier than the minute after the classification or promotion signal.
- Compare Focus, Challenger and Background forward outcomes to measure missed late movers and false early leaders.
- Include spread, slippage, fees and execution delay before deciding final thresholds or group sizes.
- Do not allow a future focus controller to change live scoring weights automatically.

## Implementation sequence

1. Collect Active-universe evidence and measure one-minute processing latency while Watch-only stocks remain subscribed.
2. Add durable, timestamped focus-group transition records.
3. Implement the 9:45 classification and one-minute promotion/demotion evaluator.
4. Add Focus, Challenger and Background filters to the dashboard.
5. Calibrate group sizes and transition rules through walk-forward backtesting.
