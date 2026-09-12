"""Add deterministic corporate-action assessments.

Revision ID: 0006_corp_action_scores
Revises: 0005_corporate_actions
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_corp_action_scores"
down_revision: str | None = "0005_corporate_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corporate_action_assessments",
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("assessment_version", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=20), nullable=False),
        sa.Column("instrument_key", sa.String(length=160), nullable=False),
        sa.Column("symbol", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=24), nullable=False),
        sa.Column("materiality_score", sa.Numeric(8, 2), nullable=False),
        sa.Column("sentiment_score", sa.Numeric(8, 2), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("impact_horizon", sa.String(length=80), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 6)),
        sa.Column("reference_price_date", sa.Date()),
        sa.Column("derived_metrics", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("cautions", sa.JSON(), nullable=False),
        sa.Column("requires_ai_review", sa.Boolean(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "assessment_version"),
        sa.ForeignKeyConstraint(["event_id"], ["corporate_actions.event_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_corporate_action_assessments_instrument", "corporate_action_assessments", ["instrument_key", "category"])
    op.create_index("ix_corporate_action_assessments_direction", "corporate_action_assessments", ["direction", "materiality_score"])


def downgrade() -> None:
    op.drop_index("ix_corporate_action_assessments_direction", table_name="corporate_action_assessments")
    op.drop_index("ix_corporate_action_assessments_instrument", table_name="corporate_action_assessments")
    op.drop_table("corporate_action_assessments")
