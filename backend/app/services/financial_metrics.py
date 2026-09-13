"""Deterministic financial calculations over immutable Upstox result snapshots."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.models.market import (
    FinancialCapitalMetrics,
    FinancialEpsMetrics,
    FinancialGrowthMetrics,
    FinancialMarginMetrics,
    FinancialMetricSnapshot,
    FinancialResultSnapshot,
)

CALCULATION_VERSION = 1
NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None


def _normalized(value: object) -> str:
    return NON_ALNUM.sub(" ", str(value or "").casefold()).strip()


def _category_history(
    payload: dict[str, object], collection: str, category: str
) -> list[tuple[str, float]]:
    rows = payload.get(collection)
    if not isinstance(rows, list):
        return []
    match = next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and _normalized(row.get("category")) == _normalized(category)
        ),
        None,
    )
    history = match.get("history") if isinstance(match, dict) else None
    return _history_values(history)


def _history_values(rows: object) -> list[tuple[str, float]]:
    if not isinstance(rows, list):
        return []
    values = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        period = str(row.get("period") or "").strip()
        value = _number(row.get("value"))
        if period and value is not None:
            values.append((period, value))
    return values


def _line_history(payload: dict[str, object], names: tuple[str, ...]) -> list[tuple[str, float]]:
    rows = payload.get("full_statement")
    if not isinstance(rows, list):
        return []
    normalized_names = {_normalized(name) for name in names}
    match = next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and _normalized(row.get("particular")) in normalized_names
        ),
        None,
    )
    return _history_values(match.get("history")) if isinstance(match, dict) else []


def _borrowing_history(payload: dict[str, object]) -> list[tuple[str, float]]:
    exact = _line_history(payload, ("Total Borrowings", "Total Debt", "Borrowings"))
    if exact:
        return exact
    rows = payload.get("full_statement")
    if not isinstance(rows, list):
        return []
    by_period: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = _normalized(row.get("particular"))
        if "borrowing" not in label and label not in {"current debt", "non current debt"}:
            continue
        for period, value in _history_values(row.get("history")):
            by_period[period] = by_period.get(period, 0) + value
    return list(by_period.items())


def _value_for_period(history: list[tuple[str, float]], period: str | None) -> float | None:
    if not period:
        return None
    return next((value for row_period, value in history if row_period == period), None)


def _same_period_prior_year(
    history: list[tuple[str, float]], period: str | None = None
) -> float | None:
    if not history:
        return None
    reference_period = period or history[0][0]
    try:
        latest = datetime.strptime(reference_period, "%b %Y")
    except ValueError:
        return history[4][1] if period is None and len(history) > 4 else None
    target = (latest.month, latest.year - 1)
    for row_period, value in history:
        try:
            parsed = datetime.strptime(row_period, "%b %Y")
        except ValueError:
            continue
        if (parsed.month, parsed.year) == target:
            return value
    return None


def _growth(current: float | None, prior: float | None, *, positive_base: bool = False) -> float | None:
    if current is None or prior is None or prior == 0 or (positive_base and prior <= 0):
        return None
    return round((current / prior - 1) * 100, 4)


def _margin(profit: float | None, revenue: float | None) -> float | None:
    if profit is None or revenue is None or revenue <= 0:
        return None
    return round(profit / revenue * 100, 4)


def _ratio_value(rows: object, name: str) -> float | None:
    if not isinstance(rows, list):
        return None
    match = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and _normalized(row.get("name")) == _normalized(name)
        ),
        None,
    )
    return _number(match.get("company_value")) if isinstance(match, dict) else None


def calculate_financial_metrics(
    snapshot: FinancialResultSnapshot,
    *,
    calculated_at: datetime | None = None,
) -> FinancialMetricSnapshot:
    raw = snapshot.raw_payload
    quarterly = dict(raw.get("quarterly_income_statement", {}))
    annual = dict(raw.get("annual_income_statement", {}))
    cash_flow = dict(raw.get("annual_cash_flow", {}))
    balance = dict(raw.get("annual_balance_sheet", {}))
    key_ratios = raw.get("key_ratios", [])

    revenue = _category_history(quarterly, "income_statement", "revenue")
    operating_profit = _category_history(quarterly, "income_statement", "operating_profit")
    net_profit = _category_history(quarterly, "income_statement", "net_profit")
    annual_net_profit = _category_history(annual, "income_statement", "net_profit")
    operating_cash = _category_history(cash_flow, "cash_flow", "operating")

    current_quarter = revenue[0][0] if revenue else None
    previous_quarter = revenue[1][0] if len(revenue) > 1 else None
    current_revenue = _value_for_period(revenue, current_quarter)
    previous_revenue = _value_for_period(revenue, previous_quarter)
    yoy_revenue = _same_period_prior_year(revenue, current_quarter)
    current_operating = _value_for_period(operating_profit, current_quarter)
    previous_operating = _value_for_period(operating_profit, previous_quarter)
    yoy_operating = _same_period_prior_year(operating_profit, current_quarter)
    current_net = _value_for_period(net_profit, current_quarter)
    previous_net = _value_for_period(net_profit, previous_quarter)
    yoy_net = _same_period_prior_year(net_profit, current_quarter)

    current_operating_margin = _margin(current_operating, current_revenue)
    previous_operating_margin = _margin(previous_operating, previous_revenue)
    yoy_operating_margin = _margin(yoy_operating, yoy_revenue)
    current_net_margin = _margin(current_net, current_revenue)
    previous_net_margin = _margin(previous_net, previous_revenue)
    yoy_net_margin = _margin(yoy_net, yoy_revenue)

    cash_conversion = None
    cash_period = operating_cash[0][0] if operating_cash else None
    cash_value = _value_for_period(operating_cash, cash_period)
    matching_annual_net = _value_for_period(annual_net_profit, cash_period)
    if cash_value is not None and matching_annual_net is not None and matching_annual_net > 0:
        cash_conversion = round(cash_value / matching_annual_net * 100, 4)

    debt = _borrowing_history(balance)
    debt_latest = debt[0][1] if debt else None
    debt_prior = _same_period_prior_year(debt)
    equity = _line_history(balance, ("Total Equity", "Shareholders Funds", "Shareholders' Funds"))
    debt_to_equity = (
        round(debt_latest / equity[0][1], 4)
        if debt_latest is not None and equity and equity[0][1] > 0
        else None
    )
    balance_history = balance.get("history")
    liabilities: list[tuple[str, float]] = []
    if isinstance(balance_history, list):
        for row in balance_history:
            if isinstance(row, dict):
                value = _number(row.get("total_liability"))
                period = str(row.get("period") or "").strip()
                if period and value is not None:
                    liabilities.append((period, value))

    eps_history = _line_history(annual, ("EPS - Basic", "Basic EPS", "EPS Basic"))
    eps_latest = eps_history[0][1] if eps_history else None
    eps_prior = _same_period_prior_year(eps_history)
    roe = _ratio_value(key_ratios, "ROE")
    roce = _ratio_value(key_ratios, "ROCE")

    growth = FinancialGrowthMetrics(
        revenue_qoq_percent=_growth(current_revenue, previous_revenue),
        revenue_yoy_percent=_growth(current_revenue, yoy_revenue),
        operating_profit_qoq_percent=_growth(current_operating, previous_operating, positive_base=True),
        operating_profit_yoy_percent=_growth(current_operating, yoy_operating, positive_base=True),
        net_profit_qoq_percent=_growth(current_net, previous_net, positive_base=True),
        net_profit_yoy_percent=_growth(current_net, yoy_net, positive_base=True),
    )
    margins = FinancialMarginMetrics(
        operating_margin_percent=current_operating_margin,
        operating_margin_qoq_change_pp=(
            round(current_operating_margin - previous_operating_margin, 4)
            if current_operating_margin is not None and previous_operating_margin is not None else None
        ),
        operating_margin_yoy_change_pp=(
            round(current_operating_margin - yoy_operating_margin, 4)
            if current_operating_margin is not None and yoy_operating_margin is not None else None
        ),
        net_margin_percent=current_net_margin,
        net_margin_qoq_change_pp=(
            round(current_net_margin - previous_net_margin, 4)
            if current_net_margin is not None and previous_net_margin is not None else None
        ),
        net_margin_yoy_change_pp=(
            round(current_net_margin - yoy_net_margin, 4)
            if current_net_margin is not None and yoy_net_margin is not None else None
        ),
    )
    capital = FinancialCapitalMetrics(
        operating_cash_conversion_percent=cash_conversion,
        total_debt_crore=debt_latest,
        debt_yoy_change_percent=_growth(debt_latest, debt_prior),
        debt_to_equity=debt_to_equity,
        total_liabilities_crore=liabilities[0][1] if liabilities else None,
        liabilities_yoy_change_percent=_growth(
            liabilities[0][1] if liabilities else None,
            _same_period_prior_year(liabilities),
        ),
        roe_percent=roe,
        roce_percent=roce,
    )
    eps = FinancialEpsMetrics(
        latest_basic_eps=eps_latest,
        latest_period=eps_history[0][0] if eps_history else None,
        yoy_growth_percent=_growth(eps_latest, eps_prior, positive_base=True),
        history=[{"period": period, "value": value} for period, value in eps_history[:5]],
    )
    tracked: dict[str, float | None] = {
        **growth.model_dump(),
        **margins.model_dump(),
        "operating_cash_conversion_percent": cash_conversion,
        "total_debt_crore": debt_latest,
        "debt_yoy_change_percent": capital.debt_yoy_change_percent,
        "debt_to_equity": debt_to_equity,
        "total_liabilities_crore": capital.total_liabilities_crore,
        "liabilities_yoy_change_percent": capital.liabilities_yoy_change_percent,
        "roe_percent": roe,
        "roce_percent": roce,
        "latest_basic_eps": eps_latest,
        "eps_yoy_growth_percent": eps.yoy_growth_percent,
    }
    unavailable = [key for key, value in tracked.items() if value is None]
    cautions = []
    if previous_operating is not None and previous_operating <= 0:
        cautions.append("operating_profit_qoq_growth_suppressed_non_positive_base")
    if yoy_operating is not None and yoy_operating <= 0:
        cautions.append("operating_profit_yoy_growth_suppressed_non_positive_base")
    if previous_net is not None and previous_net <= 0:
        cautions.append("net_profit_qoq_growth_suppressed_non_positive_base")
    if yoy_net is not None and yoy_net <= 0:
        cautions.append("net_profit_yoy_growth_suppressed_non_positive_base")
    if debt_latest is None:
        cautions.append("explicit_borrowing_line_unavailable_total_liabilities_not_used_as_debt")
    available_count = len(tracked) - len(unavailable)
    return FinancialMetricSnapshot(
        source_snapshot_id=snapshot.snapshot_id,
        calculation_version=CALCULATION_VERSION,
        isin=snapshot.isin,
        instrument_key=snapshot.instrument_key,
        symbol=snapshot.symbol,
        latest_quarter=snapshot.quarterly_period,
        latest_annual_period=snapshot.annual_period,
        growth=growth,
        margins=margins,
        capital=capital,
        eps=eps,
        data_quality="complete" if available_count == len(tracked) else "partial" if available_count else "unavailable",
        unavailable=unavailable,
        cautions=cautions,
        formulas={
            "growth": "(current/prior - 1) * 100",
            "margin": "profit/revenue * 100",
            "margin_change": "current margin - comparison margin, in percentage points",
            "cash_conversion": "annual operating cash flow/annual net profit * 100",
            "debt_to_equity": "explicit total borrowings/explicit total equity",
            "roe_roce": "Upstox key-ratio company values",
        },
        calculated_at=calculated_at or datetime.now(UTC),
    )
