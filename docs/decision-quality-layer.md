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
- **Corporate-action facts:** the preparation flow now fetches Upstox events by ISIN and idempotently stores dividend, split, bonus, rights and other provider facts with announcement/ex/record dates and the untouched source payload.
- **Deterministic corporate-action assessment:** versioned rules classify each event, select the last daily close before the announcement/event date, and calculate available dividend yield, offer premium, rights dilution/discount, and split/bonus magnitude. Materiality and conservative sentiment remain separate fields.
- **Safe adjusted-series overlay:** raw provider candles remain untouched. Versioned dividend, bonus and verified face-value split factors produce a separate adjusted-candle response; ambiguous mechanical terms are marked `unavailable` instead of guessed.
- **Official filing evidence:** preparation best-effort synchronizes matching NSE corporate announcements, their attachment URLs, exchange text and untouched response metadata. A filing outage is reported but cannot stop market history preparation.
- **Financial context:** Upstox quarterly consolidated income-statement and cash-flow facts are stored separately from event facts and interpretations.
- **Grounded AI adapter:** AI interpretation is opt-in. It runs only with an explicitly configured model and supporting documents, uses strict structured output, stores no API response at OpenAI, and rejects scores that do not cite a supplied document ID.
- **Event outcomes and calibration:** 1/5/20-session raw and NIFTY-relative returns are recorded. Category/direction buckets require at least 30 observations before being labelled ready; the report never changes live weights automatically.
- **Live evidence context:** active events and their deterministic or grounded-AI impact appear beside the minute evidence. They are contextual and remain outside confluence weights until outcome validation is sufficient.

## API

- `GET /api/v1/market/regime`
- `GET /api/v1/market/risk`
- `GET /api/v1/market/outcomes?session_date=YYYY-MM-DD`
- `GET /api/v1/market/outcomes?session_date=YYYY-MM-DD&instrument_key=NSE_EQ%7C...`
- `GET /api/v1/market/corporate-actions`
- `GET /api/v1/market/corporate-action-assessments`
- `GET /api/v1/market/adjusted-candles?instrument_key=NSE_EQ%7C...&interval=day`
- `GET /api/v1/market/corporate-action-documents`
- `GET /api/v1/market/corporate-action-ai`
- `GET /api/v1/market/corporate-action-outcomes`
- `GET /api/v1/market/corporate-action-calibration`

The existing `GET /api/v1/market/evidence` response now includes `signal_persistence`, `risk_assessment`, `corporate_action_context`, and an explicit `derivatives_confirmation` availability state.

## Configuration

- `QFAE_RISK_REFERENCE_ORDER_VALUE_INR` controls the cash amount used for D5 slippage estimation.
- `QFAE_RISK_MAX_SLIPPAGE_BPS` rejects visible-book slippage above the limit.
- `QFAE_RISK_MIN_CIRCUIT_DISTANCE_PERCENT` rejects prices too close to either circuit.
- `QFAE_RISK_MAX_GAP_ATR` rejects unusually large opening gaps relative to daily ATR.
- `QFAE_RISK_MAX_SPREAD_RANGE_BPS` rejects unstable spreads across the latest three observations.
- `QFAE_RISK_CAPITAL_INR` is intentionally optional. Position, loss, and sector-exposure limits must not be presented as active without an explicit capital budget and portfolio state.
- `QFAE_CORPORATE_DOCUMENTS_ENABLED` enables best-effort official NSE filing metadata ingestion.
- `QFAE_CORPORATE_ACTION_LOOKBACK_DAYS` bounds filing and AI enrichment; raw Upstox event history remains durable.
- `QFAE_CORPORATE_ACTION_AI_ENABLED`, `OPENAI_API_KEY`, and `QFAE_AI_MODEL` must all be deliberately configured to activate AI analysis. AI is disabled by default.

## Inputs staged next

1. Build cash-to-current-futures/option-expiry mapping and populate futures basis, price/OI state, and PCR only for eligible stocks.
2. Synchronize NSE surveillance indicators (ASM, GSM and trade-to-trade) into dated records used by the risk gate.
3. Add global instruments such as GIFT NIFTY and major overnight indices to the pre-market context. The current regime explicitly reports `global_market_context` as unavailable.
4. Add account/virtual-portfolio state before activating per-trade loss, position-size, daily-loss and sector-exposure limits.

Deterministic corporate-action scores are not model weights. Splits and bonuses are marked economically neutral; rights, merger and other context-dependent actions retain explicit cautions for later filing/document and AI review.

Corporate actions and surveillance lists are time-varying facts. Store every version with effective dates; never overwrite history with today's classification.

## Provider contracts

- [Upstox full market feed](https://upstox.com/developer/api-documentation/get-market-data-feed/) supplies D5 depth and extended feed details including circuit limits.
- [Upstox corporate actions](https://upstox.com/developer/api-documentation/get-corporate-actions/) supplies split, bonus, dividend and rights events by ISIN.
- [Upstox income statement](https://upstox.com/developer/api-documentation/get-income-statement/) and cash-flow endpoints supply company-reported financial context.
- [NSE corporate filings](https://www.nseindia.com/companies-listing/corporate-filings-announcements) supplies official announcement metadata and attachment links.
- [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) supplies the optional strict-schema, non-stored AI interpretation contract.
- [Upstox OI API](https://upstox.com/developer/api-documentation/get-oi/) and the related analytics endpoints are candidates for derivatives confirmation.
- [NSE market surveillance](https://www.nseindia.com/static/regulations/exchange-market-surveillance-actions) is the authoritative source family for ASM/GSM/trade-to-trade restrictions.
