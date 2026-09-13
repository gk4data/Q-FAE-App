"""Add versioned deterministic financial metric snapshots.

Revision ID: 0009_financial_metrics
Revises: 0008_financial_snapshots
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_financial_metrics"
down_revision: str | None = "0008_financial_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_metric_snapshots",
        sa.Column("source_snapshot_id", sa.String(32), nullable=False),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(20), nullable=False),
        sa.Column("instrument_key", sa.String(160), nullable=False),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("latest_quarter", sa.String(40)),
        sa.Column("latest_annual_period", sa.String(40)),
        sa.Column("metrics_payload", sa.JSON(), nullable=False),
        sa.Column("data_quality", sa.String(24), nullable=False),
        sa.Column("unavailable", sa.JSON(), nullable=False),
        sa.Column("cautions", sa.JSON(), nullable=False),
        sa.Column("formulas", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("source_snapshot_id", "calculation_version"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["financial_result_snapshots.snapshot_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_financial_metric_snapshots_instrument",
        "financial_metric_snapshots",
        ["instrument_key", "calculated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_financial_metric_snapshots_instrument",
        table_name="financial_metric_snapshots",
    )
    op.drop_table("financial_metric_snapshots")
