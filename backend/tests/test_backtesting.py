from datetime import datetime, timedelta, timezone

import pytest

from app.models.backtest import BacktestRunRequest
from app.models.market import Candle, EvidenceOutcomeObservation
from app.services.backtesting import OpportunityBacktester

IST = timezone(timedelta(hours=5, minutes=30))


def observation(
    timestamp: datetime,
    *,
    score: float = 75,
    eligible: bool = True,
    signal_state: str = "confirmed",
) -> EvidenceOutcomeObservation:
    return EvidenceOutcomeObservation(
        instrument_key="NSE_EQ|TEST",
        symbol="TEST",
        sector="Technology",
        candle_timestamp=timestamp,
        observed_at=timestamp + timedelta(seconds=2),
        reference_price=99,
        confluence="supportive",
        signal_state=signal_state,
        data_quality="complete",
        evidence_payload={
            "opportunity_score": {
                "final_score": score,
                "eligible": eligible,
                "status": "high_priority",
                "model_version": "pilot-v1",
                "top_positive_factors": ["above_vwap"],
                "top_cautions": [],
            }
        },
        market_regime_payload={"state": "risk_on"},
    )


def candle(timestamp: datetime, open_price: float, close: float, low=None, high=None) -> Candle:
    return Candle(
        instrument_key="NSE_EQ|TEST",
        timestamp=timestamp,
        open=open_price,
        high=high if high is not None else max(open_price, close),
        low=low if low is not None else min(open_price, close),
        close=close,
        volume=1_000,
    )


class Source:
    def __init__(self, observations, candles):
        self.observations = observations
        self.candles = candles

    def get_backtest_observations(
        self, _from_date, _to_date, _min_score, _signal_states, _require_eligible
    ):
        sessions = {item.candle_timestamp.date() for item in self.observations}
        return len(self.observations), len(sessions), self.observations

    def get_session_candles_many(self, instrument_keys, _session_date):
        return {instrument_key: self.candles for instrument_key in instrument_keys}

    def get_session_evidence_many(self, instrument_keys, _session_date):
        return {instrument_key: self.observations for instrument_key in instrument_keys}


def test_fixed_holding_uses_next_candle_open_and_includes_costs() -> None:
    signal_time = datetime(2026, 9, 21, 9, 15, tzinfo=IST)
    candles = [
        candle(signal_time, 98, 99),
        candle(signal_time + timedelta(minutes=1), 100, 101),
        candle(signal_time + timedelta(minutes=6), 104, 105),
    ]
    config = BacktestRunRequest(
        from_date=signal_time.date(),
        to_date=signal_time.date(),
        holding_minutes=5,
        exit_policy="fixed_minutes",
        slippage_bps_per_side=5,
        fees_bps_per_side=10,
    )

    result = OpportunityBacktester(Source([observation(signal_time)], candles)).run(config)

    assert result.summary.trades == 1
    trade = result.trades[0]
    assert trade.entry_timestamp == signal_time + timedelta(minutes=1)
    assert trade.entry_price == pytest.approx(100.05)
    assert trade.gross_return_percent == 5
    assert trade.net_return_percent < trade.gross_return_percent
    assert trade.exit_reason == "fixed_5m"
    assert result.summary.net_profit_inr == trade.pnl_inr
    assert result.model_versions == ["pilot-v1"]


def test_bracket_exit_resolves_same_candle_against_long_position() -> None:
    signal_time = datetime(2026, 9, 21, 10, 0, tzinfo=IST)
    candles = [
        candle(signal_time + timedelta(minutes=1), 100, 100, low=98, high=103),
        candle(signal_time + timedelta(minutes=2), 100, 101),
    ]
    config = BacktestRunRequest(
        from_date=signal_time.date(),
        to_date=signal_time.date(),
        exit_policy="bracket",
        stop_loss_percent=1,
        take_profit_percent=2,
        slippage_bps_per_side=0,
        fees_bps_per_side=0,
    )

    result = OpportunityBacktester(Source([observation(signal_time)], candles)).run(config)

    assert result.trades[0].exit_reason == "stop_loss_conservative"
    assert result.trades[0].gross_return_percent == -1


def test_ineligible_and_low_score_observations_are_not_traded() -> None:
    signal_time = datetime(2026, 9, 21, 11, 0, tzinfo=IST)
    rows = [
        observation(signal_time, score=69),
        observation(signal_time + timedelta(minutes=1), score=80, eligible=False),
        observation(signal_time + timedelta(minutes=2), score=80, signal_state="building"),
    ]
    config = BacktestRunRequest(from_date=signal_time.date(), to_date=signal_time.date())

    result = OpportunityBacktester(Source(rows, [])).run(config)

    assert result.summary.observations == 3
    assert result.summary.qualifying_signals == 0
    assert result.summary.trades == 0


def test_model_exit_uses_confirmed_deterioration_and_next_candle_open() -> None:
    signal_time = datetime(2026, 9, 21, 9, 15, tzinfo=IST)
    rows = [
        observation(signal_time, score=75),
        observation(signal_time + timedelta(minutes=1), score=50, signal_state="weakening"),
        observation(signal_time + timedelta(minutes=2), score=48, signal_state="weakening"),
    ]
    candles = [
        candle(signal_time + timedelta(minutes=1), 100, 100.5, low=99.5),
        candle(signal_time + timedelta(minutes=2), 101, 101.5, low=100.5),
        candle(signal_time + timedelta(minutes=3), 102, 101.8, low=101.5),
    ]
    config = BacktestRunRequest(
        from_date=signal_time.date(),
        to_date=signal_time.date(),
        exit_policy="model",
        model_exit_score=55,
        model_exit_confirmation_minutes=2,
        model_minimum_hold_minutes=0,
        stop_loss_percent=5,
        slippage_bps_per_side=0,
        fees_bps_per_side=0,
    )

    result = OpportunityBacktester(Source(rows, candles)).run(config)

    trade = result.trades[0]
    assert trade.exit_timestamp == signal_time + timedelta(minutes=3)
    assert trade.exit_price == 102
    assert trade.exit_reason == "model_signal_deteriorated"
    assert trade.exit_opportunity_score == 48
    assert trade.exit_signal_state == "weakening"


def test_model_exit_hard_stop_overrides_later_evidence_exit() -> None:
    signal_time = datetime(2026, 9, 21, 10, 0, tzinfo=IST)
    rows = [
        observation(signal_time, score=75),
        observation(signal_time + timedelta(minutes=1), score=45, signal_state="failed"),
    ]
    candles = [
        candle(signal_time + timedelta(minutes=1), 100, 99, low=98.5),
        candle(signal_time + timedelta(minutes=2), 99, 99.5),
    ]
    config = BacktestRunRequest(
        from_date=signal_time.date(),
        to_date=signal_time.date(),
        exit_policy="model",
        model_minimum_hold_minutes=0,
        stop_loss_percent=1,
        slippage_bps_per_side=0,
        fees_bps_per_side=0,
    )

    result = OpportunityBacktester(Source(rows, candles)).run(config)

    assert result.trades[0].exit_reason == "hard_stop_loss"
    assert result.trades[0].exit_price == 99


def test_invalid_period_is_rejected() -> None:
    with pytest.raises(ValueError):
        BacktestRunRequest(
            from_date=datetime(2026, 9, 22).date(),
            to_date=datetime(2026, 9, 21).date(),
        )
