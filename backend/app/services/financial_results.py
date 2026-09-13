"""Cache and availability rules for versioned company financial results."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from app.models.market import CorporateFinancialContext, FinancialResultSnapshot


def latest_category(payload: dict[str, object], collection: str, category: str) -> tuple[float | None, str | None]:
    rows = payload.get(collection)
    if not isinstance(rows, list):
        return None, None
    match = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(item.get("category", "")).casefold() == category.casefold()
        ),
        None,
    )
    history = match.get("history") if isinstance(match, dict) else None
    row = history[0] if isinstance(history, list) and history and isinstance(history[0], dict) else None
    if row is None:
        return None, None
    try:
        value = float(row["value"])
    except (KeyError, TypeError, ValueError):
        value = None
    period = str(row.get("period") or "").strip() or None
    return value, period


def latest_completed_quarter(as_of: date) -> tuple[int, int]:
    """Return month/year of the most recently completed calendar quarter."""
    quarter_end_month = ((as_of.month - 1) // 3) * 3
    year = as_of.year
    if quarter_end_month == 0:
        quarter_end_month = 12
        year -= 1
    return quarter_end_month, year


def period_is_latest_completed_quarter(period: str | None, as_of: date) -> bool:
    if not period:
        return False
    for pattern in ("%b %Y", "%B %Y"):
        try:
            parsed = datetime.strptime(period.strip(), pattern)
            return (parsed.month, parsed.year) == latest_completed_quarter(as_of)
        except ValueError:
            continue
    return False


def snapshot_is_reusable(
    snapshot: FinancialResultSnapshot | None,
    *,
    now: datetime,
    cache_days: int,
) -> bool:
    required_payloads = {
        "quarterly_income_statement",
        "annual_income_statement",
        "annual_cash_flow",
        "annual_balance_sheet",
        "key_ratios",
    }
    if (
        snapshot is None
        or not snapshot.quarterly_available
        or not required_payloads.issubset(snapshot.raw_payload)
    ):
        return False
    fresh_after = now.astimezone(UTC) - timedelta(days=cache_days)
    return (
        snapshot.last_seen_at.astimezone(UTC) >= fresh_after
        and period_is_latest_completed_quarter(snapshot.quarterly_period, now.date())
    )


def build_financial_snapshot(
    *,
    isin: str,
    instrument_key: str,
    symbol: str,
    quarterly_income: dict[str, object],
    annual_income: dict[str, object],
    annual_cash_flow: dict[str, object],
    annual_balance_sheet: dict[str, object],
    key_ratios: list[object] | None = None,
    captured_at: datetime | None = None,
) -> tuple[FinancialResultSnapshot, CorporateFinancialContext]:
    captured = captured_at or datetime.now(UTC)
    quarterly_revenue, quarterly_period = latest_category(
        quarterly_income, "income_statement", "revenue"
    )
    operating_profit, _ = latest_category(
        quarterly_income, "income_statement", "operating_profit"
    )
    net_profit, _ = latest_category(quarterly_income, "income_statement", "net_profit")
    annual_revenue, annual_period = latest_category(
        annual_income, "income_statement", "revenue"
    )
    operating_cash_flow, cash_period = latest_category(
        annual_cash_flow, "cash_flow", "operating"
    )
    payload: dict[str, object] = {
        "quarterly_income_statement": quarterly_income,
        "annual_income_statement": annual_income,
        "annual_cash_flow": annual_cash_flow,
        "annual_balance_sheet": annual_balance_sheet,
        "key_ratios": key_ratios or [],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    snapshot_id = hashlib.sha256(f"{isin}|consolidated|{canonical}".encode()).hexdigest()[:32]
    quarterly_available = bool(quarterly_period and quarterly_revenue is not None)
    annual_available = bool(
        annual_period
        and annual_revenue is not None
        and annual_cash_flow.get("cash_flow")
        and annual_balance_sheet.get("history")
    )
    snapshot = FinancialResultSnapshot(
        snapshot_id=snapshot_id,
        isin=isin,
        instrument_key=instrument_key,
        symbol=symbol,
        quarterly_period=quarterly_period,
        annual_period=annual_period,
        quarterly_available=quarterly_available,
        annual_available=annual_available,
        raw_payload=payload,
        captured_at=captured,
        last_seen_at=captured,
    )
    available = sum(
        value is not None
        for value in (quarterly_revenue, operating_profit, net_profit, operating_cash_flow)
    )
    context = CorporateFinancialContext(
        isin=isin,
        instrument_key=instrument_key,
        symbol=symbol,
        latest_revenue_crore=quarterly_revenue,
        latest_operating_profit_crore=operating_profit,
        latest_net_profit_crore=net_profit,
        latest_operating_cash_flow_crore=operating_cash_flow,
        revenue_period=quarterly_period,
        cash_flow_period=cash_period,
        raw_payload=payload,
        data_quality="complete" if available == 4 else "partial" if available else "unavailable",
        fetched_at=captured,
    )
    return snapshot, context


def context_from_financial_snapshot(
    snapshot: FinancialResultSnapshot,
) -> CorporateFinancialContext:
    payload = snapshot.raw_payload
    _, context = build_financial_snapshot(
        isin=snapshot.isin,
        instrument_key=snapshot.instrument_key,
        symbol=snapshot.symbol,
        quarterly_income=dict(payload.get("quarterly_income_statement", {})),
        annual_income=dict(payload.get("annual_income_statement", {})),
        annual_cash_flow=dict(payload.get("annual_cash_flow", {})),
        annual_balance_sheet=dict(payload.get("annual_balance_sheet", {})),
        key_ratios=list(payload.get("key_ratios", [])),
        captured_at=snapshot.last_seen_at,
    )
    return context
