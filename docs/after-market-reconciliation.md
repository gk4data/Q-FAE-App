# After-market daily-candle reconciliation

Q-FAE provides a manual reconciliation step while market-day automation remains deferred. After a completed session, **Reconcile close** fetches the official Upstox daily candle for all 20 pilot equities and market-context indices, persists it idempotently, and replaces any same-date provisional daily candle in Redis.

For pilot equities, Q-FAE compares the official candle with retained regular-session one-minute candles and stores an audit record containing minute coverage, open/high/low/close consistency, volume difference, and explicit notes. A normal NSE session has 375 possible one-minute buckets from 09:15 through 15:29. An absent candle can mean either no trade or missing provider data, so Q-FAE reports the coverage gap without inventing a zero-volume candle or claiming a cause it cannot verify.

The official close is not expected to equal the last regular-session one-minute close. From 3 August 2026, [NSE's Closing Auction Session](https://www.nseindia.com/static/products-services/closing-auction-session) determines the close after continuous trading; earlier sessions used a closing-price methodology that could also differ from the final trade. Post-auction volume may likewise exceed the sum of regular-session minute candles. Q-FAE treats these known differences as informational and continues to flag minute-grid gaps, open/high/low discrepancies, and unexplained volume differences.

Reconciliation also refreshes the daily-regime cache from official candles and rolls completed equity sessions into minute-of-day profiles. Results are stored in `session_reconciliations` and exposed through:

- `POST /api/v1/market/reconcile?session_date=YYYY-MM-DD`
- `GET /api/v1/market/reconciliations?session_date=YYYY-MM-DD`

The provider can publish the final candle with a delay. A missing official candle is reported as missing and can be safely retried because all writes are idempotent.
