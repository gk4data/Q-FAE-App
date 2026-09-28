# Opportunity-model backtesting

Q-FAE backtests the recommendations it recorded point-in-time in
`evidence_observations`. It does not rebuild a past recommendation using facts
that became available later.

## Execution contract

- A qualifying signal must meet the configured score, eligibility and signal-state rules.
- Entry occurs at the **next one-minute candle open** after the recorded signal candle.
- Slippage and fees are configurable per side and are included in net returns.
- Model-managed, fixed-minute, end-of-day and stop/target bracket exits are supported.
- A model-managed position is reassessed from the evidence recorded after every completed minute. A failed persistence state exits immediately after the configured minimum hold; weakening, ineligibility or a score below the exit threshold must persist for the configured confirmation window.
- Model exits execute at the next one-minute candle open. A hard stop remains active from entry and every remaining position is closed by the end of the session.
- When one candle touches both a long stop and target, the stop is selected. This is the conservative result when intraminute event order is unknown.
- Per-minute candidate, per-day trade and concurrent-position limits prevent every repeated signal from being counted as an independent trade.
- One trade per stock per session is the default.

## Outputs

Every saved run retains:

- the complete configuration and date range;
- model versions observed in the selected signals;
- aggregate return, costs, win rate, expectancy, profit factor, maximum drawdown and a daily Sharpe-like statistic;
- recorded-session and traded-session counts so a broad date selection cannot hide sparse live evidence;
- score, regime, sector and exit-reason breakdowns;
- entry/exit timestamps and prices, net return, P&L, MFE, MAE and exit reason for every trade.

The default capital is Rs 10 lakh with Rs 1 lakh per simulated trade. Returns
are therefore portfolio-level only under the configured trade and concurrency
limits; they are not a claim that every signal could be filled at arbitrary size.

## Data boundary

The first release evaluates only evidence Q-FAE actually recorded. Raw candles
from dates before point-in-time evidence collection cannot be treated as model
recommendations without a separate historical replay engine.

PostgreSQL one-minute pruning is disabled by default through
`QFAE_PRUNE_PERSISTED_MINUTE_HISTORY=false`. Redis remains a bounded working
cache. Set the flag to true only when deliberate database retention limits are
required.

## API

- `POST /api/v1/market/backtests`
- `GET /api/v1/market/backtests`
- `GET /api/v1/market/backtests/{run_id}`

The Backtesting dashboard tab supplies the common parameters and displays saved
runs and trade-level output.

Mechanical policies are retained as benchmarks. Model-managed results should be
compared against them over an out-of-sample period; a higher in-sample return is
not by itself evidence that revised thresholds or weights generalize.
