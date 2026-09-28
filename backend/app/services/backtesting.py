"""Point-in-time simulation of recorded Q-FAE opportunity recommendations."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app.models.backtest import (
    BacktestBreakdown,
    BacktestRun,
    BacktestRunRequest,
    BacktestSummary,
    BacktestTrade,
)
from app.models.market import Candle, EvidenceOutcomeObservation
from app.services.market_context import INDIA_TIMEZONE


class BacktestDataSource(Protocol):
    def get_backtest_observations(
        self,
        from_date: date,
        to_date: date,
        min_score: float,
        signal_states: list[str],
        require_eligible: bool,
    ) -> tuple[int, int, list[EvidenceOutcomeObservation]]: ...

    def get_session_candles_many(
        self, instrument_keys: list[str], session_date: date
    ) -> dict[str, list[Candle]]: ...

    def get_session_evidence_many(
        self, instrument_keys: list[str], session_date: date
    ) -> dict[str, list[EvidenceOutcomeObservation]]: ...


def _score_payload(observation: EvidenceOutcomeObservation) -> dict[str, object] | None:
    payload = observation.evidence_payload.get("opportunity_score")
    return payload if isinstance(payload, dict) else None


def _regime(observation: EvidenceOutcomeObservation) -> str | None:
    payload = observation.market_regime_payload
    value = payload.get("state") if isinstance(payload, dict) else None
    return str(value) if value else None


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


def _return_percent(entry: float, exit_price: float) -> float:
    return (exit_price / entry - 1) * 100


class OpportunityBacktester:
    """Execute recorded recommendations using only later candles."""

    def __init__(self, source: BacktestDataSource) -> None:
        self.source = source

    def run(self, config: BacktestRunRequest) -> BacktestRun:
        created_at = datetime.now(INDIA_TIMEZONE)
        observation_count, recorded_sessions, candidates = self.source.get_backtest_observations(
            config.from_date,
            config.to_date,
            config.min_score,
            config.required_signal_states,
            config.require_eligible,
        )
        qualifying = [item for item in candidates if self._qualifies(item, config)]
        grouped: dict[tuple[date, datetime], list[EvidenceOutcomeObservation]] = defaultdict(list)
        for item in qualifying:
            session_date = item.candle_timestamp.astimezone(INDIA_TIMEZONE).date()
            grouped[(session_date, item.candle_timestamp)].append(item)

        trades: list[BacktestTrade] = []
        traded_by_day: dict[date, set[str]] = defaultdict(set)
        daily_trade_counts: dict[date, int] = defaultdict(int)
        skipped_missing_candles = 0
        current_session: date | None = None
        session_candles: dict[str, list[Candle]] = {}
        session_evidence: dict[str, list[EvidenceOutcomeObservation]] = {}
        instruments_by_session: dict[date, set[str]] = defaultdict(set)
        for (session_date, _), rows in grouped.items():
            instruments_by_session[session_date].update(item.instrument_key for item in rows)

        for (session_date, _), rows in sorted(grouped.items(), key=lambda item: item[0]):
            if session_date != current_session:
                current_session = session_date
                session_candles = self.source.get_session_candles_many(
                    sorted(instruments_by_session[session_date]), session_date
                )
                session_evidence = (
                    self.source.get_session_evidence_many(
                        sorted(instruments_by_session[session_date]), session_date
                    )
                    if config.exit_policy == "model"
                    else {}
                )
            ranked = sorted(rows, key=self._score, reverse=True)[
                : config.max_candidates_per_minute
            ]
            for observation in ranked:
                if daily_trade_counts[session_date] >= config.max_trades_per_day:
                    break
                if (
                    config.one_trade_per_stock_per_day
                    and observation.instrument_key in traded_by_day[session_date]
                ):
                    continue
                trade = self._simulate_trade(
                    observation,
                    session_candles.get(observation.instrument_key, []),
                    session_evidence.get(observation.instrument_key, []),
                    config,
                )
                if trade is None:
                    skipped_missing_candles += 1
                    continue
                open_positions = sum(
                    prior.entry_timestamp <= trade.entry_timestamp < prior.exit_timestamp
                    for prior in trades
                )
                if open_positions >= config.max_concurrent_positions:
                    continue
                trades.append(trade)
                traded_by_day[session_date].add(observation.instrument_key)
                daily_trade_counts[session_date] += 1

        trades.sort(key=lambda item: (item.entry_timestamp, item.symbol))
        completed_at = datetime.now(INDIA_TIMEZONE)
        versions = sorted(
            {item.model_version for item in trades if item.model_version is not None}
        )
        return BacktestRun(
            run_id=uuid4().hex,
            status="completed",
            created_at=created_at,
            completed_at=completed_at,
            config=config,
            summary=self._summary(
                observations=observation_count,
                recorded_sessions=recorded_sessions,
                qualifying_signals=len(qualifying),
                skipped_missing_candles=skipped_missing_candles,
                trades=trades,
                config=config,
            ),
            breakdowns=self._breakdowns(trades),
            model_versions=versions,
            trades=trades,
            limitations=[
                "Only evidence recorded point-in-time by Q-FAE is included.",
                "Historical spread and order-book depth are represented by configured costs.",
                "A candle touching stop and target is resolved against the position conservatively.",
                "Model exits use only evidence recorded by the completed minute and execute at the next candle open.",
                "This is research output, not a forecast or trading recommendation.",
            ],
        )

    @staticmethod
    def _score(observation: EvidenceOutcomeObservation) -> float:
        payload = _score_payload(observation)
        try:
            return float(payload.get("final_score", 0)) if payload else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _qualifies(
        self, observation: EvidenceOutcomeObservation, config: BacktestRunRequest
    ) -> bool:
        score = _score_payload(observation)
        if score is None or self._score(observation) < config.min_score:
            return False
        if observation.signal_state not in config.required_signal_states:
            return False
        return not config.require_eligible or score.get("eligible") is True

    def _simulate_trade(
        self,
        observation: EvidenceOutcomeObservation,
        candles: list[Candle],
        evidence_path: list[EvidenceOutcomeObservation],
        config: BacktestRunRequest,
    ) -> BacktestTrade | None:
        future = sorted(
            (
                candle
                for candle in candles
                if candle.timestamp > observation.candle_timestamp
            ),
            key=lambda item: item.timestamp,
        )
        if not future:
            return None
        entry_candle = future[0]
        raw_entry = entry_candle.open
        exit_candle, raw_exit, exit_reason, exit_evidence = self._select_exit(
            raw_entry, entry_candle, future, evidence_path, config
        )
        if exit_candle is None or raw_exit is None:
            return None

        slippage = config.slippage_bps_per_side / 10_000
        entry_price = raw_entry * (1 + slippage)
        exit_price = raw_exit * (1 - slippage)
        gross_return = _return_percent(raw_entry, raw_exit)
        execution_return = _return_percent(entry_price, exit_price)
        fee_percent = config.fees_bps_per_side * 2 / 100
        net_return = execution_return - fee_percent
        cost_percent = max(0.0, gross_return - net_return)
        path = [item for item in future if item.timestamp <= exit_candle.timestamp]
        mfe = _return_percent(raw_entry, max(item.high for item in path)) if path else None
        mae = _return_percent(raw_entry, min(item.low for item in path)) if path else None
        score = _score_payload(observation) or {}
        return BacktestTrade(
            trade_id=uuid4().hex,
            instrument_key=observation.instrument_key,
            symbol=observation.symbol,
            sector=observation.sector,
            signal_timestamp=observation.candle_timestamp,
            entry_timestamp=entry_candle.timestamp,
            exit_timestamp=exit_candle.timestamp,
            opportunity_score=_round(self._score(observation)),
            score_status=str(score.get("status") or "unknown"),
            signal_state=observation.signal_state,
            market_regime=_regime(observation),
            model_version=str(score.get("model_version")) if score.get("model_version") else None,
            entry_price=_round(entry_price, 6),
            exit_price=_round(exit_price, 6),
            gross_return_percent=_round(gross_return),
            net_return_percent=_round(net_return),
            cost_percent=_round(cost_percent),
            pnl_inr=_round(config.position_size_inr * net_return / 100, 2),
            holding_minutes=max(
                0, int((exit_candle.timestamp - entry_candle.timestamp).total_seconds() // 60)
            ),
            exit_reason=exit_reason,
            exit_opportunity_score=(
                _round(self._score(exit_evidence)) if exit_evidence is not None else None
            ),
            exit_signal_state=(exit_evidence.signal_state if exit_evidence is not None else None),
            mfe_percent=_round(mfe) if mfe is not None else None,
            mae_percent=_round(mae) if mae is not None else None,
            top_positive_factors=[str(item) for item in score.get("top_positive_factors", [])][:8],
            top_cautions=[str(item) for item in score.get("top_cautions", [])][:8],
        )

    @staticmethod
    def _select_exit(
        entry: float,
        entry_candle: Candle,
        future: list[Candle],
        evidence_path: list[EvidenceOutcomeObservation],
        config: BacktestRunRequest,
    ) -> tuple[Candle | None, float | None, str, EvidenceOutcomeObservation | None]:
        if config.exit_policy == "end_of_day":
            return future[-1], future[-1].close, "end_of_day", None
        if config.exit_policy == "fixed_minutes":
            target_time = entry_candle.timestamp + timedelta(minutes=config.holding_minutes)
            match = next((item for item in future if item.timestamp >= target_time), None)
            if match is not None:
                return match, match.close, f"fixed_{config.holding_minutes}m", None
            return future[-1], future[-1].close, "session_close_fallback", None

        if config.exit_policy == "model":
            return OpportunityBacktester._select_model_exit(
                entry, entry_candle, future, evidence_path, config
            )

        stop_price = entry * (1 - config.stop_loss_percent / 100)
        target_price = entry * (1 + config.take_profit_percent / 100)
        for candle in future:
            stop_hit = candle.low <= stop_price
            target_hit = candle.high >= target_price
            if stop_hit:
                reason = "stop_loss_conservative" if target_hit else "stop_loss"
                return candle, stop_price, reason, None
            if target_hit:
                return candle, target_price, "take_profit", None
        return future[-1], future[-1].close, "end_of_day", None

    @staticmethod
    def _select_model_exit(
        entry: float,
        entry_candle: Candle,
        future: list[Candle],
        evidence_path: list[EvidenceOutcomeObservation],
        config: BacktestRunRequest,
    ) -> tuple[Candle | None, float | None, str, EvidenceOutcomeObservation | None]:
        """Apply hard risk first, then act on confirmed point-in-time model deterioration."""
        minimum_exit_time = entry_candle.timestamp + timedelta(
            minutes=config.model_minimum_hold_minutes
        )
        deteriorating = 0
        model_exit: tuple[Candle, EvidenceOutcomeObservation, str] | None = None
        for evidence in sorted(evidence_path, key=lambda item: item.candle_timestamp):
            if evidence.candle_timestamp < entry_candle.timestamp:
                continue
            score = _score_payload(evidence) or {}
            score_value = OpportunityBacktester._score(evidence)
            failed = evidence.signal_state == "failed"
            weakening = evidence.signal_state == "weakening"
            ineligible = score.get("eligible") is False
            below_exit_score = score_value < config.model_exit_score
            deterioration_reason = (
                "model_signal_failed" if failed else
                "model_became_ineligible" if ineligible else
                "model_signal_deteriorated" if weakening else
                "model_score_deteriorated" if below_exit_score else
                None
            )
            deteriorating = deteriorating + 1 if deterioration_reason else 0
            if evidence.candle_timestamp < minimum_exit_time:
                continue
            if failed or deteriorating >= config.model_exit_confirmation_minutes:
                execution_candle = next(
                    (item for item in future if item.timestamp > evidence.candle_timestamp),
                    None,
                )
                if execution_candle is not None:
                    model_exit = (execution_candle, evidence, deterioration_reason or "model_exit")
                break

        stop_price = entry * (1 - config.stop_loss_percent / 100)
        model_exit_candle = model_exit[0] if model_exit is not None else None
        for candle in future:
            if model_exit_candle is not None and candle.timestamp >= model_exit_candle.timestamp:
                break
            if candle.low <= stop_price:
                return candle, min(candle.open, stop_price), "hard_stop_loss", None

        if model_exit is not None:
            candle, evidence, reason = model_exit
            return candle, candle.open, reason, evidence

        for candle in future:
            if candle.low <= stop_price:
                return candle, min(candle.open, stop_price), "hard_stop_loss", None
        return future[-1], future[-1].close, "end_of_day", None

    @staticmethod
    def _summary(
        *,
        observations: int,
        recorded_sessions: int,
        qualifying_signals: int,
        skipped_missing_candles: int,
        trades: list[BacktestTrade],
        config: BacktestRunRequest,
    ) -> BacktestSummary:
        returns = [item.net_return_percent for item in trades]
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value < 0]
        gross_profit = sum(item.pnl_inr for item in trades if item.pnl_inr > 0)
        gross_loss = abs(sum(item.pnl_inr for item in trades if item.pnl_inr < 0))
        net_profit = sum(item.pnl_inr for item in trades)
        gross_pnl = sum(
            config.position_size_inr * item.gross_return_percent / 100 for item in trades
        )
        equity = config.initial_capital_inr
        peak = equity
        max_drawdown = 0.0
        daily_pnl: dict[date, float] = defaultdict(float)
        for trade in sorted(trades, key=lambda item: item.exit_timestamp):
            equity += trade.pnl_inr
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
            daily_pnl[trade.exit_timestamp.astimezone(INDIA_TIMEZONE).date()] += trade.pnl_inr
        daily_returns = [value / config.initial_capital_inr * 100 for value in daily_pnl.values()]
        sharpe = None
        if len(daily_returns) >= 2 and statistics.stdev(daily_returns) > 0:
            sharpe = statistics.mean(daily_returns) / statistics.stdev(daily_returns) * math.sqrt(252)
        return BacktestSummary(
            observations=observations,
            recorded_sessions=recorded_sessions,
            traded_sessions=len(
                {item.entry_timestamp.astimezone(INDIA_TIMEZONE).date() for item in trades}
            ),
            qualifying_signals=qualifying_signals,
            skipped_missing_candles=skipped_missing_candles,
            trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate_percent=_round(len(wins) / len(trades) * 100) if trades else None,
            average_win_percent=_round(statistics.mean(wins)) if wins else None,
            average_loss_percent=_round(statistics.mean(losses)) if losses else None,
            average_net_return_percent=_round(statistics.mean(returns)) if returns else None,
            expectancy_percent=_round(statistics.mean(returns)) if returns else None,
            gross_return_percent=_round(gross_pnl / config.initial_capital_inr * 100),
            net_return_percent=_round(net_profit / config.initial_capital_inr * 100),
            net_profit_inr=_round(net_profit, 2),
            profit_factor=_round(gross_profit / gross_loss) if gross_loss else None,
            maximum_drawdown_percent=_round(max_drawdown),
            sharpe_like=_round(sharpe) if sharpe is not None else None,
        )

    @staticmethod
    def _breakdowns(trades: list[BacktestTrade]) -> list[BacktestBreakdown]:
        groups: dict[tuple[str, str], list[BacktestTrade]] = defaultdict(list)
        for trade in trades:
            score_bucket = (
                "80+" if trade.opportunity_score >= 80 else
                "70-79.99" if trade.opportunity_score >= 70 else
                "60-69.99" if trade.opportunity_score >= 60 else "below_60"
            )
            groups[("score", score_bucket)].append(trade)
            groups[("market_regime", trade.market_regime or "unavailable")].append(trade)
            groups[("sector", trade.sector or "unavailable")].append(trade)
            groups[("exit_reason", trade.exit_reason)].append(trade)
        result: list[BacktestBreakdown] = []
        for (dimension, bucket), rows in sorted(groups.items()):
            returns = [item.net_return_percent for item in rows]
            result.append(
                BacktestBreakdown(
                    dimension=dimension,
                    bucket=bucket,
                    trades=len(rows),
                    win_rate_percent=_round(
                        sum(value > 0 for value in returns) / len(rows) * 100
                    ),
                    average_net_return_percent=_round(statistics.mean(returns)),
                    total_pnl_inr=_round(sum(item.pnl_inr for item in rows), 2),
                )
            )
        return result
