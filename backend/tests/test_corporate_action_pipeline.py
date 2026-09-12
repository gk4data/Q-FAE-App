from datetime import UTC, date, datetime, timedelta

from app.models.market import Candle, CorporateAction
from app.services.corporate_action_assessment import assess_corporate_action
from app.services.corporate_action_pipeline import (
    adjust_candles,
    build_adjustment,
    build_calibration_report,
    evaluate_action_outcome,
)


def action(action_type: str, **values: object) -> CorporateAction:
    return CorporateAction(
        event_id=str(values.pop("event_id", action_type)),
        isin="INE000000001",
        instrument_key="NSE_EQ|INE000000001",
        symbol="TEST",
        action_type=action_type,
        announcement_date=date(2026, 7, 1),
        ex_date=date(2026, 7, 3),
        details={},
        raw_payload={},
        ingested_at=datetime(2026, 7, 1, tzinfo=UTC),
        **values,
    )


def candles(key: str, closes: list[float], start: date = date(2026, 7, 2)) -> list[Candle]:
    return [
        Candle(
            instrument_key=key,
            timestamp=datetime.combine(start + timedelta(days=index), datetime.min.time(), tzinfo=UTC),
            interval="day",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=100,
        )
        for index, close in enumerate(closes)
    ]


def test_adjustments_are_safe_and_do_not_replace_raw_values() -> None:
    bonus = build_adjustment(action("Bonus", ratio="1:1"))
    dividend = build_adjustment(action("Dividend", event_id="div", amount=5), reference_close=100)
    split = build_adjustment(action("Stock Split", event_id="split", ratio="10:2"))

    assert bonus.price_factor == 0.5
    assert dividend.price_factor == 0.95
    assert split.status == "unavailable"
    adjusted = adjust_candles(candles("NSE_EQ|INE000000001", [100]), [bonus])
    assert adjusted[0].raw_close == 100
    assert adjusted[0].adjusted_close == 50
    assert adjusted[0].adjusted_volume == 200


def test_outcomes_and_calibration_use_nifty_relative_returns() -> None:
    item = action("Dividend", amount=2)
    stock = candles(item.instrument_key, [100, 110, 121, 121, 121, 121, 121], date(2026, 7, 2))
    nifty = candles("NSE_INDEX|Nifty 50", [200, 210, 220, 220, 220, 220, 220], date(2026, 7, 2))
    outcome = evaluate_action_outcome(item, stock, nifty)

    assert outcome is not None
    assert outcome.return_1d_percent == 10
    assert outcome.abnormal_return_1d_percent == 5
    assessment = assess_corporate_action(item, reference_price=100)
    report = build_calibration_report([assessment], [outcome])
    one_day = next(bucket for bucket in report.buckets if bucket.horizon_sessions == 1)
    assert one_day.mean_abnormal_return_percent == 5
    assert one_day.readiness == "insufficient_sample"
