"""Optional grounded AI interpretation of corporate actions via OpenAI Responses API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx

from app.models.market import (
    CorporateAction,
    CorporateActionAIAnalysis,
    CorporateActionAssessment,
    CorporateActionDocument,
    CorporateFinancialContext,
)

AI_ANALYSIS_VERSION = 1
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "impact_score": {"type": "number", "minimum": -100, "maximum": 100},
        "impact_probability": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "impact_horizon": {"type": "string", "enum": ["intraday", "days", "weeks", "months", "mechanical"]},
        "rationale": {"type": "string"},
        "positive_factors": {"type": "array", "items": {"type": "string"}},
        "negative_factors": {"type": "array", "items": {"type": "string"}},
        "citation_document_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["impact_score", "impact_probability", "confidence", "impact_horizon", "rationale", "positive_factors", "negative_factors", "citation_document_ids"],
}


def unavailable_ai_analysis(
    event_id: str,
    *,
    model: str | None,
    reason: str,
) -> CorporateActionAIAnalysis:
    return CorporateActionAIAnalysis(
        event_id=event_id,
        analysis_version=AI_ANALYSIS_VERSION,
        provider="openai",
        model=model,
        status="unavailable",
        error=reason,
        analyzed_at=datetime.now(UTC),
    )


class CorporateActionAIScorer:
    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.model = model
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CorporateActionAIScorer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def analyze(
        self,
        action: CorporateAction,
        assessment: CorporateActionAssessment,
        documents: list[CorporateActionDocument],
        financial_context: CorporateFinancialContext | None,
    ) -> CorporateActionAIAnalysis:
        if not documents:
            return unavailable_ai_analysis(action.event_id, model=self.model, reason="supporting_documents_unavailable")
        input_payload = {
            "event": action.model_dump(mode="json", exclude={"raw_payload"}),
            "deterministic_assessment": assessment.model_dump(mode="json"),
            "financial_context": financial_context.model_dump(mode="json", exclude={"raw_payload"}) if financial_context else None,
            "documents": [
                {
                    "document_id": item.document_id,
                    "title": item.title,
                    "published_at": item.published_at.isoformat(),
                    "source_url": item.source_url,
                    "text": (item.document_text or item.summary or "")[:12000],
                }
                for item in documents
            ],
        }
        try:
            response = self._client.post(
                "/responses",
                json={
                "model": self.model,
                "store": False,
                "max_output_tokens": 900,
                "instructions": (
                    "You assess the likely price impact of an Indian listed-company corporate action. "
                    "Use only supplied facts and documents. Do not treat a split or bonus as value creation. "
                    "Distinguish mechanical price effects from economic impact. Cite only supplied document_id values. "
                    "Lower confidence when expectations, funding, participation, or transaction terms are absent."
                ),
                "input": json.dumps(input_payload, separators=(",", ":"), default=str),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "corporate_action_impact",
                        "strict": True,
                        "schema": OUTPUT_SCHEMA,
                    }
                },
                },
            )
            response.raise_for_status()
            payload = response.json()
            output_text = "".join(
                str(content.get("text", ""))
                for item in payload.get("output", [])
                if isinstance(item, dict)
                for content in item.get("content", [])
                if isinstance(content, dict) and content.get("type") == "output_text"
            )
            result = json.loads(output_text)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            return unavailable_ai_analysis(action.event_id, model=self.model, reason=f"ai_request_or_schema_failed:{type(exc).__name__}")
        allowed = {item.document_id for item in documents}
        citations = [str(item) for item in result.get("citation_document_ids", []) if str(item) in allowed]
        grounded = bool(citations)
        return CorporateActionAIAnalysis(
            event_id=action.event_id,
            analysis_version=AI_ANALYSIS_VERSION,
            provider="openai",
            model=self.model,
            status="complete" if grounded else "unavailable",
            impact_score=float(result["impact_score"]) if grounded else None,
            impact_probability=float(result["impact_probability"]) if grounded else None,
            confidence=float(result["confidence"]) if grounded else None,
            impact_horizon=str(result["impact_horizon"]) if grounded else None,
            rationale=str(result["rationale"]) if grounded else None,
            positive_factors=[str(item) for item in result.get("positive_factors", [])] if grounded else [],
            negative_factors=[str(item) for item in result.get("negative_factors", [])] if grounded else [],
            citation_document_ids=citations,
            grounded=grounded,
            error=None if grounded else "model_returned_no_valid_citations",
            analyzed_at=datetime.now(UTC),
        )
