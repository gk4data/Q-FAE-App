from datetime import UTC, date, datetime, timedelta

from app.services.financial_results import (
    build_financial_snapshot,
    latest_completed_quarter,
    period_is_latest_completed_quarter,
    snapshot_is_reusable,
)
from app.services.upstox_market import UpstoxMarketDataClient


def income(period: str, revenue: float = 100) -> dict[str, object]:
    return {
        "income_statement": [
            {"category": "revenue", "history": [{"period": period, "value": revenue}]},
            {"category": "operating_profit", "history": [{"period": period, "value": 20}]},
            {"category": "net_profit", "history": [{"period": period, "value": 12}]},
        ]
    }


def snapshot(captured_at: datetime, quarterly_period: str = "Jun 2026"):
    return build_financial_snapshot(
        isin="INE1",
        instrument_key="NSE_EQ|INE1",
        symbol="TEST",
        quarterly_income=income(quarterly_period),
        annual_income=income("Mar 2026", 400),
        annual_cash_flow={"cash_flow": [{"category": "operating", "history": [{"period": "Mar 2026", "value": 50}]}]},
        annual_balance_sheet={"history": [{"period": "Mar 2026", "total_asset": 500, "total_liability": 200}]},
        captured_at=captured_at,
    )


def test_latest_completed_quarter_and_period_matching() -> None:
    assert latest_completed_quarter(date(2026, 1, 10)) == (12, 2025)
    assert latest_completed_quarter(date(2026, 4, 1)) == (3, 2026)
    assert latest_completed_quarter(date(2026, 9, 13)) == (6, 2026)
    assert period_is_latest_completed_quarter("Jun 2026", date(2026, 9, 13)) is True
    assert period_is_latest_completed_quarter("Mar 2026", date(2026, 9, 13)) is False


def test_recent_latest_quarter_is_reused_but_stale_or_older_period_is_not() -> None:
    now = datetime(2026, 9, 13, tzinfo=UTC)
    current, _ = snapshot(now - timedelta(days=10))
    stale, _ = snapshot(now - timedelta(days=31))
    older_period, _ = snapshot(now - timedelta(days=2), "Mar 2026")

    assert snapshot_is_reusable(current, now=now, cache_days=30) is True
    assert snapshot_is_reusable(stale, now=now, cache_days=30) is False
    assert snapshot_is_reusable(older_period, now=now, cache_days=30) is False


def test_snapshot_is_content_versioned_and_builds_quarterly_context() -> None:
    first, context = snapshot(datetime(2026, 9, 1, tzinfo=UTC))
    second, _ = snapshot(datetime(2026, 9, 2, tzinfo=UTC))

    assert first.snapshot_id == second.snapshot_id
    assert first.quarterly_available is True
    assert first.annual_available is True
    assert first.quarterly_period == "Jun 2026"
    assert first.annual_period == "Mar 2026"
    assert context.latest_revenue_crore == 100
    assert context.latest_operating_cash_flow_crore == 50


def test_upstox_financial_fetch_collects_quarterly_and_full_annual_datasets() -> None:
    paths: list[str] = []
    client = object.__new__(UpstoxMarketDataClient)

    def fake_get(path: str) -> dict[str, object]:
        paths.append(path)
        if "time_period=quarterly" in path:
            data = income("Jun 2026")
        elif "income-statement" in path:
            data = income("Mar 2026", 400)
        elif "cash-flow" in path:
            data = {"cash_flow": [{"category": "operating", "history": [{"period": "Mar 2026", "value": 50}]}]}
        elif "key-ratios" in path:
            data = [{"name": "ROE", "company_value": "12%"}, {"name": "ROCE", "company_value": "15%"}]
        else:
            data = {"history": [{"period": "Mar 2026", "total_asset": 500, "total_liability": 200}]}
        return {"status": "success", "data": data}

    client._get = fake_get  # type: ignore[method-assign]
    result, context = client.fetch_financial_results("INE1", "NSE_EQ|INE1", "TEST")

    assert len(paths) == 5
    assert sum("fs=true" in path for path in paths) == 3
    assert result.quarterly_available is True
    assert result.annual_available is True
    assert context.revenue_period == "Jun 2026"
