"""Official NSE announcement metadata ingestion for corporate-action grounding."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from app.models.market import CorporateAction, CorporateActionDocument
from app.services.market_context import INDIA_TIMEZONE

NSE_ROOT = "https://www.nseindia.com"
ACTION_TERMS = ("dividend", "bonus", "split", "sub-division", "rights", "buyback", "buy back", "merger", "demerger", "delisting")


def _published_at(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for pattern in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=INDIA_TIMEZONE).astimezone(UTC)
        except ValueError:
            continue
    return None


def normalize_nse_announcements(
    instrument_key: str,
    symbol: str,
    rows: Iterable[Any],
    actions: list[CorporateAction],
    *,
    ingested_at: datetime | None = None,
) -> list[CorporateActionDocument]:
    captured = ingested_at or datetime.now(UTC)
    documents = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        title = str(row.get("subject") or row.get("desc") or row.get("attchmntText") or "Corporate announcement").strip()
        summary = str(row.get("attchmntText") or row.get("desc") or "").strip() or None
        combined = f"{title} {summary or ''}".casefold()
        if not any(term in combined for term in ACTION_TERMS):
            continue
        published = _published_at(row.get("an_dt") or row.get("sort_date") or row.get("dt_tm"))
        if published is None:
            continue
        raw_url = str(row.get("attchmntFile") or row.get("attachment") or "").strip()
        if not raw_url:
            continue
        source_url = raw_url if raw_url.startswith("http") else urljoin("https://nsearchives.nseindia.com/", raw_url.lstrip("/"))
        matched = []
        for action in actions:
            action_date = action.announcement_date or action.ex_date or action.record_date
            published_date = published.astimezone(INDIA_TIMEZONE).date()
            if action_date and abs((published_date - action_date).days) <= 45:
                matched.append(action.event_id)
        if not matched:
            continue
        document_id = hashlib.sha256(f"nse|{source_url}|{published.isoformat()}".encode()).hexdigest()[:32]
        documents.append(
            CorporateActionDocument(
                document_id=document_id,
                instrument_key=instrument_key,
                symbol=symbol,
                source="nse",
                published_at=published,
                title=title,
                summary=summary,
                source_url=source_url,
                document_text="\n".join(value for value in (title, summary) if value),
                matched_event_ids=matched,
                raw_payload=dict(row),
                ingested_at=captured,
            )
        )
    return documents


class NseAnnouncementClient:
    """Small best-effort adapter around NSE's public corporate-filings surface."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=NSE_ROOT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-IN,en;q=0.9",
                "Referer": f"{NSE_ROOT}/companies-listing/corporate-filings-announcements",
            },
            timeout=20,
            follow_redirects=True,
        )
        self._client.get("/companies-listing/corporate-filings-announcements")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NseAnnouncementClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(
        self,
        instrument_key: str,
        symbol: str,
        actions: list[CorporateAction],
        *,
        from_date: date,
        to_date: date,
    ) -> list[CorporateActionDocument]:
        response = self._client.get(
            "/api/corporate-announcements",
            params={
                "index": "equities",
                "symbol": symbol,
                "from_date": from_date.strftime("%d-%m-%Y"),
                "to_date": to_date.strftime("%d-%m-%Y"),
            },
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("NSE corporate-announcement response was not a list")
        return normalize_nse_announcements(instrument_key, symbol, rows, actions)
