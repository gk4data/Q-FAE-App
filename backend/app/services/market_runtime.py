"""Orchestrate pre-market loading and the Upstox live market session."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

import upstox_client

from app.core.config import Settings
from app.models.market import LiveSnapshot
from app.services.equity_universe import EquityUniverseService
from app.services.market_context import build_market_context, calculate_relative_volume
from app.services.market_state import MarketStateStore
from app.services.upstox_auth import TokenCache
from app.services.upstox_market import (
    MARKET_CONTEXT_KEYS,
    RequestRateLimiter,
    UpstoxMarketDataClient,
    normalize_feed_message,
)

logger = logging.getLogger(__name__)


class MarketRuntimeError(RuntimeError):
    """Raised when a requested market operation cannot start safely."""


class MarketRuntime:
    """Single-process coordinator for background bootstrap and live streaming."""

    def __init__(
        self,
        settings: Settings,
        state_store: MarketStateStore,
        universe_service: EquityUniverseService,
    ) -> None:
        self.settings = settings
        self.state_store = state_store
        self.universe_service = universe_service
        self._lock = threading.RLock()
        self._bootstrap_thread: threading.Thread | None = None
        self._stream_thread: threading.Thread | None = None
        self._streamer: Any | None = None
        self._context_timer: threading.Timer | None = None
        self._last_context_bucket: int | None = None
        self._symbols: dict[str, str] = {}
        self._bootstrap: dict[str, Any] = {
            "state": "idle",
            "total": 0,
            "processed": 0,
            "history_loaded": 0,
            "sectors_loaded": 0,
            "errors": 0,
            "started_at": None,
            "finished_at": None,
            "recent_errors": [],
        }
        self._live: dict[str, Any] = {
            "state": "stopped",
            "connected": False,
            "subscribed": 0,
            "last_message_at": None,
            "last_context_at": None,
            "error": None,
        }

    def status(self) -> dict[str, Any]:
        try:
            redis_available = self.state_store.ping()
        except Exception:
            redis_available = False
        with self._lock:
            return {
                "cadence_seconds": self.settings.qfae_market_snapshot_interval_seconds,
                "redis_available": redis_available,
                "bootstrap": dict(self._bootstrap),
                "live": dict(self._live),
            }

    def start_bootstrap(self, limit: int | None = None) -> dict[str, Any]:
        self._require_access_token()
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        with self._lock:
            if self._bootstrap_thread and self._bootstrap_thread.is_alive():
                raise MarketRuntimeError("Pre-market bootstrap is already running")
            self._bootstrap = {
                "state": "running",
                "total": len(instruments),
                "processed": 0,
                "history_loaded": 0,
                "sectors_loaded": 0,
                "errors": 0,
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "recent_errors": [],
            }
            self._bootstrap_thread = threading.Thread(
                target=self._run_bootstrap,
                args=(instruments,),
                name="qfae-pre-market-bootstrap",
                daemon=True,
            )
            self._bootstrap_thread.start()
            return dict(self._bootstrap)

    def _run_bootstrap(self, instruments: list[dict[str, str]]) -> None:
        limiter = RequestRateLimiter(
            self.settings.qfae_market_request_rate_per_second,
            self.settings.qfae_market_request_rate_per_minute,
        )
        try:
            with UpstoxMarketDataClient(self._require_access_token(), limiter) as client:
                for instrument in instruments:
                    errors: list[str] = []
                    history_loaded = False
                    sector_loaded = False
                    try:
                        candles = client.fetch_recent_minute_history(
                            instrument["instrument_key"],
                            self.settings.qfae_market_history_days,
                        )
                        self.state_store.save_candles(candles)
                        history_loaded = True
                    except Exception as exc:
                        errors.append(f"{instrument['symbol']}: history: {exc}")

                    isin = instrument.get("isin")
                    if isin:
                        try:
                            sector = client.fetch_sector(isin)
                            if sector:
                                self.state_store.save_sector(instrument["instrument_key"], sector)
                                sector_loaded = True
                        except Exception as exc:
                            errors.append(f"{instrument['symbol']}: sector: {exc}")

                    with self._lock:
                        self._bootstrap["processed"] += 1
                        self._bootstrap["history_loaded"] += int(history_loaded)
                        self._bootstrap["sectors_loaded"] += int(sector_loaded)
                        self._bootstrap["errors"] += len(errors)
                        if errors:
                            self._bootstrap["recent_errors"] = (
                                self._bootstrap["recent_errors"] + errors
                            )[-25:]
            with self._lock:
                self._bootstrap["state"] = "completed"
        except Exception as exc:
            logger.exception("Pre-market bootstrap stopped unexpectedly")
            with self._lock:
                self._bootstrap["state"] = "failed"
                self._bootstrap["recent_errors"] = (
                    self._bootstrap["recent_errors"] + [f"bootstrap: {exc}"]
                )[-25:]
                self._bootstrap["errors"] += 1
        finally:
            with self._lock:
                self._bootstrap["finished_at"] = datetime.now(UTC).isoformat()

    def start_live(self, limit: int | None = None) -> dict[str, Any]:
        token = self._require_access_token()
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        symbols = {item["instrument_key"]: item["symbol"] for item in instruments}
        symbols.update(
            {
                MARKET_CONTEXT_KEYS[0]: "NIFTY 50",
                MARKET_CONTEXT_KEYS[1]: "NIFTY BANK",
                MARKET_CONTEXT_KEYS[2]: "INDIA VIX",
            }
        )
        instrument_keys = list(dict.fromkeys([*symbols.keys()]))
        if len(instrument_keys) > 2000:
            raise MarketRuntimeError("A Full-feed connection supports at most 2,000 instrument keys")
        with self._lock:
            if self._stream_thread and self._stream_thread.is_alive():
                raise MarketRuntimeError("Live market stream is already running")
            self._symbols = symbols
            self._live = {
                "state": "connecting",
                "connected": False,
                "subscribed": len(instrument_keys),
                "last_message_at": None,
                "last_context_at": None,
                "error": None,
            }
            configuration = upstox_client.Configuration()
            configuration.access_token = token
            api_client = upstox_client.ApiClient(configuration)
            streamer = upstox_client.MarketDataStreamerV3(api_client, instrument_keys, "full")
            streamer.auto_reconnect(True, 10, 12)
            streamer.on("open", self._on_stream_open)
            streamer.on("message", self._on_stream_message)
            streamer.on("error", self._on_stream_error)
            streamer.on("close", self._on_stream_close)
            streamer.on("reconnecting", self._on_stream_reconnecting)
            streamer.on("autoReconnectStopped", self._on_reconnect_stopped)
            self._streamer = streamer
            self._stream_thread = threading.Thread(
                target=self._connect_stream,
                name="qfae-upstox-market-stream",
                daemon=True,
            )
            self._stream_thread.start()
            return dict(self._live)

    def stop_live(self) -> dict[str, Any]:
        with self._lock:
            streamer = self._streamer
        if streamer is not None:
            try:
                streamer.disconnect()
            except Exception as exc:
                raise MarketRuntimeError(f"Could not stop the live market stream: {exc}") from exc
        with self._lock:
            self._live["state"] = "stopped"
            self._live["connected"] = False
            self._streamer = None
            return dict(self._live)

    def _connect_stream(self) -> None:
        try:
            self._streamer.connect()
        except Exception as exc:
            self._on_stream_error(exc)

    def _on_stream_open(self) -> None:
        with self._lock:
            self._live["state"] = "connected"
            self._live["connected"] = True
            self._live["error"] = None

    def _on_stream_message(self, message: dict[str, Any]) -> None:
        try:
            snapshots = normalize_feed_message(message, self._symbols)
            for snapshot in snapshots:
                if snapshot.current_candle:
                    self.state_store.save_candles([snapshot.current_candle])
                self.state_store.save_snapshot(snapshot)
            received_at = datetime.now(UTC)
            with self._lock:
                self._live["last_message_at"] = received_at.isoformat()
            provider_time = message.get("currentTs")
            try:
                bucket = int(provider_time) // (self.settings.qfae_market_snapshot_interval_seconds * 1000)
            except (TypeError, ValueError):
                bucket = int(received_at.timestamp()) // self.settings.qfae_market_snapshot_interval_seconds
            self._queue_minute_context(bucket)
        except Exception as exc:
            logger.exception("Could not normalize an Upstox live-feed message")
            self._on_stream_error(exc)

    def _queue_minute_context(self, bucket: int) -> None:
        with self._lock:
            if self._last_context_bucket == bucket:
                return
            self._last_context_bucket = bucket
            if self._context_timer:
                self._context_timer.cancel()
            self._context_timer = threading.Timer(2.0, self._calculate_minute_context)
            self._context_timer.daemon = True
            self._context_timer.start()

    def _calculate_minute_context(self) -> None:
        try:
            as_of = datetime.now(UTC)
            enriched: list[LiveSnapshot] = []
            for snapshot in self.state_store.get_snapshots():
                if not snapshot.instrument_key.startswith("NSE_EQ|"):
                    enriched.append(snapshot)
                    continue
                history = self.state_store.get_candles(snapshot.instrument_key, limit=5000)
                completed = self._latest_completed_candle(snapshot, history)
                relative_volume = calculate_relative_volume(completed, history) if completed else None
                if completed and relative_volume is not None:
                    snapshot = snapshot.model_copy(
                        update={
                            "completed_candle_relative_volume": relative_volume,
                            "completed_candle_timestamp": completed.timestamp,
                        }
                    )
                    self.state_store.save_snapshot(snapshot)
                enriched.append(snapshot)
            context = build_market_context(
                enriched,
                self.state_store.get_sectors(),
                as_of=as_of,
                cadence_seconds=self.settings.qfae_market_snapshot_interval_seconds,
            )
            self.state_store.save_context(context)
            with self._lock:
                self._live["last_context_at"] = context.as_of.isoformat()
        except Exception as exc:
            logger.exception("Minute-level market context calculation failed")
            self._on_stream_error(exc)

    @staticmethod
    def _latest_completed_candle(snapshot: LiveSnapshot, history: list[Any]) -> Any | None:
        if not history:
            return None
        if snapshot.current_candle and history[-1].timestamp == snapshot.current_candle.timestamp:
            return history[-2] if len(history) > 1 else None
        return history[-1]

    def _on_stream_error(self, error: Any) -> None:
        safe_error = str(error).replace(self._access_token() or "<no-token>", "<redacted>")[:500]
        with self._lock:
            self._live["error"] = safe_error
            if not self._live["connected"]:
                self._live["state"] = "error"

    def _on_stream_close(self, *_: Any) -> None:
        with self._lock:
            self._live["connected"] = False
            if self._live["state"] != "stopped":
                self._live["state"] = "disconnected"

    def _on_stream_reconnecting(self, message: Any) -> None:
        with self._lock:
            self._live["state"] = "reconnecting"
            self._live["connected"] = False
            self._live["error"] = str(message)[:500]

    def _on_reconnect_stopped(self, message: Any) -> None:
        with self._lock:
            self._live["state"] = "reconnect_exhausted"
            self._live["connected"] = False
            self._live["error"] = str(message)[:500]

    def _resolved_instruments(self, limit: int | None) -> list[dict[str, str]]:
        try:
            universe = self.universe_service.load()
        except (FileNotFoundError, ValueError) as exc:
            raise MarketRuntimeError(str(exc)) from exc
        instruments: list[dict[str, str]] = []
        for row in universe.get("instruments", []):
            candidate = row.get("candidate") if isinstance(row, dict) else None
            if row.get("status") != "resolved" or not isinstance(candidate, dict):
                continue
            key = candidate.get("instrument_key")
            symbol = candidate.get("trading_symbol")
            if key and symbol:
                instruments.append(
                    {
                        "instrument_key": str(key),
                        "symbol": str(symbol),
                        "isin": str(candidate.get("isin") or ""),
                    }
                )
        if limit is not None:
            instruments = instruments[:limit]
        if not instruments:
            raise MarketRuntimeError("The approved universe has no resolved instruments")
        return instruments

    def _access_token(self) -> str | None:
        cached = TokenCache(self.settings.upstox_token_cache_path).load()
        return cached["access_token"] if cached else None

    def _require_access_token(self) -> str:
        token = self._access_token()
        if not token:
            raise MarketRuntimeError("A current Upstox login is required")
        return token

    def _require_state_store(self) -> None:
        try:
            if not self.state_store.ping():
                raise MarketRuntimeError("Redis is unavailable")
        except MarketRuntimeError:
            raise
        except Exception as exc:
            raise MarketRuntimeError("Redis is unavailable; start it with docker compose up -d redis") from exc
