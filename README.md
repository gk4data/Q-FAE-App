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
   uvicorn app.main:app --reload --port 8000
   ```

4. In a second terminal, start the UI:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

The API health endpoint is `http://localhost:8000/api/v1/health`; the UI runs on `http://localhost:3000` by default.

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

Q-FAE now has a provider-backed market-day foundation. It uses Upstox Historical Candle V3 for recent one-minute OHLCV, Company Profile for sector metadata, Market Data Feed V3 in `full` mode for live equity/index updates, and Redis for transient candles, quotes, and minute-level context.

Start Redis before using the market endpoints:

```powershell
docker compose up -d redis
```

After signing in through the frontend, use the Market Workspace buttons to **Prepare 20 stocks** and **Start live feed**. The dashboard displays LTP, change, one-minute OHLCV, relative volume, spread, sector, and whether each value is live, cached, historical, or waiting.

Twenty stocks is the application default during the pilot phase (`QFAE_MARKET_PILOT_SIZE=20`). Historical loading runs in the background and is throttled below Upstox's published standard-API limits. The dashboard shows its progress; the API endpoints remain available for diagnostics and future automation. The live session also subscribes to NIFTY 50, India VIX, and thirteen NIFTY sector indices so sector direction is measured from provider benchmarks rather than inferred from the small equity pilot.

Each manually started live session schedules a backend safety stop for the normal NSE cash-market close at 3:30 PM IST. The API refuses to start a new normal live session after that time. Exchange holidays and announced special sessions will be handled by the future market-calendar controller.

Read the normalized state through:

- `GET /api/v1/market/candles?instrument_key=NSE_EQ%7C...`
- `GET /api/v1/market/watchlist`
- `GET /api/v1/market/context`
- `GET /api/v1/market/features`
- `GET /api/v1/market/daily-regimes`
- `WS /api/v1/market/stream`

The context snapshot is recalculated once per minute and currently includes NIFTY 50 and NIFTY Bank direction, India VIX, market breadth, median spread, sector breadth/performance, liquidity coverage, stale-data coverage, and same-minute-of-day relative-volume leaders.

The [intraday feature engine](docs/intraday-feature-engine.md) calculates VWAP, opening gap/ranges, relative strength, momentum quality, volume acceleration/RVOL, pullback quality, ATR/volatility, and liquidity inputs after each completed minute. Its dashboard matrix exposes the raw measurements and availability state; it does not yet create a trade score.

The [daily regime engine](docs/daily-regime-engine.md) adds independent 5/20/60/120/250-session performance, moving-average trend, price structure, daily participation, volatility, and benchmark-relative evidence. Older weak performance is retained as context and never used as an automatic veto against fresh strength.

Before full-universe operation, implement the [historical-data storage policy](docs/historical-data-storage.md): permanent incremental daily history in PostgreSQL, bounded recent one-minute history for tradable stocks, rolling minute-of-day profiles, Redis for live state, and optional compressed research archives.

Order placement, scoring, ML predictions, and automated trading are intentionally outside this phase.

The approved candidate inputs for the future explainable opportunity model are maintained in [the model factor register](docs/model-factor-register.md). All listed factors should be retained for evaluation, while their direction, weights, and interactions remain subject to point-in-time backtesting on Indian-market data.
