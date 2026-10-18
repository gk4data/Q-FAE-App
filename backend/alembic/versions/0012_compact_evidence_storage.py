"""Add compact background-universe evidence checkpoints.

Revision ID: 0012_compact_evidence
Revises: 0011_execution_quality
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_compact_evidence"
down_revision: str | None = "0011_execution_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compact_evidence_observations",
        sa.Column("instrument_key", sa.String(160), nullable=False),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("sector", sa.String(120)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("opportunity_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("coverage_percent", sa.Numeric(8, 4), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("score_status", sa.String(40), nullable=False),
        sa.Column("confluence", sa.String(40), nullable=False),
        sa.Column("signal_state", sa.String(40), nullable=False),
        sa.Column("risk_status", sa.String(40)),
        sa.Column("liquidity_tier", sa.String(24), nullable=False),
        sa.Column("market_regime_state", sa.String(40)),
        sa.Column("flow_confirmation", sa.String(40)),
        sa.Column("price_trend_score", sa.Numeric(8, 4)),
        sa.Column("participation_score", sa.Numeric(8, 4)),
        sa.Column("market_sector_score", sa.Numeric(8, 4)),
        sa.Column("fundamental_score", sa.Numeric(8, 4)),
        sa.Column("capture_reason", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("instrument_key", "candle_timestamp"),
    )
    op.create_index(
        "ix_compact_evidence_time",
        "compact_evidence_observations",
        ["candle_timestamp"],
    )
    op.create_index(
        "ix_compact_evidence_candidate",
        "compact_evidence_observations",
        ["eligible", "opportunity_score", "candle_timestamp"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_compact_evidence_candidate",
        table_name="compact_evidence_observations",
    )
    op.drop_index(
        "ix_compact_evidence_time",
        table_name="compact_evidence_observations",
    )
    op.drop_table("compact_evidence_observations")
