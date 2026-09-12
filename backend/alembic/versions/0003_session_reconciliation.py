"""Add after-market session reconciliation records.

Revision ID: 0003_session_reconciliation
Revises: 0002_minute_history_profiles
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_session_reconciliation"
down_revision: str | None = "0002_minute_history_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_reconciliations",
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("instrument_key", sa.String(length=160), nullable=False),
        sa.Column("symbol", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("minute_count", sa.Integer(), nullable=False),
        sa.Column("expected_minutes", sa.Integer(), nullable=False),
        sa.Column("official_close", sa.Numeric(20, 6), nullable=False),
        sa.Column("official_volume", sa.BigInteger(), nullable=False),
        sa.Column("aggregated_close", sa.Numeric(20, 6)),
        sa.Column("aggregated_volume", sa.BigInteger()),
        sa.Column("volume_difference_percent", sa.Numeric(18, 6)),
        sa.Column("ohlc_matches", sa.Boolean()),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("session_date", "instrument_key"),
    )
    op.create_index(
        "ix_session_reconciliations_status",
        "session_reconciliations",
        ["session_date", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_reconciliations_status", table_name="session_reconciliations")
    op.drop_table("session_reconciliations")

