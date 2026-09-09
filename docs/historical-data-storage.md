# Future historical-data storage policy

Status: architectural requirement for the full-universe phase; not yet implemented.

Q-FAE must not download the complete historical dataset again every morning. Historical market data will use a rolling, incremental storage model with distinct policies for daily and one-minute data.

## Required storage tiers

### Daily OHLCV

- Store at least 3–5 years of daily OHLCV permanently for the full approved stock universe and required benchmark/sector indices.
- Use daily data for multi-horizon returns, moving-average regimes, ATR, breakouts, bases, relative strength, and other medium/long-term context.
- Perform a one-time backfill, followed by a small overlapping incremental refresh of approximately 2–5 sessions.
- Use an idempotent database upsert keyed by instrument key, interval, and timestamp.
- Preserve raw and corporate-action-adjusted values, with adjustment/version metadata, when that layer is implemented.

### Raw one-minute OHLCV

- Always retain the current market day's completed one-minute candles.
- Retain approximately 14–30 recent sessions for approved/tradable stocks, rather than indefinitely retaining all raw minutes for every listed stock.
- Use recent minutes for opening behaviour, VWAP development, same-time RVOL, pullback quality, liquidity analysis, and short-horizon validation.
- Make the universe scope and retention period configurable after storage and provider-rate tests.

### Rolling minute-of-day profiles

Before older raw minutes expire, update compact statistical profiles for each instrument and each normal NSE market minute. Profiles should retain:

- minute-of-day bucket;
- comparable-session count;
- mean and median volume;
- volume dispersion and useful percentiles;
- typical range and realised volatility;
- spread/liquidity statistics when reliable;
- last update timestamp and calculation version.

These profiles allow live same-minute comparisons without repeatedly reading or storing every historical minute candle.

### Research archive

- Longer raw one-minute history may be retained separately for strategy backtesting when justified.
- Prefer compressed, partitioned archival storage such as Parquet by date/instrument group instead of the operational application database.
- Archive retention must be a deliberate research requirement, not an accidental consequence of the live pipeline.

## System responsibilities

| Component | Responsibility |
| --- | --- |
| PostgreSQL | Durable daily candles, limited operational minute history, calculated profiles, sync metadata, and point-in-time feature records. |
| Redis | Current quotes, forming/completed live minutes, latest feature snapshots, runtime status, and dashboard cache. |
| Archive storage | Optional long-horizon raw minute data for reproducible research and backtesting. |

## Incremental market-day flow

1. Before market open, determine the last successfully stored session per instrument.
2. Request only missing data plus a small overlap for corrections.
3. Validate and upsert without creating duplicate candles.
4. Recalculate affected daily regimes and minute profiles only.
5. During market hours, append completed live minutes and update provisional daily evidence.
6. After market close, reconcile the provisional day with the official daily candle and update rolling profiles.

## Non-negotiable data-quality rules

- Missing values must remain missing; they must not be silently converted to zero.
- Calculations must record data-through time, source, adjustment status, and feature version.
- Backtests must use only information available at that historical time and avoid survivorship/look-ahead bias.
- Provider corrections, symbol changes, instrument-key changes, splits, bonuses, and other corporate actions must be handled without destroying the original observations.
- Daily history is broad and permanent; raw minute retention is selective and bounded.

This policy should be implemented before Q-FAE expands from the pilot universe to full-universe daily processing.
