# Q-FAE

Quantitative Financial Algorithm for Equity — a local-first, real-time Indian equity intelligence platform.

## Architecture

```text
Upstox REST + Market Data Feed V3
              |
       FastAPI backend
              |
      Redis + PostgreSQL
              |
     React / TypeScript UI
```

Upstox is the market-data provider; FastAPI is Q-FAE's backend. The backend will normalize provider data and expose Q-FAE-owned REST/WebSocket APIs to the frontend.

## Repository layout

- `backend/` — FastAPI application and future provider adapters, feature services, and API routes.
- `frontend/` — React/TypeScript dashboard, built with Vite.
- `.devcontainer/` — optional GitHub Codespaces / VS Code Dev Container configuration.
- `compose.yaml` — local Redis and PostgreSQL services.

## Local setup

1. Copy `.env.example` to `.env` and enter only local configuration values. Do not commit `.env`.
2. Start Redis and PostgreSQL: `docker compose up -d`.
3. Start the API:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   python -m alembic upgrade head
   uvicorn app.main:app --reload --port 8000
   ```

4. In a second terminal, start the UI:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

The API health endpoint is `http://localhost:8000/api/v1/health`; PostgreSQL health is available at `http://localhost:8000/api/v1/health/database`; the UI runs on `http://localhost:3000` by default.

## Equity universe refresh

`Stock List.xlsx` is the source list for the Q-FAE equity universe. Refreshing the universe downloads the current public Upstox NSE instrument master, maps the requested company names to instrument keys, and writes `data/instruments/upstox_nse_equity_universe.json`.

Start the API, then call:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/instruments/refresh
```

The frontend's future **Get instrument list** action will call this same endpoint. The mapping records `resolved`, `needs_review`, and `unmatched` rows. Only `resolved` rows are safe to subscribe to automatically.

## Upstox sign-in

The frontend redirects the browser to `GET /api/v1/auth/upstox/login`. Q-FAE validates a one-time OAuth state value in its callback, exchanges the authorization code on the backend, and caches the bearer token locally at `.qfae/upstox_access_token.json`. The token is ignored by Git and is never returned through a frontend endpoint.

The Upstox developer application must register this exact redirect URI:

```text
http://localhost:8000/api/v1/auth/upstox/callback
```

Set the same value for `UPSTOX_REDIRECT_URI` in your local `.env`; also set `QFAE_FRONTEND_URL=http://localhost:3000` when using the local Vite frontend.

## Minute-based market data

Q-FAE now has a provider-backed market-day foundation. It uses Upstox Historical Candle V3 for recent one-minute OHLCV, Company Profile for sector metadata, Market Data Feed V3 in `full` mode for live equity/index updates, Redis for transient candles, quotes, and minute-level context, and PostgreSQL for durable daily history.

Start Redis and PostgreSQL before using the market endpoints, then apply any pending migration:

```powershell
docker compose up -d redis postgres
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

After signing in through the frontend, use the Market Workspace buttons to **Prepare 100 stocks** and **Start live feed**. The dashboard displays LTP, change, one-minute OHLCV, relative volume, spread, sector, and whether each value is live, cached, historical, or waiting.

One hundred stocks is the application default during the expanded evidence-collection phase (`QFAE_MARKET_PILOT_SIZE=100`). This is intentionally below the provider's Full-feed capacity while the local one-minute calculation and persistence latency is measured. Historical loading runs in the background and is throttled below Upstox's published standard-API limits. The dashboard shows its progress; the API endpoints remain available for diagnostics and future automation. The live session also subscribes to NIFTY 50, India VIX, and thirteen NIFTY sector indices so sector direction is measured from provider benchmarks rather than inferred from the equity universe.

Each manually started live session schedules a backend safety stop for the normal NSE cash-market close at 3:30 PM IST. The API refuses to start a new normal live session after that time. Exchange holidays and announced special sessions will be handled by the future market-calendar controller.

Read the normalized state through:

- `GET /api/v1/market/candles?instrument_key=NSE_EQ%7C...`
- `GET /api/v1/market/watchlist`
- `GET /api/v1/market/context`
- `GET /api/v1/market/features`
- `GET /api/v1/market/daily-regimes`
- `GET /api/v1/market/minute-profiles?instrument_key=NSE_EQ%7C...`
- `GET /api/v1/market/evidence`
- `GET /api/v1/market/opportunities`
- `GET /api/v1/market/confirmations`
- `GET /api/v1/market/risk`
- `GET /api/v1/market/regime`
- `GET /api/v1/market/outcomes?session_date=YYYY-MM-DD`
- `GET /api/v1/market/corporate-actions`
- `GET /api/v1/market/corporate-action-assessments`
- `GET /api/v1/market/adjusted-candles?instrument_key=NSE_EQ%7C...&interval=day`
- `GET /api/v1/market/corporate-action-documents`
- `GET /api/v1/market/corporate-action-ai`
- `GET /api/v1/market/corporate-action-outcomes`
- `GET /api/v1/market/corporate-action-calibration`
- `POST /api/v1/market/financial-results/check?limit=100`
- `GET /api/v1/market/financial-metrics`
- `POST /api/v1/market/reconcile?session_date=YYYY-MM-DD`
- `GET /api/v1/market/reconciliations?session_date=YYYY-MM-DD`
- `WS /api/v1/market/stream`

The context snapshot is recalculated once per minute and currently includes NIFTY 50 and NIFTY Bank direction, India VIX, market breadth, median spread, sector breadth/performance, liquidity coverage, stale-data coverage, and same-minute-of-day relative-volume leaders.

The [intraday feature engine](docs/intraday-feature-engine.md) calculates VWAP, opening gap/ranges, relative strength, momentum quality, volume acceleration/RVOL, pullback quality, ATR/volatility, and liquidity inputs after each completed minute. Its dashboard matrix exposes the raw measurements and availability state; it does not yet create a trade score.

The [daily regime engine](docs/daily-regime-engine.md) adds independent 5/20/60/120/250-session performance, moving-average trend, price structure, daily participation, volatility, and benchmark-relative evidence. Older weak performance is retained as context and never used as an automatic veto against fresh strength.

The [validated evidence-confluence layer](docs/evidence-confluence.md) integrates current intraday technicals, daily regime, NIFTY/sector relative strength, and volume/liquidity confirmation as transparent raw inputs. The [provisional opportunity-ranking layer](docs/opportunity-ranking.md) applies explicit, configurable pilot weights, data-coverage penalties, persistence confirmation, and hard risk invalidations to rank long-continuation candidates. The [after-market reconciliation flow](docs/after-market-reconciliation.md) replaces provisional daily evidence with the official provider candle and records data-quality differences.

The [volume and liquidity confirmation contract](docs/volume-liquidity-confirmation.md) combines RVOL and acceleration with spread and traded-value gates. High activity cannot be labelled confirmed when execution quality is rejected.

The [decision-quality layer](docs/decision-quality-layer.md) adds two-of-three-minute signal persistence, D5 slippage/circuit/tradability checks, persistent market regime, point-in-time forward-outcome tracking, safe corporate-action adjustments, official filing evidence, optional citation-grounded AI interpretation, and event calibration. NSE surveillance synchronization, global context and mapped F&O confirmation remain explicit staged inputs rather than silently assumed data.

The [financial-result caching policy](docs/financial-result-caching.md) stores content-versioned quarterly and annual Upstox statements. **Prepare 100 stocks** and the dashboard utility reuse a latest-quarter snapshot for 30 days, while older-quarter, stale or missing data triggers a provider refresh.

The [financial-metric layer](docs/financial-metrics.md) calculates versioned QoQ/YoY growth, margins, cash conversion, explicit debt measures, ROE/ROCE and EPS history. Available metrics now feed the bounded fundamental component of the provisional pilot score; missing fields reduce coverage instead of becoming favourable values.

The dashboard exposes the latest stored values for every pilot stock in a dedicated **Financials (Qtrly/Yearly)** tab. It reads PostgreSQL when opened, stays outside the five-second live refresh, and does not trigger a provider refresh.

Selecting a stock name in **Opportunity Ranking** opens a dynamic stock-detail tab. It combines the quote, rank explanation, market context, intraday technicals, relative strength, volume/liquidity, daily regime, validated evidence, financial metrics and corporate-action context in responsive cards rather than another wide table.

The top of **Opportunity Ranking** contains an interactive Apache ECharts Alpha Matrix for the complete active universe. It plots Opportunity Score against a provisional coverage-and-persistence confidence proxy, sizes bubbles by liquidity/execution quality, colours them by status, and links every bubble to the same stock-detail view.

The first preparation backfills configured daily and one-minute history into PostgreSQL. Later preparations hydrate Redis from PostgreSQL and request only overlapping updates: five days for daily candles and two days for one-minute candles. Completed live minutes are persisted once per minute, while the still-forming candle remains only in Redis. One-minute rows have configurable 35-day retention and produce per-stock minute-of-session profiles used as the durable RVOL baseline. See the [historical-data storage policy](docs/historical-data-storage.md) for the implemented boundary and remaining full-universe work.

Order placement, scoring, ML predictions, and automated trading are intentionally outside this phase.

The approved candidate inputs are maintained in [the model factor register](docs/model-factor-register.md). Pilot-v1 implements only the available long-continuation inputs. Its direction, weights, thresholds and interactions remain provisional until point-in-time Indian-market backtesting supports calibration.

The approved [intraday focus-universe policy](docs/intraday-focus-universe.md) uses the first 30 minutes to form a provisional Focus list without discarding the rest of the 100-stock evidence universe. Background stocks remain monitored and recorded so late movers and early-leader failures remain measurable.
