# Local PostgreSQL storage and retention

Status: implemented for the current release. Q-FAE does not require Azure Blob Storage.

The storage policy separates durable market history from large point-in-time decision payloads. Daily and one-minute candles remain in local PostgreSQL because they are the reproducible source data for feature calculation and backtesting. Evidence storage is tiered so a full-universe session does not write a large JSON document for every stock on every minute.

## Implemented checklist

- [x] Keep daily OHLCV in local PostgreSQL permanently.
- [x] Keep one-minute OHLCV in local PostgreSQL permanently by default; destructive pruning remains opt-in.
- [x] Store full evidence, risk and market-regime JSON only for the strongest bounded candidate set each minute.
- [x] Default the full-evidence set to 50 stocks per minute, configurable with `QFAE_FULL_EVIDENCE_MAX_PER_MINUTE`.
- [x] Store a normalized compact checkpoint for the wider non-Dormant universe every 15 minutes.
- [x] Capture an additional compact checkpoint when a stock's coarse decision state changes.
- [x] Preserve all evidence and candle rows already stored; the migration performs no deletion or rewrite.
- [x] Add time and candidate indexes to the compact table.
- [x] Expose the checkpoint interval and score-bucket sensitivity as environment settings.
- [ ] Convert the existing multi-million-row candle/evidence tables to native monthly partitions. This is deferred because it needs a planned maintenance window and improves query/vacuum operations rather than reducing stored bytes.
- [ ] Add external archive/object storage. This is intentionally out of scope until local capacity or backup requirements justify it.

## Storage tiers

| Data | Frequency | Retention | Purpose |
| --- | --- | --- | --- |
| Daily OHLCV | Once per completed session | Permanent | Daily regimes, trends and long-horizon research |
| One-minute OHLCV | Each completed minute | Permanent by default | Intraday features and reproducible backtests |
| Full evidence JSON | Strongest 50 candidates per minute | Permanent | Exact model-decision replay and outcome evaluation |
| Compact evidence | Session start, each 15-minute checkpoint, and coarse state changes | Permanent | Whole-universe discovery, diagnostics and future funnel analysis |
| Redis live state | Current/short rolling state | Transient | Dashboard and live calculations |

Full evidence selection prioritizes Active-universe candidates by opportunity score and data coverage. It does not use turnover, previous trading activity or live execution quality as a score component. Continuity and rolling median traded value control admission; spread, slippage and depth remain separately retained cautions.

The compact row contains score, coverage, eligibility, confluence, signal/risk/liquidity states, market regime, flow confirmation and component scores. It deliberately contains no large JSON payload.

## Capacity note

The local database measured about 4.07 GB before this policy was introduced, including about 2.77 GB of candles and 1.14 GB of legacy full evidence. Those existing rows are preserved. With the new default cap, new full-evidence writes are limited to at most 18,750 rows per normal 375-minute session instead of one row per tracked stock per minute. Compact checkpoints add small normalized rows for background coverage.

Actual growth must be remeasured after several complete sessions because PostgreSQL tuple/index overhead, live-universe size and state-change frequency affect the result. Operational alerts should use host disk free space, with warnings at 70% used and a critical threshold at 85% used.
