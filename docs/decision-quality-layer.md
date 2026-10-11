# Decision quality and evaluation layer

Q-FAE records what the system knew at each completed minute before any strategy weights are chosen. This avoids hindsight leakage and makes every future scoring rule testable.

## Implemented now

- **Point-in-time evidence:** each completed pilot-stock minute stores the full confluence, flow/liquidity, risk, and broad-market regime payload in PostgreSQL.
- **Forward outcomes:** 5, 15, 30, and 60-minute returns plus 60-minute maximum favourable/adverse excursion are filled only when those candles exist. The official close fills the EOD return during reconciliation.
- **Signal persistence:** a supportive classification starts as `building` and becomes `confirmed` only when at least two of the latest three completed minutes support it. Prior confirmation can become `weakening` or `failed`.
- **Execution quality:** the Upstox D5 book is normalized. Q-FAE estimates buy/sell slippage for a configurable reference order and checks current spread, three-minute spread stability, depth-imbalance stability, traded value, and quote freshness.
- **Tradability gates:** circuit distance and opening-gap/ATR are enforced. Missing ASM/GSM/trade-to-trade and portfolio-capital inputs remain visibly `unavailable`; they never silently pass.
- **Persistent market regime:** NIFTY direction, current and rolling breadth, sector participation, India VIX direction and acceleration produce `risk_on`, `mixed`, `risk_off`, or `insufficient` once per completed minute.
- **F&O contract:** evidence responses expose a provider-neutral derivatives-confirmation object. It remains unavailable until cash-to-derivative mapping and expiry selection are implemented.
- **Financial context:** Upstox quarterly consolidated income-statement and cash-flow facts are stored separately from event facts and interpretations.
- **Financial-result cache:** quarterly income statements and annual income, cash-flow and balance-sheet responses are content-versioned. Latest-quarter snapshots younger than 30 days are reused per stock by both preparation and the dashboard utility.
- **Explainable pilot ranking:** every completed-minute evidence record now includes a versioned long-continuation score. Component weights, contributions, coverage, persistence adjustment and invalidating risk gates remain inspectable; the model is explicitly labelled provisional until backtested.

## API

- `GET /api/v1/market/regime`
- `GET /api/v1/market/risk`
- `GET /api/v1/market/outcomes?session_date=YYYY-MM-DD`
- `GET /api/v1/market/outcomes?session_date=YYYY-MM-DD&instrument_key=NSE_EQ%7C...`
- `GET /api/v1/market/opportunities`

The existing `GET /api/v1/market/evidence` response includes `signal_persistence`, `risk_assessment`, and an explicit `derivatives_confirmation` availability state.

## Configuration

- `QFAE_RISK_REFERENCE_ORDER_VALUE_INR` controls the cash amount used for D5 slippage estimation.
- `QFAE_RISK_MAX_SLIPPAGE_BPS` rejects visible-book slippage above the limit.
- `QFAE_RISK_MIN_CIRCUIT_DISTANCE_PERCENT` rejects prices too close to either circuit.
- `QFAE_RISK_MAX_GAP_ATR` rejects unusually large opening gaps relative to daily ATR.
- `QFAE_RISK_MAX_SPREAD_RANGE_BPS` rejects unstable spreads across the latest three observations.
- `QFAE_RISK_CAPITAL_INR` is intentionally optional. Position, loss, and sector-exposure limits must not be presented as active without an explicit capital budget and portfolio state.

## Inputs staged next

1. Build cash-to-current-futures/option-expiry mapping and populate futures basis, price/OI state, and PCR only for eligible stocks.
2. Synchronize NSE surveillance indicators (ASM, GSM and trade-to-trade) into dated records used by the risk gate.
3. Add global instruments such as GIFT NIFTY and major overnight indices to the pre-market context. The current regime explicitly reports `global_market_context` as unavailable.
4. Add account/virtual-portfolio state before activating per-trade loss, position-size, daily-loss and sector-exposure limits.

## Provider contracts

- [Upstox full market feed](https://upstox.com/developer/api-documentation/get-market-data-feed/) supplies D5 depth and extended feed details including circuit limits.
- [Upstox income statement](https://upstox.com/developer/api-documentation/get-income-statement/) and cash-flow endpoints supply company-reported financial context.
- [Upstox OI API](https://upstox.com/developer/api-documentation/get-oi/) and the related analytics endpoints are candidates for derivatives confirmation.
- [NSE market surveillance](https://www.nseindia.com/static/regulations/exchange-market-surveillance-actions) is the authoritative source family for ASM/GSM/trade-to-trade restrictions.
