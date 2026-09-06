"""Redis-backed transient market state with an in-memory test implementation."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Protocol

from redis import Redis

from app.models.market import Candle, LiveSnapshot, MarketContext


class MarketStateStore(Protocol):
    def ping(self) -> bool: ...
    def save_candles(self, candles: Iterable[Candle]) -> int: ...
    def get_candles(self, instrument_key: str, limit: int = 500) -> list[Candle]: ...
    def save_snapshot(self, snapshot: LiveSnapshot) -> None: ...
    def get_snapshots(self) -> list[LiveSnapshot]: ...
    def save_sector(self, instrument_key: str, sector: str) -> None: ...
    def get_sectors(self) -> dict[str, str]: ...
    def save_context(self, context: MarketContext) -> None: ...
    def get_context(self) -> MarketContext | None: ...


class RedisMarketStateStore:
    """Keep recent candles and current market state in Redis."""

    _SNAPSHOTS_KEY = "qfae:market:snapshots"
    _SECTORS_KEY = "qfae:market:sectors"
    _CONTEXT_KEY = "qfae:market:context"

    def __init__(self, redis_url: str, retention_days: int = 35) -> None:
        self._redis = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        self._retention = timedelta(days=retention_days)

    def ping(self) -> bool:
        return bool(self._redis.ping())

    @staticmethod
    def _candle_key(instrument_key: str) -> str:
        return f"qfae:market:candles:1m:{instrument_key}"

    def save_candles(self, candles: Iterable[Candle]) -> int:
        candle_list = list(candles)
        if not candle_list:
            return 0
        grouped: dict[str, list[Candle]] = {}
        for candle in candle_list:
            grouped.setdefault(candle.instrument_key, []).append(candle)
        cutoff = datetime.now().astimezone() - self._retention
        with self._redis.pipeline(transaction=False) as pipeline:
            for instrument_key, values in grouped.items():
                key = self._candle_key(instrument_key)
                for candle in values:
                    score = candle.timestamp.timestamp()
                    pipeline.zremrangebyscore(key, score, score)
                    pipeline.zadd(key, {candle.model_dump_json(): score})
                pipeline.zremrangebyscore(key, "-inf", cutoff.timestamp())
                pipeline.expire(key, int(self._retention.total_seconds()))
            pipeline.execute()
        return len(candle_list)

    def get_candles(self, instrument_key: str, limit: int = 500) -> list[Candle]:
        values = self._redis.zrange(self._candle_key(instrument_key), -limit, -1)
        return [Candle.model_validate_json(value) for value in values]

    def save_snapshot(self, snapshot: LiveSnapshot) -> None:
        self._redis.hset(self._SNAPSHOTS_KEY, snapshot.instrument_key, snapshot.model_dump_json())

    def get_snapshots(self) -> list[LiveSnapshot]:
        return [LiveSnapshot.model_validate_json(value) for value in self._redis.hvals(self._SNAPSHOTS_KEY)]

    def save_sector(self, instrument_key: str, sector: str) -> None:
        self._redis.hset(self._SECTORS_KEY, instrument_key, sector)

    def get_sectors(self) -> dict[str, str]:
        return dict(self._redis.hgetall(self._SECTORS_KEY))

    def save_context(self, context: MarketContext) -> None:
        self._redis.set(self._CONTEXT_KEY, context.model_dump_json())

    def get_context(self) -> MarketContext | None:
        value = self._redis.get(self._CONTEXT_KEY)
        return MarketContext.model_validate_json(value) if value else None


class InMemoryMarketStateStore:
    """Deterministic store used by unit tests and local calculations."""

    def __init__(self) -> None:
        self._candles: dict[str, dict[datetime, Candle]] = {}
        self._snapshots: dict[str, LiveSnapshot] = {}
        self._sectors: dict[str, str] = {}
        self._context: MarketContext | None = None
        self._lock = threading.RLock()

    def ping(self) -> bool:
        return True

    def save_candles(self, candles: Iterable[Candle]) -> int:
        candle_list = list(candles)
        with self._lock:
            for candle in candle_list:
                self._candles.setdefault(candle.instrument_key, {})[candle.timestamp] = candle
        return len(candle_list)

    def get_candles(self, instrument_key: str, limit: int = 500) -> list[Candle]:
        with self._lock:
            candles = sorted(self._candles.get(instrument_key, {}).values(), key=lambda item: item.timestamp)
        return candles[-limit:]

    def save_snapshot(self, snapshot: LiveSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.instrument_key] = snapshot

    def get_snapshots(self) -> list[LiveSnapshot]:
        with self._lock:
            return list(self._snapshots.values())

    def save_sector(self, instrument_key: str, sector: str) -> None:
        with self._lock:
            self._sectors[instrument_key] = sector

    def get_sectors(self) -> dict[str, str]:
        with self._lock:
            return dict(self._sectors)

    def save_context(self, context: MarketContext) -> None:
        with self._lock:
            self._context = context

    def get_context(self) -> MarketContext | None:
        with self._lock:
            return self._context
