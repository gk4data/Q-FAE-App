from datetime import UTC, datetime

from app.services.financial_metrics import calculate_financial_metrics
from app.services.financial_results import build_financial_snapshot


def category(name: str, values: list[tuple[str, float]]) -> dict[str, object]:
    return {
        "category": name,
        "history": [{"period": period, "value": value} for period, value in values],
    }


def full_line(name: str, values: list[tuple[str, float]]) -> dict[str, object]:
    return {
        "particular": name,
        "history": [{"period": period, "value": value} for period, value in values],
    }


def test_all_requested_financial_metrics_are_calculated_with_explicit_formulas() -> None:
    quarters = ["Jun 2026", "Mar 2026", "Dec 2025", "Sep 2025", "Jun 2025"]
    quarterly = {
        "income_statement": [
            category("revenue", list(zip(quarters, [120, 100, 90, 85, 80]))),
            category("operating_profit", list(zip(quarters, [24, 18, 16, 14, 12]))),
            category("net_profit", list(zip(quarters, [12, 8, 7, 6, 5]))),
        ]
    }
    annual = {
        "income_statement": [
            category("revenue", [("Mar 2026", 400), ("Mar 2025", 340)]),
            category("operating_profit", [("Mar 2026", 72), ("Mar 2025", 60)]),
            category("net_profit", [("Mar 2026", 40), ("Mar 2025", 32)]),
        ],
        "full_statement": [full_line("EPS - Basic", [("Mar 2026", 10), ("Mar 2025", 8)])],
    }
    cash = {"cash_flow": [category("operating", [("Mar 2026", 50), ("Mar 2025", 38)])]}
    balance = {
        "history": [
            {"period": "Mar 2026", "total_asset": 700, "total_liability": 300},
            {"period": "Mar 2025", "total_asset": 650, "total_liability": 280},
        ],
        "full_statement": [
            full_line("Total Borrowings", [("Mar 2026", 100), ("Mar 2025", 125)]),
            full_line("Total Equity", [("Mar 2026", 200), ("Mar 2025", 180)]),
        ],
    }
    snapshot, _ = build_financial_snapshot(
        isin="INE1",
        instrument_key="NSE_EQ|INE1",
        symbol="TEST",
        quarterly_income=quarterly,
        annual_income=annual,
        annual_cash_flow=cash,
        annual_balance_sheet=balance,
        key_ratios=[
            {"name": "ROE", "company_value": "12.5%"},
            {"name": "ROCE", "company_value": "15%"},
        ],
        captured_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    metrics = calculate_financial_metrics(snapshot)

    assert metrics.growth.revenue_qoq_percent == 20
    assert metrics.growth.revenue_yoy_percent == 50
    assert metrics.growth.net_profit_yoy_percent == 140
    assert metrics.margins.operating_margin_percent == 20
    assert metrics.margins.operating_margin_qoq_change_pp == 2
    assert metrics.capital.operating_cash_conversion_percent == 125
    assert metrics.capital.total_debt_crore == 100
    assert metrics.capital.debt_yoy_change_percent == -20
    assert metrics.capital.debt_to_equity == 0.5
    assert metrics.capital.roe_percent == 12.5
    assert metrics.capital.roce_percent == 15
    assert metrics.eps.latest_basic_eps == 10
    assert metrics.eps.yoy_growth_percent == 25
    assert metrics.data_quality == "complete"


def test_profit_growth_is_not_manufactured_from_a_loss_base() -> None:
    quarters = ["Jun 2026", "Mar 2026", "Dec 2025", "Sep 2025", "Jun 2025"]
    quarterly = {
        "income_statement": [
            category("revenue", list(zip(quarters, [100, 90, 85, 80, 75]))),
            category("operating_profit", list(zip(quarters, [10, -2, 3, 2, -4]))),
            category("net_profit", list(zip(quarters, [5, -1, 1, 1, -3]))),
        ]
    }
    snapshot, _ = build_financial_snapshot(
        isin="INE1", instrument_key="NSE_EQ|INE1", symbol="TEST",
        quarterly_income=quarterly, annual_income={}, annual_cash_flow={},
        annual_balance_sheet={}, captured_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    metrics = calculate_financial_metrics(snapshot)

    assert metrics.growth.operating_profit_qoq_percent is None
    assert metrics.growth.net_profit_yoy_percent is None
    assert "net_profit_qoq_growth_suppressed_non_positive_base" in metrics.cautions


def test_cash_conversion_matches_net_profit_to_the_cash_flow_period() -> None:
    snapshot, _ = build_financial_snapshot(
        isin="INE1",
        instrument_key="NSE_EQ|INE1",
        symbol="TEST",
        quarterly_income={},
        annual_income={
            "income_statement": [
                category("net_profit", [("Mar 2026", 50), ("Mar 2025", 40)])
            ]
        },
        annual_cash_flow={
            "cash_flow": [category("operating", [("Mar 2025", 60), ("Mar 2024", 45)])]
        },
        annual_balance_sheet={},
        captured_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    metrics = calculate_financial_metrics(snapshot)

    assert metrics.capital.operating_cash_conversion_percent == 150
