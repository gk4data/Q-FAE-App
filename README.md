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

### One-click Windows start

After completing the one-time Python and Node.js setup below, double-click
`Start-QFAE.cmd` in the repository root. The launcher starts Docker Desktop when
needed, starts Redis and PostgreSQL, applies database migrations, starts the
backend and frontend in minimized service windows, waits for both applications,
and opens `http://localhost:3000/` in the default browser.

The launcher is safe to rerun when Q-FAE is already running. To see server logs
or stop either development server, restore its minimized PowerShell window and
press `Ctrl+C`. Docker data services can be stopped later from the repository
root with `docker compose stop`.

From PowerShell, the equivalent command is:

```powershell
.\Start-QFAE.ps1
```

Pass `-NoBrowser` when the browser should not be opened automatically.

To stop Q-FAE, double-click `Stop-QFAE.cmd`. It first disconnects the Upstox
stream or cancels a scheduled market-open start, then closes the Q-FAE backend
and frontend and stops the project Redis/PostgreSQL containers. Docker volumes
are preserved, so historical data is not deleted. Docker Desktop itself remains
running to avoid interrupting unrelated containers.

The PowerShell equivalent is:

```powershell
.\Stop-QFAE.ps1
```

Pass `-KeepContainers` to stop only the backend and frontend while leaving Redis
and PostgreSQL running.

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

The current Upstox NSE BOD master is the source of the Q-FAE equity universe. Each refresh cross-checks it against Upstox's suspended-instrument file and official NSE security/bhavdata reports, then writes `data/instruments/upstox_nse_equity_universe.json`. No manually maintained stock-list workbook is required.

Eligibility requires a normal NSE `EQ` company share, an official completed-session close of at least Rs 20, an issued-capital record, no current suspension, and market capitalization of at least Rs 500 crore. Market cap is calculated as NSE issued capital multiplied by the latest completed NSE close. ETFs and other non-company EQ instruments are rejected using NSE's security-type flag. The thresholds are configurable with `QFAE_MIN_SHARE_PRICE_INR` and `QFAE_MIN_MARKET_CAP_CRORE`.

Start the API, then call:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/instruments/refresh
```

The preparation action refreshes this snapshot before selecting stocks, and the instrument endpoint can refresh it independently. Only `resolved` rows are eligible for automatic subscription. Excluded rows retain a transparent reason so missing market-cap data is never treated as a pass.

## Upstox sign-in

The frontend redirects the browser to `GET /api/v1/auth/upstox/login`. Q-FAE validates a one-time OAuth state value in its callback, exchanges the authorization code on the backend, and caches the bearer token locally at `.qfae/upstox_access_token.json`. The token is ignored by Git and is never returned through a frontend endpoint.

The Upstox developer application must register this exact redirect URI:

```text
http://localhost:8000/api/v1/auth/upstox/callback
```

Set the same value for `UPSTOX_REDIRECT_URI` in your local `.env`; also set `QFAE_FRONTEND_URL=http://localhost:3000` when using the local Vite frontend.

For this read-only application, `UPSTOX_ANALYTICS_TOKEN` may instead contain the one-year Analytics Token generated in Upstox Developer Apps. When configured, Q-FAE prefers it for REST and WebSocket market data and reports the session as authenticated without exposing the token to the frontend. Leave the variable blank to continue using the normal daily OAuth flow.

## Minute-based market data

Q-FAE now has a provider-backed market-day foundation. It uses Upstox Historical Candle V3 for recent one-minute OHLCV, Company Profile for sector metadata, Market Data Feed V3 in `full` mode for live equity/index updates, Redis for transient candles, quotes, and minute-level context, and PostgreSQL for durable daily history.

Start Redis and PostgreSQL before using the market endpoints, then apply any pending migration:

```powershell
docker compose up -d redis postgres
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

After signing in through the frontend, use the single **Prepare universe & start live** button. The blocking path loads only the rolling admission window from PostgreSQL, refreshes benchmark history and selects the live universe. Q-FAE reads the official Upstox NSE timings for the date: before market open it arms the prepared feed to start automatically at the published opening time, during market hours it starts immediately, and after close or on a non-trading day it prepares without opening a stream. Full daily refreshes, missing minute profiles, sector metadata, execution-quality profiles and a capped financial-results batch continue afterward in memory-bounded 25-stock batches. Current-session minute backfill has priority over this optional enrichment. If available system memory falls below the configured reserve, enrichment pauses without stopping the live feed.

Preparation now covers every company that passes the provider-led NSE mainboard, market-cap and price gates. Previous-day turnover no longer controls admission or ordering. Rolling 10-session continuity and median traded value classify each company as Active, Watch-only or Dormant. Active stocks receive opportunity ranks based only on price/trend, participation, market/sector context, fundamentals and signal persistence. Rolling/current spread, D5 slippage and depth stability are reported separately as execution cautions and never suppress or reduce an Active stock's opportunity score or rank. Historical loading is incremental, stored in PostgreSQL and throttled below provider request limits. The live session also subscribes to NIFTY 50, India VIX, and thirteen NIFTY sector indices so sector direction is measured from provider benchmarks rather than inferred from the equity universe.

Each manually started live session schedules a backend safety stop for the normal NSE cash-market close at 3:30 PM IST. The API refuses to start a new normal live session after that time. Exchange holidays and announced special sessions will be handled by the future market-calendar controller.

The next priority milestone is the [automated market-day operations plan](docs/market-day-automation-plan.md): long-lived read-only Upstox authentication, an idempotent market-calendar controller, restart/backfill recovery, production Docker services, Azure VM scheduling, and completeness monitoring. Its acceptance target is a full session that requires no VS Code window, terminal, browser, preparation button, or live-feed button.

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
- `POST /api/v1/market/financial-results/check?limit=100`
- `GET /api/v1/market/financial-metrics`
- `POST /api/v1/market/reconcile?session_date=YYYY-MM-DD`
- `GET /api/v1/market/reconciliations?session_date=YYYY-MM-DD`
- `WS /api/v1/market/stream`

The context snapshot is recalculated once per minute and currently includes NIFTY 50 and NIFTY Bank direction, India VIX, market breadth, median spread, sector breadth/performance, liquidity coverage, stale-data coverage, and same-minute-of-day relative-volume leaders. Every current quote participates in the lightweight market screen. Expensive candle-history features are bounded to the strongest candidates, existing Focus/Cooling names, and a rotating discovery batch (300 stocks per minute by default), keeping a full-universe cycle within the one-minute cadence on the development VM.

The [intraday feature engine](docs/intraday-feature-engine.md) calculates VWAP, opening gap/ranges, relative strength, momentum quality, volume acceleration/RVOL, pullback quality, ATR/volatility, and liquidity inputs after each completed minute. Its dashboard matrix exposes the raw measurements and availability state; it does not yet create a trade score.

The [daily regime engine](docs/daily-regime-engine.md) adds independent 5/20/60/120/250-session performance, moving-average trend, price structure, daily participation, volatility, and benchmark-relative evidence. Older weak performance is retained as context and never used as an automatic veto against fresh strength.

The [validated evidence-confluence layer](docs/evidence-confluence.md) integrates current intraday technicals, daily regime, NIFTY/sector relative strength, and volume/liquidity confirmation as transparent raw inputs. The [provisional opportunity-ranking layer](docs/opportunity-ranking.md) applies explicit, configurable pilot weights, data-coverage penalties and persistence confirmation to rank long-continuation candidates while keeping execution risk separate. The [after-market reconciliation flow](docs/after-market-reconciliation.md) replaces provisional daily evidence with the official provider candle and records data-quality differences.

The [volume and liquidity confirmation contract](docs/volume-liquidity-confirmation.md) combines RVOL and acceleration with spread and traded-value gates. High activity cannot be labelled confirmed when execution quality is rejected.

The [decision-quality layer](docs/decision-quality-layer.md) adds two-of-three-minute signal persistence, D5 slippage/circuit/tradability checks, persistent market regime, and point-in-time forward-outcome tracking. NSE surveillance synchronization, global context and mapped F&O confirmation remain explicit staged inputs rather than silently assumed data.

The [financial-result caching policy](docs/financial-result-caching.md) stores content-versioned quarterly and annual Upstox statements. Background preparation checks only a capped batch per run so fundamentals can never delay live data; the dashboard utility remains available for an explicit wider refresh. Both paths reuse a latest-quarter snapshot for 30 days, while older-quarter, stale or missing data triggers a provider refresh.

The [financial-metric layer](docs/financial-metrics.md) calculates versioned QoQ/YoY growth, margins, cash conversion, explicit debt measures, ROE/ROCE and EPS history. Available metrics now feed the bounded fundamental component of the provisional pilot score; missing fields reduce coverage instead of becoming favourable values.

The dashboard exposes the latest stored values for every pilot stock in a dedicated **Financials (Qtrly/Yearly)** tab. It reads PostgreSQL when opened, stays outside the five-second live refresh, and does not trigger a provider refresh.

Selecting a stock name in **Opportunity Ranking** opens a dynamic stock-detail tab. It combines the quote, rank explanation, market context, intraday technicals, relative strength, volume/liquidity, daily regime, validated evidence and financial metrics in responsive cards rather than another wide table.

The top of **Opportunity Ranking** contains an interactive Apache ECharts Alpha Matrix for the complete active universe. It plots Opportunity Score against a provisional coverage-and-persistence confidence proxy, sizes bubbles by participation strength, colours them by status, and links every bubble to the same stock-detail view. Execution cautions remain visible in the ranking table but do not affect matrix position or bubble size.

Q-FAE also keeps one rolling latest-dashboard snapshot in Redis. When the feed stops after market close or the API process restarts, the frontend continues to show the most recently completed opportunity ranking, Alpha Matrix, market context and intraday features with an explicit as-of timestamp. The snapshot is replaced by the next completed live minute and is not a multi-day archive.

Preparation first reuses the compact rolling daily admission window already in Redis and reads only missing instruments from PostgreSQL before starting live collection. A background worker then refreshes configured daily history and fills only missing minute profiles in bounded batches; it does not load full-universe minute history into Redis. Starting at the opening bell skips unnecessary current-session backfill, while a later start fills the 09:15-to-current gap in the background before appending live candles. Completed live minutes are persisted once per minute, while the still-forming candle remains only in Redis. Daily and one-minute candles remain durable by default. Full evidence JSON is retained for only the strongest bounded candidates each minute, while the wider universe receives compact 15-minute and state-change checkpoints. Runtime status uses prepared counters rather than rescanning the full database and Redis universe on every dashboard poll. The dashboard, live table and analysis panels poll together once per minute. See the [local storage retention policy](docs/local-storage-retention.md) and [historical-data storage policy](docs/historical-data-storage.md).

Order placement, scoring, ML predictions, and automated trading are intentionally outside this phase.

The approved candidate inputs are maintained in [the model factor register](docs/model-factor-register.md). Pilot-v2 implements only the available long-continuation inputs. Its direction, weights, thresholds and interactions remain provisional until point-in-time Indian-market backtesting supports calibration.

The implemented [intraday focus-universe policy](docs/intraday-focus-universe.md) uses 9:15-9:30 as discovery, then promotes stocks after two qualifying completed minutes and demotes only after three materially weak red minutes. Constructive green pauses become visible **Focus - Cooling** candidates and return to active Focus immediately when strength resumes. Background stocks remain silently monitored every minute, and every state transition is retained in PostgreSQL for later funnel backtesting. A negative session return is never a standalone exclusion.

The same policy applies rolling liquidity admission before intraday ranking. A stock must trade in at least 8 of the latest 10 NIFTY sessions; otherwise it is Dormant. A qualifying stock remains Watch-only unless its 10-session median traded value is at least Rs 2 crore. Daily execution-quality profiles are still built from recorded minute evidence, but rolling/current spread, live D5 depth and estimated slippage are cautions only and cannot remove an otherwise valid opportunity.

Q-FAE accepts only normal NSE `EQ` company shares with market cap of at least Rs 500 crore and a completed close of at least Rs 20. SME series (`SM`, `ST`, and `SZ`), trade-for-trade series (`BE` and `BZ`), ETFs, other non-company instruments, suspended stocks, penny stocks, and stocks without sufficient official inputs are excluded before preparation. They cannot enter live subscriptions, evidence, ranking, or dashboard views.
