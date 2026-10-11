# Future historical-data storage policy

Status: PostgreSQL daily candles, durable pilot minute history, and rolling minute-of-day profiles are implemented. Full-universe scaling and compressed research archives remain future phases.

Q-FAE must not download the complete historical dataset again every morning. Historical market data will use a rolling, incremental storage model with distinct policies for daily and one-minute data.

The implemented foundation includes an Alembic-managed schema, idempotent candle upserts, per-instrument sync watermarks, Redis hydration from PostgreSQL, a five-day daily overlap, and a two-day one-minute overlap. PostgreSQL minute pruning is disabled by default so backtests remain reproducible. The 35-day setting applies only when `QFAE_PRUNE_PERSISTED_MINUTE_HISTORY=true`. Profiles are rebuilt from prior sessions and deliberately exclude the current live date.

## Required storage tiers

### Daily OHLCV

- Store at least 3–5 years of daily OHLCV permanently for the full approved stock universe and required benchmark/sector indices.
- Use daily data for multi-horizon returns, moving-average regimes, ATR, breakouts, bases, relative strength, and other medium/long-term context.
- Perform a one-time backfill, followed by a small overlapping incremental refresh of approximately 2–5 sessions.
- Use an idempotent database upsert keyed by instrument key, interval, and timestamp.

### Raw one-minute OHLCV

- Always retain the current market day's completed one-minute candles.
- Retain approved-universe minute history for reproducible backtesting; introduce partitioning or archives as measured storage grows.
- Use recent minutes for opening behaviour, VWAP development, same-time RVOL, pullback quality, liquidity analysis, and short-horizon validation.
- Keep destructive PostgreSQL pruning opt-in and separate from Redis cache expiry.

### Rolling minute-of-day profiles

As new sessions arrive, update compact statistical profiles for each instrument and each normal NSE market minute. Profiles should retain:

- minute-of-day bucket;
- comparable-session count;
- mean and median volume;
- volume dispersion and useful percentiles;
- typical range and realised volatility;
- spread/liquidity statistics when reliable;
- last update timestamp and calculation version.

These profiles allow live same-minute comparisons without repeatedly reading or storing every historical minute candle.

Q-FAE now uses the persisted median-volume profile for intraday RVOL when at least five comparable sessions are available. It falls back to the Redis history calculation when a profile is unavailable or insufficient. Historical bid/ask spread is not supplied with Upstox candle history, so spread-profile fields should remain unavailable until Q-FAE persistently samples reliable live depth.

### Research archive

- Longer raw one-minute history is retained for strategy backtesting unless pruning is explicitly enabled.
- Prefer compressed, partitioned archival storage such as Parquet by date/instrument group instead of the operational application database.
- Archive retention must be a deliberate research requirement, not an accidental consequence of the live pipeline.

## System responsibilities

| Component | Responsibility |
| --- | --- |
| PostgreSQL | Durable daily/minute candles, calculated profiles, sync metadata, point-in-time evidence and saved backtest runs. |
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
- Provider corrections, symbol changes, and instrument-key changes must be handled without destroying the original observations.
- Daily history is broad and permanent; approved-universe raw minute history remains durable for reproducible backtesting.

## Capacity and operational limits

PostgreSQL does not impose a small fixed database quota; practical capacity is governed by the host/Docker disk, write throughput, indexes, vacuuming and backup time. The local Docker database was approximately 48 MB at the start of the 100-stock phase, and its container filesystem reported approximately 950 GB available. These figures are observations, not reserved capacity or a storage guarantee.

At 139 stocks and 375 normal NSE minutes, Q-FAE can create up to 52,125 point-in-time evidence rows per full session in addition to minute candles. Because evidence rows contain JSON payloads and outcomes are updated as horizons mature, write latency and table/index growth must be measured after real sessions. Both candles and evidence observations intended for backtesting now remain durable by default; retention and archival limits must be introduced deliberately as measured storage grows.

Before moving from 139 to 200 stocks:

- record per-minute calculation and persistence latency;
- add database-size, table-size, latest-evidence and disk-usage health reporting;
- set warning thresholds at 70% disk use and a critical threshold at 85%;
- confirm autovacuum keeps up with progressively updated evidence outcomes;
- partition `evidence_observations` by month when measured size/query plans justify it;
- back up durable evidence and move long-horizon raw research data to compressed archive storage.

Before full-universe expansion, benchmark PostgreSQL write/query throughput, partition high-growth tables if justified, and implement the research archive policy.
