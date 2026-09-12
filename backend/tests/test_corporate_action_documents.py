from datetime import UTC, date, datetime

from app.models.market import CorporateAction
from app.services.corporate_action_documents import normalize_nse_announcements


def test_nse_documents_require_relevant_text_date_match_and_source_url() -> None:
    action = CorporateAction(
        event_id="event-1", isin="INE1", instrument_key="NSE_EQ|INE1", symbol="TEST",
        action_type="Dividend", announcement_date=date(2026, 7, 1), details={}, raw_payload={},
        ingested_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    rows = [{
        "subject": "Board recommends final dividend",
        "attchmntText": "Dividend of Rs 2 per share",
        "an_dt": "01-Jul-2026 12:30:00",
        "attchmntFile": "/corporate/TEST.pdf",
    }]

    documents = normalize_nse_announcements(action.instrument_key, action.symbol, rows, [action])

    assert len(documents) == 1
    assert documents[0].matched_event_ids == ["event-1"]
    assert documents[0].source_url.startswith("https://nsearchives.nseindia.com/")
    assert "dividend" in (documents[0].document_text or "").casefold()
