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
    CorporateActionContext,
    DailyRegimeSnapshot,
    LiveSnapshot,
    MarketContext,
    MarketRegimeSnapshot,
    OpportunityEvidenceSnapshot,
    RelativeVolumeMetric,
    RiskAssessment,
    SignalPersistenceSnapshot,
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
    def get_context_history(self, limit: int = 5) -> list[MarketContext]: ...
    def save_market_regime(self, regime: MarketRegimeSnapshot) -> None: ...
    def get_market_regime(self) -> MarketRegimeSnapshot | None: ...
    def save_evidence(self, evidence: OpportunityEvidenceSnapshot) -> None: ...
    def get_evidence_history(self, instrument_key: str, limit: int = 3) -> list[OpportunityEvidenceSnapshot]: ...
    def save_signal(self, signal: SignalPersistenceSnapshot) -> None: ...
    def get_signals(self) -> dict[str, SignalPersistenceSnapshot]: ...
    def save_risk_assessment(self, risk: RiskAssessment) -> None: ...
    def get_risk_assessments(self) -> dict[str, RiskAssessment]: ...
    def save_corporate_action_context(self, context: CorporateActionContext) -> None: ...
    def get_corporate_action_contexts(self) -> dict[str, CorporateActionContext]: ...


class RedisMarketStateStore:
    """Keep recent candles and current market state in Redis."""

    _SNAPSHOTS_KEY = "qfae:market:snapshots"
    _RELATIVE_VOLUME_KEY = "qfae:market:relative-volume"
    _FEATURES_KEY = "qfae:market:features"
    _DAILY_REGIMES_KEY = "qfae:market:daily-regimes"
    _SECTORS_KEY = "qfae:market:sectors"
    _CONTEXT_KEY = "qfae:market:context"
    _CONTEXT_HISTORY_KEY = "qfae:market:context-history"
    _MARKET_REGIME_KEY = "qfae:market:regime"
    _SIGNALS_KEY = "qfae:market:signals"
    _RISK_KEY = "qfae:market:risk"
    _CORPORATE_ACTION_CONTEXT_KEY = "qfae:market:corporate-action-context"

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

    @staticmethod
    def _evidence_key(instrument_key: str) -> str:
        return f"qfae:market:evidence:{instrument_key}"

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
        value = context.model_dump_json()
        score = context.as_of.timestamp()
        with self._redis.pipeline(transaction=False) as pipeline:
            pipeline.set(self._CONTEXT_KEY, value)
            pipeline.zremrangebyscore(self._CONTEXT_HISTORY_KEY, score, score)
            pipeline.zadd(self._CONTEXT_HISTORY_KEY, {value: score})
            pipeline.zremrangebyscore(self._CONTEXT_HISTORY_KEY, "-inf", score - 172800)
            pipeline.expire(self._CONTEXT_HISTORY_KEY, int(timedelta(days=2).total_seconds()))
            pipeline.execute()

    def get_context(self) -> MarketContext | None:
        value = self._redis.get(self._CONTEXT_KEY)
        return MarketContext.model_validate_json(value) if value else None

    def get_context_history(self, limit: int = 5) -> list[MarketContext]:
        values = self._redis.zrange(self._CONTEXT_HISTORY_KEY, -limit, -1)
        return [MarketContext.model_validate_json(value) for value in values]

    def save_market_regime(self, regime: MarketRegimeSnapshot) -> None:
        self._redis.set(self._MARKET_REGIME_KEY, regime.model_dump_json())

    def get_market_regime(self) -> MarketRegimeSnapshot | None:
        value = self._redis.get(self._MARKET_REGIME_KEY)
        return MarketRegimeSnapshot.model_validate_json(value) if value else None

    def save_evidence(self, evidence: OpportunityEvidenceSnapshot) -> None:
        key = self._evidence_key(evidence.instrument_key)
        score = evidence.as_of.timestamp()
        with self._redis.pipeline(transaction=False) as pipeline:
            pipeline.zremrangebyscore(key, score, score)
            pipeline.zadd(key, {evidence.model_dump_json(): score})
            pipeline.zremrangebyscore(key, "-inf", score - 432000)
            pipeline.expire(key, int(timedelta(days=5).total_seconds()))
            pipeline.execute()

    def get_evidence_history(self, instrument_key: str, limit: int = 3) -> list[OpportunityEvidenceSnapshot]:
        values = self._redis.zrange(self._evidence_key(instrument_key), -limit, -1)
        return [OpportunityEvidenceSnapshot.model_validate_json(value) for value in values]

    def save_signal(self, signal: SignalPersistenceSnapshot) -> None:
        self._redis.hset(self._SIGNALS_KEY, signal.instrument_key, signal.model_dump_json())

    def get_signals(self) -> dict[str, SignalPersistenceSnapshot]:
        return {key: SignalPersistenceSnapshot.model_validate_json(value) for key, value in self._redis.hgetall(self._SIGNALS_KEY).items()}

    def save_risk_assessment(self, risk: RiskAssessment) -> None:
        self._redis.hset(self._RISK_KEY, risk.instrument_key, risk.model_dump_json())

    def get_risk_assessments(self) -> dict[str, RiskAssessment]:
        return {key: RiskAssessment.model_validate_json(value) for key, value in self._redis.hgetall(self._RISK_KEY).items()}

    def save_corporate_action_context(self, context: CorporateActionContext) -> None:
        self._redis.hset(
            self._CORPORATE_ACTION_CONTEXT_KEY,
            context.instrument_key,
            context.model_dump_json(),
        )

    def get_corporate_action_contexts(self) -> dict[str, CorporateActionContext]:
        return {
            key: CorporateActionContext.model_validate_json(value)
            for key, value in self._redis.hgetall(self._CORPORATE_ACTION_CONTEXT_KEY).items()
        }


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
        self._context_history: list[MarketContext] = []
        self._market_regime: MarketRegimeSnapshot | None = None
        self._evidence: dict[str, list[OpportunityEvidenceSnapshot]] = {}
        self._signals: dict[str, SignalPersistenceSnapshot] = {}
        self._risk: dict[str, RiskAssessment] = {}
        self._corporate_action_contexts: dict[str, CorporateActionContext] = {}
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
            self._context_history = [item for item in self._context_history if item.as_of != context.as_of]
            self._context_history.append(context)
            self._context_history = self._context_history[-1440:]

    def get_context(self) -> MarketContext | None:
        with self._lock:
            return self._context

    def get_context_history(self, limit: int = 5) -> list[MarketContext]:
        with self._lock:
            return list(self._context_history[-limit:])

    def save_market_regime(self, regime: MarketRegimeSnapshot) -> None:
        with self._lock:
            self._market_regime = regime

    def get_market_regime(self) -> MarketRegimeSnapshot | None:
        with self._lock:
            return self._market_regime

    def save_evidence(self, evidence: OpportunityEvidenceSnapshot) -> None:
        with self._lock:
            rows = [item for item in self._evidence.get(evidence.instrument_key, []) if item.as_of != evidence.as_of]
            rows.append(evidence)
            self._evidence[evidence.instrument_key] = rows[-1500:]

    def get_evidence_history(self, instrument_key: str, limit: int = 3) -> list[OpportunityEvidenceSnapshot]:
        with self._lock:
            return list(self._evidence.get(instrument_key, [])[-limit:])

    def save_signal(self, signal: SignalPersistenceSnapshot) -> None:
        with self._lock:
            self._signals[signal.instrument_key] = signal

    def get_signals(self) -> dict[str, SignalPersistenceSnapshot]:
        with self._lock:
            return dict(self._signals)

    def save_risk_assessment(self, risk: RiskAssessment) -> None:
        with self._lock:
            self._risk[risk.instrument_key] = risk

    def get_risk_assessments(self) -> dict[str, RiskAssessment]:
        with self._lock:
            return dict(self._risk)

    def save_corporate_action_context(self, context: CorporateActionContext) -> None:
        with self._lock:
            self._corporate_action_contexts[context.instrument_key] = context

    def get_corporate_action_contexts(self) -> dict[str, CorporateActionContext]:
        with self._lock:
            return dict(self._corporate_action_contexts)
