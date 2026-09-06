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

The API health endpoint is `http://localhost:8000/api/v1/health`; the UI runs on `http://localhost:5173` by default.

## Intentional scope of this skeleton

This setup does not connect to Upstox, store data, calculate indicators, produce scores, or place orders. It establishes boundaries so those capabilities can be added incrementally and tested.
