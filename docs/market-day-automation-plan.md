# Automated market-day operations

## Priority

This is Q-FAE's next implementation priority. The purpose is to replace the
manual Azure VM, Docker, backend, frontend, Upstox authentication, preparation
and live-feed sequence with a recoverable unattended market-day service.

The first release remains read-only. It must collect complete point-in-time
evidence reliably; it must not place, modify or cancel orders.

## Target daily lifecycle (Asia/Kolkata)

| Time | Automated action |
| --- | --- |
| 08:30 | Azure starts the VM. |
| 08:35 | Docker starts Q-FAE, Redis and PostgreSQL and verifies health. |
| 08:40 | The controller verifies credentials, database/Redis availability and the NSE calendar. |
| 08:45 | Incrementally refresh the approved 100-stock universe, instrument mapping, history and profiles. |
| 09:14 | Connect the Upstox Market Data Feed and confirm exchange/session state. |
| 09:15–15:30 | Build completed one-minute candles and persist features, context, evidence and outcomes. |
| 15:30 | Stop the live feed. |
| 15:40 | Reconcile official daily candles, refresh daily regimes and update minute profiles. |
| 16:15 | Record a completeness/health report and raise any missing or stale-data warning. |
| 16:30 | Azure may deallocate the VM after successful completion. |

Times are controller defaults, not assumptions about every session. The
official Upstox market-holiday and exchange-status responses must govern normal,
holiday and special-session behavior.

## Implementation order

### 1. Long-lived read-only Upstox authentication

- Add a dedicated `UPSTOX_ANALYTICS_TOKEN` configuration path.
- Prefer the Analytics Token for supported read-only REST and WebSocket calls.
- Keep the existing daily OAuth flow as a fallback and for future capabilities
  that the read-only token cannot support.
- Never expose either token to the browser, logs or API responses.
- Store the production token in Azure Key Vault or another protected runtime
  secret store; never commit it to Git.
- Surface token type, availability and expiry metadata without returning the
  credential.

### 2. Persistent market-day controller

- Run one controller instance with a database-backed session/state record.
- Check weekends, official NSE holidays and live exchange status.
- Make preparation, stream start/stop and reconciliation idempotent.
- Automatically prepare the configured 100-stock universe before open.
- Connect shortly before 09:15 and begin calculations only from completed
  regular-session minutes.
- Retain the existing 15:30 safety stop and 15:40 reconciliation/retry flow.
- Prevent duplicate streams or jobs after process restarts.
- Expose current phase, scheduled action, last success, retry count and safe
  errors through runtime status and the dashboard.

### 3. Restart and late-start recovery

- If Q-FAE starts during market hours, verify dependencies and token, perform
  the minimum required preparation, backfill 09:15 through the latest completed
  minute and then attach the live stream.
- If it restarts after market close and reconciliation is missing, reconcile
  the completed session automatically.
- Mark every session `complete`, `recovered`, `partial`, `holiday`, or `failed`.
- Backtesting must default to complete/recovered sessions and explicitly expose
  any inclusion of partial sessions.

### 4. Production service packaging

- Add production Dockerfiles for the FastAPI backend and compiled React
  frontend.
- Extend `compose.yaml` to run backend, frontend, Redis and PostgreSQL with
  health checks, persistent volumes and restart policies.
- Run Uvicorn without `--reload`; serve the compiled frontend rather than the
  Vite development server.
- Apply Alembic migrations before the API becomes ready.
- Do not require VS Code, PowerShell terminals or an open browser for evidence
  collection.

### 5. Azure VM scheduling

- Schedule the VM to start before the controller's preparation window on NSE
  weekdays.
- Schedule deallocation only after the health report/reconciliation window.
- Prefer a Linux VM with Docker Engine for unattended boot. If the present
  Windows VM is retained, verify that Docker and the Q-FAE startup task work
  without an interactive desktop login.
- Keep VM-level scheduling separate from the market controller: Azure manages
  compute availability; Q-FAE decides whether a market session should run.

### 6. Monitoring and notifications

- Alert on invalid/expired credentials, failed dependency health, incomplete
  preparation, stream disconnection, stale evidence, partial candle coverage,
  reconciliation failure and low disk capacity.
- Produce an end-of-day summary containing session coverage, first/last minute,
  stored candle/evidence counts, stream gaps and reconciliation result.
- Keep errors redacted and retain operational history in PostgreSQL.

## Acceptance criteria

The milestone is complete when:

1. Starting the Azure VM is sufficient to start all Q-FAE services.
2. No VS Code window, terminal or browser is required for daily collection.
3. A valid Analytics Token removes daily OTP/PIN authentication for supported
   read-only APIs.
4. On a normal NSE session, the controller prepares, connects, records every
   completed minute, stops and reconciles without button clicks.
5. A mid-session restart backfills the gap and records the session as recovered.
6. Holidays do not start a live stream, and special-session times are not
   silently treated as normal-session times.
7. The dashboard clearly reports automation state and incomplete sessions.
8. Backtesting can exclude partial sessions by default.

## Deferred boundary

Automated order placement is not part of this milestone. If Q-FAE later gains
trading capability, it must use a separately reviewed authentication, risk and
approval design rather than broadening the read-only automation implicitly.
