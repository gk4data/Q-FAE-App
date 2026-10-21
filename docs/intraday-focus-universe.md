# Intraday focus-universe policy

Status: rolling liquidity admission and the reversible intraday Focus/Cooling/Background funnel are implemented. Thresholds remain provisional until walk-forward testing provides calibration evidence.

## Rolling liquidity admission

Before intraday focus selection, Q-FAE classifies every approved stock from completed daily candles using **traded value**, not raw share volume. Daily traded value is approximated as daily typical price (`(high + low + close) / 3`) multiplied by daily volume, which makes unlike share prices more comparable.

| Tier | Rolling rule | Runtime treatment |
| --- | --- | --- |
| Active | Traded in at least 18 of the latest 20 NIFTY sessions, 20-session median traded value is at least Rs 5 crore, and the rolling median spread is at most 25 bps. | Live subscription, features, evidence and opportunity ranking, subject to the live slippage gate. |
| Watch-only | Trading continuity passes, but median traded value is below Rs 5 crore, median spread exceeds 25 bps, or spread history is still unavailable. | Live subscription, features and directional scoring for audit; excluded from executable ranks and shown separately when its opportunity signal is strong. |
| Dormant | Traded in fewer than 18 of the latest 20 NIFTY sessions. | Excluded from live subscription and opportunity ranking; daily history still refreshes. |

Daily spread medians are calculated from Q-FAE's recorded minute evidence and stored in PostgreSQL after reconciliation. The rolling spread window therefore builds prospectively; missing spread history is never treated as a pass. The live D5 order book must also support a Rs 1 lakh reference order with estimated worst-side slippage no greater than 20 bps, otherwise the stock is ineligible for ranking.

Preparation continues to refresh daily history for all approved stocks, including Dormant stocks. This preserves the reactivation path and avoids permanently deleting a company from the approved universe.

The approved universe is never truncated or prioritized by the previous session's turnover. Turnover is used only through the rolling liquidity gate. The current approved-universe size fits below the provider's Full-feed capacity together with the market-context indices; the runtime fails explicitly rather than silently dropping stocks if that capacity is ever exceeded.

Only normal NSE `EQ` company shares with market capitalization of at least Rs 500 crore and a latest completed close of at least Rs 20 are inside the approved universe. The daily provider-led refresh starts from Upstox's BOD master, rejects suspended securities, uses NSE's security-type flag to remove ETFs and other non-company instruments, and calculates market cap from official issued capital and the latest completed close. Missing inputs are excluded rather than guessed. SME `SM`, `ST`, and `SZ` series and trade-for-trade `BE` and `BZ` series are rejected before preparation, live subscription, evidence calculation, ranking, and dashboard display. No manually maintained stock-list workbook is used.

## Decision

Q-FAE uses 9:15-9:30 AM as an opening discovery period, but it does not permanently discard liquidity-Active stocks that are quiet or red at the open. Trading attention narrows after 9:30; market-data collection and compact evidence recording continue across the complete non-Dormant universe throughout the session. Watch-only stocks remain streamed for observation, while Dormant stocks keep daily history for later reactivation.

This separation prevents late breakouts, sector rotations, news reactions, VWAP reclaims and failed early leaders from disappearing from the research dataset. It also avoids training the future backtest only on stocks that already looked attractive at 9:30 AM.

## Market-day flow

1. **9:15-9:30 AM - discovery:** process all liquidity-qualified approved stocks each completed minute without prematurely labelling opening noise as Focus.
2. **From 9:30 AM - provisional classification:** require two consecutive promotable completed minutes before a stock enters Focus.
3. **Continuous rotation:** show Focus and Focus-Cooling stocks in the opportunity table. Screen every live quote with inexpensive current-session measures, then run full history-dependent features for the strongest candidates plus a rotating Background discovery batch each completed minute. Require three materially weak completed minutes before demotion to Background.
4. **After market close:** retain every group's evidence and outcomes. Reconcile the official close and evaluate whether early Focus membership improved forward returns after costs.

## Groups

| Group | Provisional size | Treatment |
| --- | ---: | --- |
| Focus | Dynamic | Confirmed long-opportunity candidates shown and ranked prominently. |
| Focus - Cooling | Dynamic | Green Focus stocks with paused momentum or a constructive pullback; still visible and ranked so the next leg is not missed. |
| Background | Remaining Active stocks | Hidden from the primary ranking, screened from every live quote, periodically selected for full feature discovery, and retained through compact evidence. |
| Watch-only | Rolling-liquidity or execution constraint | Streamed and scored for observation but never given an executable rank. |
| Dormant | Failed trading-continuity gate | Excluded from live subscription while daily history continues to refresh. |

Group sizes are operating defaults, not model truths. They must be calibrated from stored point-in-time outcomes.

## Promotion evidence

A Background stock may enter Focus when persistent evidence supports several of the following:

- a valid 5/15/30-minute opening-range breakout or retest;
- improving relative strength versus NIFTY and the mapped sector;
- price holding above or reclaiming VWAP with a positive slope;
- accelerating same-minute RVOL and directional volume;
- improving liquidity with acceptable spread, depth and estimated slippage;
- a new official company announcement or other timestamped catalyst;
- an Opportunity Score crossing the configured review threshold with adequate coverage;
- confirmation in at least two of the latest three completed minutes.

## Demotion and hard exclusion

Use hysteresis so a single noisy minute does not cause constant list turnover. The implemented starting rule promotes after two consecutive qualifying minutes. A green Focus stock with two cooling minutes moves to Focus-Cooling but remains in the table; one newly promotable minute returns it immediately to Focus. Demotion to Background still requires three consecutive materially weak red minutes. A failed execution/risk gate demotes immediately.

Being below the previous close is not a sufficient demotion or exclusion rule. Material weakness requires it together with at least two other conditions such as a below/falling VWAP, simultaneous underperformance versus NIFTY and sector, weak RVOL/volume acceleration, or no opening-range breakout. A red stock can therefore enter Focus when relative strength, VWAP, volume and opening-range evidence confirm a reversal or emerging leader.

Focus-Cooling recognizes that higher lows, orderly or low-volume pullbacks and short momentum pauses can precede another expansion. Cooling is an attention label, not a negative model verdict, and it never stops candle or evidence processing.

Hard exclusion for the rest of the session is permitted only for objective data or tradability failures, including:

- invalid/delisted instrument or halted trading;
- stale or materially incomplete live data;
- unacceptable spread, visible-book slippage or traded value;
- circuit proximity or another rejected risk/tradability gate;
- a confirmed surveillance or corporate restriction once those inputs are implemented.

Weak first-30-minute performance alone is never a hard-exclusion reason.

## Evidence and backtesting requirements

- Store group membership, promotion/demotion time, trigger reasons, score, coverage and model version at every transition.
- Store full per-minute evidence for the bounded strongest candidate set and compact checkpoints for the wider non-Dormant universe; retain daily history for Watch-only and Dormant stocks.
- Simulate any entry no earlier than the minute after the classification or promotion signal.
- Compare Focus and Background forward outcomes to measure missed late movers and false early leaders.
- Include spread, slippage, fees and execution delay before deciding final thresholds or group sizes.
- Do not allow a future focus controller to change live scoring weights automatically.

## Implementation sequence

1. [x] Collect Active-universe evidence while Watch-only stocks remain subscribed.
2. [x] Add durable, timestamped focus-group transition records.
3. [x] Implement the 9:30 classification and one-minute promotion/demotion evaluator.
4. [x] Restrict the primary opportunity table and Alpha Matrix to confirmed Focus and Focus-Cooling stocks while showing Focus/Cooling/Background/Watch-only counts.
5. [ ] Calibrate thresholds and transition rules through walk-forward backtesting.
