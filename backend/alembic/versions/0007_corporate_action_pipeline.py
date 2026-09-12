"""Add corporate-action adjustments, grounding, AI analyses, and outcomes.

Revision ID: 0007_corp_action_pipeline
Revises: 0006_corp_action_scores
"""
from typing import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0007_corp_action_pipeline"
down_revision: str | None = "0006_corp_action_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("corporate_action_adjustments",
        sa.Column("event_id", sa.String(32), nullable=False), sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("instrument_key", sa.String(160), nullable=False), sa.Column("category", sa.String(40), nullable=False),
        sa.Column("effective_date", sa.Date()), sa.Column("price_factor", sa.Numeric(20,12)), sa.Column("volume_factor", sa.Numeric(20,12)),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("reason", sa.String(160), nullable=False), sa.Column("reference_close", sa.Numeric(20,6)),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "calculation_version"), sa.ForeignKeyConstraint(["event_id"], ["corporate_actions.event_id"], ondelete="CASCADE"))
    op.create_table("corporate_action_documents",
        sa.Column("document_id", sa.String(32), primary_key=True), sa.Column("instrument_key", sa.String(160), nullable=False), sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("source", sa.String(32), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True), nullable=False), sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()), sa.Column("source_url", sa.Text(), nullable=False), sa.Column("document_text", sa.Text()), sa.Column("matched_event_ids", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False), sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_corporate_action_documents_instrument", "corporate_action_documents", ["instrument_key", "published_at"])
    op.create_table("corporate_financial_contexts",
        sa.Column("isin", sa.String(20), primary_key=True), sa.Column("instrument_key", sa.String(160), nullable=False), sa.Column("symbol", sa.String(80), nullable=False), sa.Column("statement_type", sa.String(24), nullable=False),
        sa.Column("latest_revenue_crore", sa.Numeric(24,4)), sa.Column("latest_operating_profit_crore", sa.Numeric(24,4)), sa.Column("latest_net_profit_crore", sa.Numeric(24,4)), sa.Column("latest_operating_cash_flow_crore", sa.Numeric(24,4)),
        sa.Column("revenue_period", sa.String(40)), sa.Column("cash_flow_period", sa.String(40)), sa.Column("raw_payload", sa.JSON(), nullable=False), sa.Column("data_quality", sa.String(24), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("corporate_action_ai_analyses",
        sa.Column("event_id", sa.String(32), nullable=False), sa.Column("analysis_version", sa.Integer(), nullable=False), sa.Column("provider", sa.String(32), nullable=False), sa.Column("model", sa.String(80)), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("impact_score", sa.Numeric(8,2)), sa.Column("impact_probability", sa.Numeric(5,4)), sa.Column("confidence", sa.Numeric(5,4)), sa.Column("impact_horizon", sa.String(40)), sa.Column("rationale", sa.Text()),
        sa.Column("positive_factors", sa.JSON(), nullable=False), sa.Column("negative_factors", sa.JSON(), nullable=False), sa.Column("citation_document_ids", sa.JSON(), nullable=False), sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(240)), sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "analysis_version"), sa.ForeignKeyConstraint(["event_id"], ["corporate_actions.event_id"], ondelete="CASCADE"))
    op.create_table("corporate_action_outcomes",
        sa.Column("event_id", sa.String(32), primary_key=True), sa.Column("instrument_key", sa.String(160), nullable=False), sa.Column("event_date", sa.Date(), nullable=False), sa.Column("reference_price", sa.Numeric(20,6)),
        sa.Column("return_1d_percent", sa.Numeric(18,6)), sa.Column("abnormal_return_1d_percent", sa.Numeric(18,6)), sa.Column("return_5d_percent", sa.Numeric(18,6)), sa.Column("abnormal_return_5d_percent", sa.Numeric(18,6)),
        sa.Column("return_20d_percent", sa.Numeric(18,6)), sa.Column("abnormal_return_20d_percent", sa.Numeric(18,6)), sa.Column("outcome_status", sa.String(24), nullable=False), sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["event_id"], ["corporate_actions.event_id"], ondelete="CASCADE"))
    op.create_index("ix_corporate_action_outcomes_instrument", "corporate_action_outcomes", ["instrument_key", "event_date"])


def downgrade() -> None:
    op.drop_index("ix_corporate_action_outcomes_instrument", table_name="corporate_action_outcomes")
    op.drop_table("corporate_action_outcomes")
    op.drop_table("corporate_action_ai_analyses")
    op.drop_table("corporate_financial_contexts")
    op.drop_index("ix_corporate_action_documents_instrument", table_name="corporate_action_documents")
    op.drop_table("corporate_action_documents")
    op.drop_table("corporate_action_adjustments")
