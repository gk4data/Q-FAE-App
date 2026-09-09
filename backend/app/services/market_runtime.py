"""Orchestrate pre-market loading and the Upstox live market session."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, time as datetime_time
from typing import Any

import upstox_client

from app.core.config import Settings
from app.models.market import (
    Candle,
    DailyRegimeSnapshot,
    LiveSnapshot,
    RelativeVolumeMetric,
    StockFeatureSnapshot,
    WatchlistItem,
)
from app.services.daily_regime import (
    aggregate_session_candle,
    build_daily_regime,
    cumulative_relative_volume,
    merge_daily_history,
)
from app.services.equity_universe import EquityUniverseService
from app.services.market_features import build_stock_features
from app.services.market_context import INDIA_TIMEZONE, build_market_context, calculate_relative_volume
from app.services.market_state import MarketStateStore
from app.services.upstox_auth import TokenCache
from app.services.upstox_market import (
    MARKET_CONTEXT_KEYS,
    MARKET_CONTEXT_SYMBOLS,
    MAX_FULL_FEED_INSTRUMENTS,
    NIFTY_50_KEY,
    RequestRateLimiter,
    SECTOR_INDEX_SYMBOLS,
    UpstoxMarketDataClient,
    normalize_feed_message,
)

logger = logging.getLogger(__name__)
NSE_MARKET_CLOSE = datetime_time(hour=15, minute=30)


def nse_market_close_at(now: datetime) -> datetime:
    """Return the normal NSE cash-market close for the supplied session date."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market-clock timestamps must include a timezone")
    local_now = now.astimezone(INDIA_TIMEZONE)
    return datetime.combine(local_now.date(), NSE_MARKET_CLOSE, tzinfo=INDIA_TIMEZONE)


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
        self._market_close_timer: threading.Timer | None = None
        self._last_context_bucket: int | None = None
        self._symbols: dict[str, str] = {}
        self._bootstrap: dict[str, Any] = {
            "state": "idle",
            "total": 0,
            "processed": 0,
            "history_loaded": 0,
            "daily_history_loaded": 0,
            "benchmark_daily_loaded": 0,
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
            "scheduled_stop_at": None,
            "error": None,
        }

    def status(self) -> dict[str, Any]:
        try:
            redis_available = self.state_store.ping()
        except Exception:
            redis_available = False
        with self._lock:
            bootstrap = dict(self._bootstrap)
            live = dict(self._live)
        if redis_available and bootstrap["state"] != "running":
            try:
                instruments = self._resolved_instruments(None)
                keys = [instrument["instrument_key"] for instrument in instruments]
                sectors = self.state_store.get_sectors()
                benchmark_keys = tuple(dict.fromkeys((NIFTY_50_KEY, *SECTOR_INDEX_SYMBOLS.keys())))
                bootstrap.update(
                    {
                        "total": len(keys),
                        "history_loaded": sum(self.state_store.has_candles(key) for key in keys),
                        "daily_history_loaded": sum(
                            self.state_store.has_daily_candles(key) for key in keys
                        ),
                        "benchmark_daily_loaded": sum(
                            self.state_store.has_daily_candles(key) for key in benchmark_keys
                        ),
                        "sectors_loaded": sum(key in sectors for key in keys),
                    }
                )
            except Exception:
                pass
        return {
                "cadence_seconds": self.settings.qfae_market_snapshot_interval_seconds,
                "pilot_size": self.settings.qfae_market_pilot_size,
                "redis_available": redis_available,
                "bootstrap": bootstrap,
                "live": live,
            }

    def get_watchlist(self, limit: int | None = None) -> list[WatchlistItem]:
        """Build a compact view of cached historical and live data for the pilot universe."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        snapshots = {
            snapshot.instrument_key: snapshot
            for snapshot in self.state_store.get_snapshots()
        }
        sectors = self.state_store.get_sectors()
        relative_volumes = self.state_store.get_relative_volumes()
        with self._lock:
            live_connected = bool(self._live["connected"])
        rows: list[WatchlistItem] = []

        for instrument in instruments:
            key = instrument["instrument_key"]
            snapshot = snapshots.get(key)
            history = self.state_store.get_candles(key, limit=self._history_limit())
            candle = snapshot.current_candle if snapshot and snapshot.current_candle else (
                history[-1] if history else None
            )
            ltp = snapshot.ltp if snapshot and snapshot.ltp is not None else (
                candle.close if candle else None
            )
            previous_close = snapshot.previous_close if snapshot else None
            if previous_close is None:
                previous_close = self._previous_session_close(history)
            change_percent = None
            if ltp is not None and previous_close:
                change_percent = ((ltp - previous_close) / previous_close) * 100

            spread_bps = None
            if snapshot and snapshot.best_bid_price and snapshot.best_ask_price:
                midpoint = (snapshot.best_bid_price + snapshot.best_ask_price) / 2
                if midpoint > 0:
                    spread_bps = ((snapshot.best_ask_price - snapshot.best_bid_price) / midpoint) * 10_000

            relative_volume = None
            relative_volume_metric = relative_volumes.get(key)
            if relative_volume_metric and candle:
                metric_date = relative_volume_metric.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
                candle_date = candle.timestamp.astimezone(INDIA_TIMEZONE).date()
                if metric_date == candle_date:
                    relative_volume = relative_volume_metric.relative_volume

            rows.append(
                WatchlistItem(
                    instrument_key=key,
                    symbol=instrument["symbol"],
                    company_name=instrument.get("company_name") or instrument["symbol"],
                    sector=sectors.get(key),
                    ltp=ltp,
                    previous_close=previous_close,
                    change_percent=change_percent,
                    open=candle.open if candle else None,
                    high=candle.high if candle else None,
                    low=candle.low if candle else None,
                    close=candle.close if candle else None,
                    volume=candle.volume if candle else None,
                    relative_volume=relative_volume,
                    spread_bps=spread_bps,
                    updated_at=(snapshot.received_at if snapshot else candle.timestamp if candle else None),
                    data_state=(
                        "live"
                        if snapshot and live_connected
                        else "cached"
                        if snapshot
                        else "history"
                        if candle
                        else "waiting"
                    ),
                )
            )
        return rows

    def get_features(self, limit: int | None = None) -> list[StockFeatureSnapshot]:
        """Return current-session features in approved-universe order."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        features = self.state_store.get_features()
        snapshots = {
            snapshot.instrument_key: snapshot
            for snapshot in self.state_store.get_snapshots()
        }
        today = datetime.now(INDIA_TIMEZONE).date()
        rows = []
        for instrument in instruments:
            key = instrument["instrument_key"]
            feature = features.get(key)
            snapshot = snapshots.get(key)
            if feature is None or snapshot is None or snapshot.current_candle is None:
                continue
            feature_date = feature.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
            snapshot_date = snapshot.current_candle.timestamp.astimezone(INDIA_TIMEZONE).date()
            if feature_date == snapshot_date == today:
                rows.append(feature)
        return rows

    def get_daily_regimes(self, limit: int | None = None) -> list[DailyRegimeSnapshot]:
        """Return multi-horizon evidence in approved-universe order."""
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        regimes = self.state_store.get_daily_regimes()
        return [regimes[item["instrument_key"]] for item in instruments if item["instrument_key"] in regimes]

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
                "daily_history_loaded": 0,
                "benchmark_daily_loaded": 0,
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
                    daily_history_loaded = False
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

                    try:
                        daily_candles = client.fetch_daily_history(
                            instrument["instrument_key"],
                            self.settings.qfae_daily_history_sessions,
                        )
                        self.state_store.save_daily_candles(daily_candles)
                        daily_history_loaded = True
                    except Exception as exc:
                        errors.append(f"{instrument['symbol']}: daily history: {exc}")

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
                        self._bootstrap["daily_history_loaded"] += int(daily_history_loaded)
                        self._bootstrap["sectors_loaded"] += int(sector_loaded)
                        self._bootstrap["errors"] += len(errors)
                        if errors:
                            self._bootstrap["recent_errors"] = (
                                self._bootstrap["recent_errors"] + errors
                            )[-25:]
                benchmark_keys = (NIFTY_50_KEY, *SECTOR_INDEX_SYMBOLS.keys())
                for instrument_key in dict.fromkeys(benchmark_keys):
                    try:
                        daily_candles = client.fetch_daily_history(
                            instrument_key,
                            self.settings.qfae_daily_history_sessions,
                        )
                        self.state_store.save_daily_candles(daily_candles)
                        with self._lock:
                            self._bootstrap["benchmark_daily_loaded"] += 1
                    except Exception as exc:
                        label = MARKET_CONTEXT_SYMBOLS.get(instrument_key, instrument_key)
                        with self._lock:
                            self._bootstrap["errors"] += 1
                            self._bootstrap["recent_errors"] = (
                                self._bootstrap["recent_errors"] + [f"{label}: daily history: {exc}"]
                            )[-25:]
            self._calculate_daily_regimes(datetime.now(UTC))
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
        now = datetime.now(INDIA_TIMEZONE)
        market_close = nse_market_close_at(now)
        if now >= market_close:
            raise MarketRuntimeError("The NSE cash market is closed after 3:30 PM IST")
        token = self._require_access_token()
        self._require_state_store()
        instruments = self._resolved_instruments(limit)
        symbols = {item["instrument_key"]: item["symbol"] for item in instruments}
        symbols.update(MARKET_CONTEXT_SYMBOLS)
        instrument_keys = list(dict.fromkeys([*symbols.keys()]))
        if len(instrument_keys) > MAX_FULL_FEED_INSTRUMENTS:
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
                "scheduled_stop_at": market_close.isoformat(),
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
            self._schedule_market_close(market_close, now)
            return dict(self._live)

    def stop_live(self, *, reason: str = "manual") -> dict[str, Any]:
        with self._lock:
            streamer = self._streamer
            market_close_timer = self._market_close_timer
            self._market_close_timer = None
        if market_close_timer is not None:
            market_close_timer.cancel()
        if streamer is not None:
            try:
                streamer.disconnect()
            except Exception as exc:
                raise MarketRuntimeError(f"Could not stop the live market stream: {exc}") from exc
        with self._lock:
            self._live["state"] = "market_closed" if reason == "market_close" else "stopped"
            self._live["connected"] = False
            self._live["subscribed"] = 0
            self._live["scheduled_stop_at"] = None
            self._streamer = None
            return dict(self._live)

    def _schedule_market_close(self, market_close: datetime, now: datetime) -> None:
        delay_seconds = max(0.0, (market_close - now).total_seconds())
        timer = threading.Timer(delay_seconds, self._stop_at_market_close)
        timer.name = "qfae-market-close"
        timer.daemon = True
        self._market_close_timer = timer
        timer.start()

    def _stop_at_market_close(self) -> None:
        try:
            self.stop_live(reason="market_close")
            logger.info("Upstox live feed stopped at the NSE cash-market close")
        except Exception:
            logger.exception("Could not stop the Upstox live feed at market close")

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
            all_snapshots = self.state_store.get_snapshots()
            snapshots_by_key = {snapshot.instrument_key: snapshot for snapshot in all_snapshots}
            feature_snapshots_by_key = dict(snapshots_by_key)
            for instrument_key, snapshot in snapshots_by_key.items():
                if instrument_key.startswith("NSE_EQ|"):
                    continue
                history = self.state_store.get_candles(instrument_key, limit=5)
                completed = self._latest_completed_candle(snapshot, history)
                feature_snapshots_by_key[instrument_key] = snapshot.model_copy(
                    update={"ltp": completed.close if completed else None}
                )
            active_equity_keys = {
                instrument["instrument_key"]
                for instrument in self._resolved_instruments(None)
            }
            selected_snapshots = [
                snapshot
                for snapshot in all_snapshots
                if not snapshot.instrument_key.startswith("NSE_EQ|")
                or snapshot.instrument_key in active_equity_keys
            ]
            sectors = self.state_store.get_sectors()
            enriched: list[LiveSnapshot] = []
            calculated_features: list[StockFeatureSnapshot] = []
            for snapshot in selected_snapshots:
                if not snapshot.instrument_key.startswith("NSE_EQ|"):
                    enriched.append(snapshot)
                    continue
                history = self.state_store.get_candles(
                    snapshot.instrument_key,
                    limit=self._history_limit(),
                )
                completed = self._latest_completed_candle(snapshot, history)
                relative_volume = calculate_relative_volume(completed, history) if completed else None
                relative_volume_metric = None
                if completed and relative_volume is not None:
                    relative_volume_metric = RelativeVolumeMetric(
                        instrument_key=snapshot.instrument_key,
                        relative_volume=relative_volume,
                        candle_timestamp=completed.timestamp,
                        calculated_at=as_of,
                    )
                    self.state_store.save_relative_volume(relative_volume_metric)
                    snapshot = snapshot.model_copy(
                        update={
                            "completed_candle_relative_volume": relative_volume,
                            "completed_candle_timestamp": completed.timestamp,
                        }
                    )
                else:
                    self.state_store.delete_relative_volume(snapshot.instrument_key)
                if completed:
                    try:
                        calculated_features.append(
                            build_stock_features(
                                snapshot,
                                completed,
                                history,
                                feature_snapshots_by_key,
                                sectors.get(snapshot.instrument_key),
                                relative_volume_metric,
                                as_of=as_of,
                                max_spread_bps=self.settings.qfae_feature_max_spread_bps,
                                min_traded_value_inr=self.settings.qfae_feature_min_traded_value_inr,
                            )
                        )
                    except Exception:
                        logger.exception("Feature calculation failed for %s", snapshot.symbol)
                        self.state_store.delete_features(snapshot.instrument_key)
                else:
                    self.state_store.delete_features(snapshot.instrument_key)
                enriched.append(snapshot)

            ranked_returns = sorted(
                feature.relative_strength.session_return_percent
                for feature in calculated_features
                if feature.relative_strength.session_return_percent is not None
            )
            for feature in calculated_features:
                session_return = feature.relative_strength.session_return_percent
                percentile = None
                if session_return is not None and ranked_returns:
                    percentile = round(
                        sum(value <= session_return for value in ranked_returns) / len(ranked_returns) * 100,
                        2,
                    )
                feature = feature.model_copy(
                    update={
                        "relative_strength": feature.relative_strength.model_copy(
                            update={"universe_percentile": percentile}
                        )
                    }
                )
                self.state_store.save_features(feature)
            self._calculate_daily_regimes(as_of)
            context = build_market_context(
                enriched,
                sectors,
                as_of=as_of,
                cadence_seconds=self.settings.qfae_market_snapshot_interval_seconds,
            )
            self.state_store.save_context(context)
            with self._lock:
                self._live["last_context_at"] = context.as_of.isoformat()
        except Exception as exc:
            logger.exception("Minute-level market context calculation failed")
            self._on_stream_error(exc)

    def _calculate_daily_regimes(self, as_of: datetime) -> None:
        instruments = self._resolved_instruments(None)
        sectors = self.state_store.get_sectors()
        snapshots = {
            snapshot.instrument_key: snapshot
            for snapshot in self.state_store.get_snapshots()
        }
        benchmark_keys = tuple(dict.fromkeys((NIFTY_50_KEY, *SECTOR_INDEX_SYMBOLS.keys())))
        benchmark_histories: dict[str, list[Candle]] = {}
        for instrument_key in benchmark_keys:
            history = self.state_store.get_daily_candles(
                instrument_key,
                self.settings.qfae_daily_history_sessions,
            )
            provisional, _ = self._provisional_daily_evidence(
                instrument_key,
                snapshots.get(instrument_key),
                as_of,
            )
            benchmark_histories[instrument_key] = merge_daily_history(history, provisional)

        for instrument in instruments:
            instrument_key = instrument["instrument_key"]
            history = self.state_store.get_daily_candles(
                instrument_key,
                self.settings.qfae_daily_history_sessions,
            )
            provisional, live_relative_volume = self._provisional_daily_evidence(
                instrument_key,
                snapshots.get(instrument_key),
                as_of,
            )
            regime = build_daily_regime(
                instrument_key,
                instrument["symbol"],
                sectors.get(instrument_key),
                merge_daily_history(history, provisional),
                benchmark_histories,
                as_of=as_of,
                live_relative_volume=live_relative_volume,
            )
            if regime is not None:
                self.state_store.save_daily_regime(regime)

    def _provisional_daily_evidence(
        self,
        instrument_key: str,
        snapshot: LiveSnapshot | None,
        as_of: datetime,
    ) -> tuple[Candle | None, float | None]:
        if snapshot is None:
            return None, None
        history = self.state_store.get_candles(instrument_key, limit=self._history_limit())
        completed = self._latest_completed_candle(snapshot, history)
        if completed is None:
            return None, None
        session_date = completed.timestamp.astimezone(INDIA_TIMEZONE).date()
        if session_date != as_of.astimezone(INDIA_TIMEZONE).date():
            return None, None
        return (
            aggregate_session_candle(instrument_key, history, completed),
            cumulative_relative_volume(history, completed),
        )

    def _history_limit(self) -> int:
        return min(10_000, (self.settings.qfae_market_history_days + 2) * 400)

    @staticmethod
    def _latest_completed_candle(snapshot: LiveSnapshot, history: list[Any]) -> Any | None:
        if not history or snapshot.current_candle is None:
            return None
        current = snapshot.current_candle
        current_date = current.timestamp.astimezone(INDIA_TIMEZONE).date()
        completed = [
            candle
            for candle in history
            if candle.timestamp < current.timestamp
            and candle.timestamp.astimezone(INDIA_TIMEZONE).date() == current_date
        ]
        return completed[-1] if completed else None

    @staticmethod
    def _previous_session_close(history: list[Candle]) -> float | None:
        if not history:
            return None
        latest_date = history[-1].timestamp.date()
        for candle in reversed(history[:-1]):
            if candle.timestamp.date() != latest_date:
                return candle.close
        return None

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
                        "company_name": str(row.get("requested_name") or candidate.get("name") or symbol),
                    }
                )
        effective_limit = limit if limit is not None else self.settings.qfae_market_pilot_size
        instruments = instruments[:effective_limit]
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
