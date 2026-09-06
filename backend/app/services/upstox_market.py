"""Upstox V3 REST and live-feed normalization for equity market data."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.models.market import Candle, LiveSnapshot

UPSTOX_API_ROOT = "https://api.upstox.com"
NIFTY_50_KEY = "NSE_INDEX|Nifty 50"
NIFTY_BANK_KEY = "NSE_INDEX|Nifty Bank"
INDIA_VIX_KEY = "NSE_INDEX|India VIX"
MARKET_CONTEXT_KEYS = (NIFTY_50_KEY, NIFTY_BANK_KEY, INDIA_VIX_KEY)
INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


class UpstoxMarketDataError(RuntimeError):
    """Raised for provider or response-contract failures without leaking credentials."""


class RequestRateLimiter:
    """Thread-safe limiter respecting both per-second and per-minute ceilings."""

    def __init__(
        self,
        per_second: int,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if per_second < 1 or per_minute < 1:
            raise ValueError("rate limits must be positive")
        self._per_second = per_second
        self._per_minute = per_minute
        self._clock = clock
        self._sleeper = sleeper
        self._second: deque[float] = deque()
        self._minute: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            wait_for = 0.0
            with self._lock:
                now = self._clock()
                while self._second and now - self._second[0] >= 1.0:
                    self._second.popleft()
                while self._minute and now - self._minute[0] >= 60.0:
                    self._minute.popleft()
                if len(self._second) >= self._per_second:
                    wait_for = max(wait_for, 1.0 - (now - self._second[0]))
                if len(self._minute) >= self._per_minute:
                    wait_for = max(wait_for, 60.0 - (now - self._minute[0]))
                if wait_for <= 0:
                    self._second.append(now)
                    self._minute.append(now)
                    return
            self._sleeper(wait_for)


def parse_candle_rows(instrument_key: str, rows: Iterable[Any]) -> list[Candle]:
    """Normalize Upstox array candles into typed Q-FAE candles."""
    candles: list[Candle] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise UpstoxMarketDataError("Upstox returned an invalid candle row")
        try:
            timestamp = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            candles.append(
                Candle(
                    instrument_key=instrument_key,
                    timestamp=timestamp,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=max(0, int(row[5])),
                    open_interest=max(0, int(row[6])) if len(row) > 6 and row[6] is not None else 0,
                )
            )
        except (TypeError, ValueError) as exc:
            raise UpstoxMarketDataError("Upstox returned an invalid candle value") from exc
    return sorted(candles, key=lambda candle: candle.timestamp)


def keep_latest_sessions(candles: Iterable[Candle], sessions: int) -> list[Candle]:
    """Retain the newest N exchange-session dates from a candle response."""
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    session_dates = sorted({candle.timestamp.date() for candle in ordered})[-sessions:]
    allowed = set(session_dates)
    return [candle for candle in ordered if candle.timestamp.date() in allowed]


def _milliseconds_to_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_feed_message(
    message: Mapping[str, Any],
    symbols: Mapping[str, str],
) -> list[LiveSnapshot]:
    """Normalize one SDK-decoded Market Data Feed V3 message."""
    feeds = message.get("feeds")
    if not isinstance(feeds, Mapping):
        return []
    received_at = _milliseconds_to_datetime(message.get("currentTs")) or datetime.now(UTC)
    snapshots: list[LiveSnapshot] = []
    for instrument_key, raw_feed in feeds.items():
        if not isinstance(raw_feed, Mapping):
            continue
        full_feed = raw_feed.get("fullFeed")
        if not isinstance(full_feed, Mapping):
            full_feed = {}
        market_data = full_feed.get("marketFF") or full_feed.get("indexFF")
        if not isinstance(market_data, Mapping):
            market_data = raw_feed.get("firstLevelWithGreeks")
        if not isinstance(market_data, Mapping):
            continue

        ltpc = market_data.get("ltpc") if isinstance(market_data.get("ltpc"), Mapping) else {}
        market_level = market_data.get("marketLevel")
        depth = market_level.get("bidAskQuote") if isinstance(market_level, Mapping) else None
        if not isinstance(depth, list):
            first_depth = market_data.get("firstDepth")
            depth = [first_depth] if isinstance(first_depth, Mapping) else []
        best_depth = depth[0] if depth and isinstance(depth[0], Mapping) else {}

        current_candle = None
        market_ohlc = market_data.get("marketOHLC")
        ohlc_values = market_ohlc.get("ohlc") if isinstance(market_ohlc, Mapping) else []
        if isinstance(ohlc_values, list):
            minute_row = next(
                (item for item in ohlc_values if isinstance(item, Mapping) and item.get("interval") == "I1"),
                None,
            )
            if minute_row:
                timestamp = _milliseconds_to_datetime(minute_row.get("ts"))
                try:
                    if timestamp is not None:
                        current_candle = Candle(
                            instrument_key=str(instrument_key),
                            timestamp=timestamp,
                            open=float(minute_row["open"]),
                            high=float(minute_row["high"]),
                            low=float(minute_row["low"]),
                            close=float(minute_row["close"]),
                            volume=max(0, int(minute_row.get("vol", 0))),
                        )
                except (KeyError, TypeError, ValueError):
                    current_candle = None

        snapshots.append(
            LiveSnapshot(
                instrument_key=str(instrument_key),
                symbol=symbols.get(str(instrument_key), str(instrument_key).split("|")[-1]),
                received_at=received_at,
                last_trade_at=_milliseconds_to_datetime(ltpc.get("ltt")),
                ltp=_optional_float(ltpc.get("ltp")),
                previous_close=_optional_float(ltpc.get("cp")),
                last_trade_quantity=_optional_int(ltpc.get("ltq")),
                total_traded_volume=_optional_int(market_data.get("vtt")),
                average_traded_price=_optional_float(market_data.get("atp")),
                best_bid_price=_optional_float(best_depth.get("bidP")),
                best_bid_quantity=_optional_int(best_depth.get("bidQ")),
                best_ask_price=_optional_float(best_depth.get("askP")),
                best_ask_quantity=_optional_int(best_depth.get("askQ")),
                total_buy_quantity=_optional_int(market_data.get("tbq")),
                total_sell_quantity=_optional_int(market_data.get("tsq")),
                current_candle=current_candle,
            )
        )
    return snapshots


class UpstoxMarketDataClient:
    """Small REST adapter limited to endpoints needed by the market-day bootstrap."""

    def __init__(self, access_token: str, limiter: RequestRateLimiter | None = None) -> None:
        self._limiter = limiter
        self._client = httpx.Client(
            base_url=UPSTOX_API_ROOT,
            headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> UpstoxMarketDataClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_recent_minute_history(
        self,
        instrument_key: str,
        sessions: int,
        *,
        as_of: date | None = None,
    ) -> list[Candle]:
        as_of = as_of or datetime.now(INDIA_TIMEZONE).date()
        from_date = as_of - timedelta(days=max(10, sessions * 2 + 3))
        encoded_key = quote(instrument_key, safe="")
        payload = self._get(
            f"/v3/historical-candle/{encoded_key}/minutes/1/{as_of.isoformat()}/{from_date.isoformat()}"
        )
        rows = payload.get("data", {}).get("candles")
        if not isinstance(rows, list):
            raise UpstoxMarketDataError("Upstox historical response did not contain candles")
        return keep_latest_sessions(parse_candle_rows(instrument_key, rows), sessions)

    def fetch_sector(self, isin: str) -> str | None:
        payload = self._get(f"/v2/fundamentals/{quote(isin, safe='')}/profile")
        data = payload.get("data")
        sector = data.get("sector") if isinstance(data, Mapping) else None
        return str(sector).strip() if sector else None

    def _get(self, path: str) -> dict[str, Any]:
        if self._limiter:
            self._limiter.acquire()
        try:
            response = self._client.get(path)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise UpstoxMarketDataError(f"Upstox request failed with HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstoxMarketDataError("Upstox request failed or returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise UpstoxMarketDataError("Upstox returned an unsuccessful response")
        return payload
