"""Store daily spread and visible-depth slippage medians.

Revision ID: 0011_execution_quality
Revises: 0010_backtesting
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_execution_quality"
down_revision: str | None = "0010_backtesting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_execution_quality",
        sa.Column("instrument_key", sa.String(160), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("median_spread_bps", sa.Numeric(18, 6)),
        sa.Column("median_buy_slippage_bps", sa.Numeric(18, 6)),
        sa.Column("median_sell_slippage_bps", sa.Numeric(18, 6)),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_key", "session_date"),
    )
    op.create_index(
        "ix_daily_execution_quality_date",
        "daily_execution_quality",
        ["session_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_execution_quality_date", table_name="daily_execution_quality")
    op.drop_table("daily_execution_quality")
