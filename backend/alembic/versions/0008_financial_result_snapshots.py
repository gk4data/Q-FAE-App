"""Add content-versioned quarterly and annual financial-result snapshots.

Revision ID: 0008_financial_snapshots
Revises: 0007_corp_action_pipeline
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_financial_snapshots"
down_revision: str | None = "0007_corp_action_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_result_snapshots",
        sa.Column("snapshot_id", sa.String(32), primary_key=True),
        sa.Column("isin", sa.String(20), nullable=False),
        sa.Column("instrument_key", sa.String(160), nullable=False),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("statement_type", sa.String(24), nullable=False),
        sa.Column("quarterly_period", sa.String(40)),
        sa.Column("annual_period", sa.String(40)),
        sa.Column("quarterly_available", sa.Boolean(), nullable=False),
        sa.Column("annual_available", sa.Boolean(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_financial_result_snapshots_instrument",
        "financial_result_snapshots",
        ["instrument_key", "last_seen_at"],
    )
    op.create_index(
        "ix_financial_result_snapshots_isin",
        "financial_result_snapshots",
        ["isin", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_financial_result_snapshots_isin", table_name="financial_result_snapshots")
    op.drop_index(
        "ix_financial_result_snapshots_instrument",
        table_name="financial_result_snapshots",
    )
    op.drop_table("financial_result_snapshots")
