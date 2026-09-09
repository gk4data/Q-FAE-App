"""Redis-backed transient market state with an in-memory test implementation."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Protocol

from redis import Redis

from app.models.market import (
    Candle,
    DailyRegimeSnapshot,
    LiveSnapshot,
    MarketContext,
    RelativeVolumeMetric,
    StockFeatureSnapshot,
)


class MarketStateStore(Protocol):
    def ping(self) -> bool: ...
    def save_candles(self, candles: Iterable[Candle]) -> int: ...
    def get_candles(self, instrument_key: str, limit: int = 500) -> list[Candle]: ...
    def has_candles(self, instrument_key: str) -> bool: ...
    def save_daily_candles(self, candles: Iterable[Candle]) -> int: ...
    def get_daily_candles(self, instrument_key: str, limit: int = 300) -> list[Candle]: ...
    def has_daily_candles(self, instrument_key: str) -> bool: ...
    def save_snapshot(self, snapshot: LiveSnapshot) -> None: ...
    def get_snapshots(self) -> list[LiveSnapshot]: ...
    def save_relative_volume(self, metric: RelativeVolumeMetric) -> None: ...
    def delete_relative_volume(self, instrument_key: str) -> None: ...
    def get_relative_volumes(self) -> dict[str, RelativeVolumeMetric]: ...
    def save_features(self, features: StockFeatureSnapshot) -> None: ...
    def delete_features(self, instrument_key: str) -> None: ...
    def get_features(self) -> dict[str, StockFeatureSnapshot]: ...
    def save_daily_regime(self, regime: DailyRegimeSnapshot) -> None: ...
    def get_daily_regimes(self) -> dict[str, DailyRegimeSnapshot]: ...
    def save_sector(self, instrument_key: str, sector: str) -> None: ...
    def get_sectors(self) -> dict[str, str]: ...
    def save_context(self, context: MarketContext) -> None: ...
    def get_context(self) -> MarketContext | None: ...


class RedisMarketStateStore:
    """Keep recent candles and current market state in Redis."""

    _SNAPSHOTS_KEY = "qfae:market:snapshots"
    _RELATIVE_VOLUME_KEY = "qfae:market:relative-volume"
    _FEATURES_KEY = "qfae:market:features"
    _DAILY_REGIMES_KEY = "qfae:market:daily-regimes"
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

    @staticmethod
    def _daily_candle_key(instrument_key: str) -> str:
        return f"qfae:market:candles:day:{instrument_key}"

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

    def has_candles(self, instrument_key: str) -> bool:
        return bool(self._redis.exists(self._candle_key(instrument_key)))

    def save_daily_candles(self, candles: Iterable[Candle]) -> int:
        candle_list = list(candles)
        if not candle_list:
            return 0
        retention_seconds = int(timedelta(days=900).total_seconds())
        grouped: dict[str, list[Candle]] = {}
        for candle in candle_list:
            grouped.setdefault(candle.instrument_key, []).append(candle)
        with self._redis.pipeline(transaction=False) as pipeline:
            for instrument_key, values in grouped.items():
                key = self._daily_candle_key(instrument_key)
                for candle in values:
                    score = candle.timestamp.timestamp()
                    pipeline.zremrangebyscore(key, score, score)
                    pipeline.zadd(key, {candle.model_dump_json(): score})
                pipeline.expire(key, retention_seconds)
            pipeline.execute()
        return len(candle_list)

    def get_daily_candles(self, instrument_key: str, limit: int = 300) -> list[Candle]:
        values = self._redis.zrange(self._daily_candle_key(instrument_key), -limit, -1)
        return [Candle.model_validate_json(value) for value in values]

    def has_daily_candles(self, instrument_key: str) -> bool:
        return bool(self._redis.exists(self._daily_candle_key(instrument_key)))

    def save_snapshot(self, snapshot: LiveSnapshot) -> None:
        self._redis.hset(self._SNAPSHOTS_KEY, snapshot.instrument_key, snapshot.model_dump_json())

    def get_snapshots(self) -> list[LiveSnapshot]:
        return [LiveSnapshot.model_validate_json(value) for value in self._redis.hvals(self._SNAPSHOTS_KEY)]

    def save_relative_volume(self, metric: RelativeVolumeMetric) -> None:
        self._redis.hset(
            self._RELATIVE_VOLUME_KEY,
            metric.instrument_key,
            metric.model_dump_json(),
        )

    def delete_relative_volume(self, instrument_key: str) -> None:
        self._redis.hdel(self._RELATIVE_VOLUME_KEY, instrument_key)

    def get_relative_volumes(self) -> dict[str, RelativeVolumeMetric]:
        return {
            instrument_key: RelativeVolumeMetric.model_validate_json(value)
            for instrument_key, value in self._redis.hgetall(self._RELATIVE_VOLUME_KEY).items()
        }

    def save_features(self, features: StockFeatureSnapshot) -> None:
        self._redis.hset(self._FEATURES_KEY, features.instrument_key, features.model_dump_json())

    def delete_features(self, instrument_key: str) -> None:
        self._redis.hdel(self._FEATURES_KEY, instrument_key)

    def get_features(self) -> dict[str, StockFeatureSnapshot]:
        return {
            instrument_key: StockFeatureSnapshot.model_validate_json(value)
            for instrument_key, value in self._redis.hgetall(self._FEATURES_KEY).items()
        }

    def save_daily_regime(self, regime: DailyRegimeSnapshot) -> None:
        self._redis.hset(self._DAILY_REGIMES_KEY, regime.instrument_key, regime.model_dump_json())

    def get_daily_regimes(self) -> dict[str, DailyRegimeSnapshot]:
        return {
            instrument_key: DailyRegimeSnapshot.model_validate_json(value)
            for instrument_key, value in self._redis.hgetall(self._DAILY_REGIMES_KEY).items()
        }

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
        self._relative_volumes: dict[str, RelativeVolumeMetric] = {}
        self._features: dict[str, StockFeatureSnapshot] = {}
        self._daily_candles: dict[str, dict[datetime, Candle]] = {}
        self._daily_regimes: dict[str, DailyRegimeSnapshot] = {}
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

    def has_candles(self, instrument_key: str) -> bool:
        with self._lock:
            return bool(self._candles.get(instrument_key))

    def save_daily_candles(self, candles: Iterable[Candle]) -> int:
        candle_list = list(candles)
        with self._lock:
            for candle in candle_list:
                self._daily_candles.setdefault(candle.instrument_key, {})[candle.timestamp] = candle
        return len(candle_list)

    def get_daily_candles(self, instrument_key: str, limit: int = 300) -> list[Candle]:
        with self._lock:
            candles = sorted(
                self._daily_candles.get(instrument_key, {}).values(),
                key=lambda item: item.timestamp,
            )
        return candles[-limit:]

    def has_daily_candles(self, instrument_key: str) -> bool:
        with self._lock:
            return bool(self._daily_candles.get(instrument_key))

    def save_snapshot(self, snapshot: LiveSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.instrument_key] = snapshot

    def get_snapshots(self) -> list[LiveSnapshot]:
        with self._lock:
            return list(self._snapshots.values())

    def save_relative_volume(self, metric: RelativeVolumeMetric) -> None:
        with self._lock:
            self._relative_volumes[metric.instrument_key] = metric

    def delete_relative_volume(self, instrument_key: str) -> None:
        with self._lock:
            self._relative_volumes.pop(instrument_key, None)

    def get_relative_volumes(self) -> dict[str, RelativeVolumeMetric]:
        with self._lock:
            return dict(self._relative_volumes)

    def save_features(self, features: StockFeatureSnapshot) -> None:
        with self._lock:
            self._features[features.instrument_key] = features

    def delete_features(self, instrument_key: str) -> None:
        with self._lock:
            self._features.pop(instrument_key, None)

    def get_features(self) -> dict[str, StockFeatureSnapshot]:
        with self._lock:
            return dict(self._features)

    def save_daily_regime(self, regime: DailyRegimeSnapshot) -> None:
        with self._lock:
            self._daily_regimes[regime.instrument_key] = regime

    def get_daily_regimes(self) -> dict[str, DailyRegimeSnapshot]:
        with self._lock:
            return dict(self._daily_regimes)

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
