from datetime import UTC, date, datetime

from app.models.market import CorporateAction
from app.services.corporate_action_assessment import assess_corporate_action, classify_action_type


def action(action_type: str, *, amount: float | None = None, ratio: str | None = None, details: dict[str, str] | None = None) -> CorporateAction:
    return CorporateAction(
        event_id=f"event-{action_type}",
        isin="INE000000001",
        instrument_key="NSE_EQ|INE000000001",
        symbol="TEST",
        action_type=action_type,
        announcement_date=date(2026, 8, 1),
        ex_date=date(2026, 8, 15),
        amount=amount,
        ratio=ratio,
        details=details or {},
        raw_payload={},
        ingested_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_dividend_yield_drives_materiality_but_keeps_missing_context_visible() -> None:
    result = assess_corporate_action(
        action("Final Dividend", amount=3),
        reference_price=100,
        reference_price_date=date(2026, 7, 31),
    )

    assert result.category == "dividend"
    assert result.direction == "positive"
    assert result.derived_metrics["dividend_yield_percent"] == 3
    assert result.materiality_score == 60
    assert result.sentiment_score == 24
    assert "cash_flow_support_unchecked" in result.cautions


def test_bonus_and_split_are_not_mislabeled_as_value_creation() -> None:
    bonus = assess_corporate_action(action("Bonus", ratio="1:1"), reference_price=100)
    split = assess_corporate_action(action("Stock Split", ratio="10:2"), reference_price=100)

    assert bonus.direction == "neutral"
    assert bonus.sentiment_score == 0
    assert bonus.derived_metrics["bonus_shares_per_existing_share"] == 1
    assert split.direction == "neutral"
    assert split.derived_metrics["ratio_magnitude"] == 5


def test_rights_issue_estimates_dilution_and_discount_transparently() -> None:
    result = assess_corporate_action(
        action("Rights Issue", ratio="1:4", details={"Issue price": "Rs 80 per share"}),
        reference_price=100,
    )

    assert result.category == "rights"
    assert result.derived_metrics["new_shares_per_100_existing"] == 25
    assert result.derived_metrics["issue_discount_percent"] == 20
    assert result.direction == "negative"
    assert result.sentiment_score == -15
    assert result.requires_ai_review is True


def test_buyback_premium_is_measured_against_pre_event_close() -> None:
    result = assess_corporate_action(
        action("Buy Back", details={"Buyback price": "Rs. 120"}),
        reference_price=100,
    )

    assert classify_action_type("Buy Back of shares") == "buyback"
    assert result.derived_metrics["offer_premium_percent"] == 20
    assert result.direction == "positive"
    assert result.materiality_score == 50
