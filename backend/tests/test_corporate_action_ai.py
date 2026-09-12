import json
from datetime import UTC, date, datetime

import httpx

from app.models.market import CorporateAction, CorporateActionDocument
from app.services.corporate_action_ai import CorporateActionAIScorer
from app.services.corporate_action_assessment import assess_corporate_action


def fixtures() -> tuple[CorporateAction, CorporateActionDocument]:
    action = CorporateAction(
        event_id="event-1", isin="INE1", instrument_key="NSE_EQ|INE1", symbol="TEST",
        action_type="Buyback", announcement_date=date(2026, 7, 1), details={"price": "120"},
        raw_payload={}, ingested_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    document = CorporateActionDocument(
        document_id="doc-1", instrument_key=action.instrument_key, symbol=action.symbol,
        source="nse", published_at=datetime(2026, 7, 1, tzinfo=UTC), title="Buyback",
        source_url="https://example.test/filing.pdf", document_text="Board approved a buyback.",
        matched_event_ids=[action.event_id], ingested_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    return action, document


def test_ai_requires_documents_without_network_call() -> None:
    action, _ = fixtures()
    scorer = CorporateActionAIScorer("unused", "configured-model", httpx.Client(transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError()))))
    result = scorer.analyze(action, assess_corporate_action(action, reference_price=100), [], None)
    assert result.status == "unavailable"
    assert result.error == "supporting_documents_unavailable"


def test_ai_accepts_only_grounded_structured_output() -> None:
    action, document = fixtures()
    structured = {
        "impact_score": 30, "impact_probability": 0.7, "confidence": 0.6,
        "impact_horizon": "weeks", "rationale": "Offer terms support demand.",
        "positive_factors": ["premium"], "negative_factors": ["participation unknown"],
        "citation_document_ids": ["doc-1"],
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": json.dumps(structured)}]}]}))
    scorer = CorporateActionAIScorer("unused", "configured-model", httpx.Client(transport=transport, base_url="https://api.test"))
    result = scorer.analyze(action, assess_corporate_action(action, reference_price=100), [document], None)
    assert result.status == "complete"
    assert result.grounded is True
    assert result.impact_score == 30
    assert result.citation_document_ids == ["doc-1"]
