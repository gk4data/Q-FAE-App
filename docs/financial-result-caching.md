# Financial-result snapshots and refresh policy

Q-FAE stores Upstox company financials outside the one-minute processing path. Each provider response is content-hashed, so an unchanged response updates its `last_seen_at` timestamp while a revised response creates a new durable snapshot.

## Datasets

For each approved stock with an ISIN, a refresh collects consolidated:

- quarterly income-statement history;
- annual income-statement history;
- annual cash-flow history; and
- annual balance-sheet history.
- current key ratios, including ROE and ROCE when available.

The latest quarterly revenue, operating profit and net profit plus annual operating cash flow continue to populate the lightweight corporate financial context used by later evidence features.

## Thirty-day cache guard

`QFAE_FINANCIAL_RESULTS_CACHE_DAYS` defaults to 30. A provider call is skipped only when both conditions are true for that stock:

1. the stored quarterly period is the most recently completed calendar quarter; and
2. the snapshot was last confirmed within the configured cache window.

A recent snapshot containing an older quarter does not block a refresh. This permits Q-FAE to discover a newly published result. The cache rule is applied both by **Prepare 20 stocks** and by the financial-results utility.

## Frontend utility

The **Check financial results** button appears below the market tables. Its result dialog reports `fetched`, `reused`, `unavailable`, or `failed` per stock and displays the latest quarterly period, annual period and snapshot date. There is no force-refresh control in the normal UI, which prevents accidental duplicate provider calls.

## API

- `POST /api/v1/market/financial-results/check?limit=20`

The normal application endpoint does not expose a force-refresh switch.

## Provider contracts

- [Upstox income statement](https://upstox.com/developer/api-documentation/get-income-statement/)
- [Upstox cash flow](https://upstox.com/developer/api-documentation/get-cash-flow/)
- [Upstox balance sheet](https://upstox.com/developer/api-documentation/get-balance-sheet/)
