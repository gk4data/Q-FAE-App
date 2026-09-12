"""Add normalized corporate-action storage.

Revision ID: 0005_corporate_actions
Revises: 0004_evidence_outcomes
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_corporate_actions"
down_revision: str | None = "0004_evidence_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corporate_actions",
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("isin", sa.String(length=20), nullable=False),
        sa.Column("instrument_key", sa.String(length=160), nullable=False),
        sa.Column("symbol", sa.String(length=80), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("announcement_date", sa.Date()),
        sa.Column("ex_date", sa.Date()),
        sa.Column("record_date", sa.Date()),
        sa.Column("amount", sa.Numeric(20, 6)),
        sa.Column("ratio", sa.String(length=80)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_corporate_actions_isin_ex_date", "corporate_actions", ["isin", "ex_date"])
    op.create_index("ix_corporate_actions_instrument", "corporate_actions", ["instrument_key", "ex_date"])


def downgrade() -> None:
    op.drop_index("ix_corporate_actions_instrument", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_isin_ex_date", table_name="corporate_actions")
    op.drop_table("corporate_actions")
