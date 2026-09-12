"""Add point-in-time evidence observations and outcomes.

Revision ID: 0004_evidence_outcomes
Revises: 0003_session_reconciliation
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_evidence_outcomes"
down_revision: str | None = "0003_session_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_observations",
        sa.Column("instrument_key", sa.String(length=160), nullable=False),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(length=80), nullable=False),
        sa.Column("sector", sa.String(length=120)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("confluence", sa.String(length=40), nullable=False),
        sa.Column("signal_state", sa.String(length=40), nullable=False),
        sa.Column("data_quality", sa.String(length=40), nullable=False),
        sa.Column("evidence_payload", sa.JSON(), nullable=False),
        sa.Column("risk_payload", sa.JSON()),
        sa.Column("market_regime_payload", sa.JSON()),
        sa.Column("forward_return_5m_percent", sa.Numeric(18, 6)),
        sa.Column("forward_return_15m_percent", sa.Numeric(18, 6)),
        sa.Column("forward_return_30m_percent", sa.Numeric(18, 6)),
        sa.Column("forward_return_60m_percent", sa.Numeric(18, 6)),
        sa.Column("forward_return_eod_percent", sa.Numeric(18, 6)),
        sa.Column("mfe_60m_percent", sa.Numeric(18, 6)),
        sa.Column("mae_60m_percent", sa.Numeric(18, 6)),
        sa.Column("outcome_status", sa.String(length=24), nullable=False),
        sa.Column("evaluated_through", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_key", "candle_timestamp"),
    )
    op.create_index("ix_evidence_observations_time", "evidence_observations", ["candle_timestamp"])
    op.create_index("ix_evidence_observations_signal", "evidence_observations", ["signal_state", "outcome_status"])


def downgrade() -> None:
    op.drop_index("ix_evidence_observations_signal", table_name="evidence_observations")
    op.drop_index("ix_evidence_observations_time", table_name="evidence_observations")
    op.drop_table("evidence_observations")
