"""Add bounded minute history support and rolling minute profiles.

Revision ID: 0002_minute_history_profiles
Revises: 0001_historical_market_data
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_minute_history_profiles"
down_revision: str | None = "0001_historical_market_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minute_of_day_profiles",
        sa.Column("instrument_key", sa.String(length=160), nullable=False),
        sa.Column("minute_of_session", sa.SmallInteger(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("mean_volume", sa.Numeric(24, 6), nullable=False),
        sa.Column("median_volume", sa.Numeric(24, 6), nullable=False),
        sa.Column("volume_stddev", sa.Numeric(24, 6), nullable=False),
        sa.Column("volume_p25", sa.Numeric(24, 6), nullable=False),
        sa.Column("volume_p75", sa.Numeric(24, 6), nullable=False),
        sa.Column("mean_range_bps", sa.Numeric(18, 6)),
        sa.Column("mean_abs_return_bps", sa.Numeric(18, 6)),
        sa.Column("mean_traded_value_inr", sa.Numeric(24, 2)),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("data_through", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_key", "minute_of_session"),
    )
    op.create_index(
        "ix_minute_profiles_minute_of_session",
        "minute_of_day_profiles",
        ["minute_of_session"],
    )


def downgrade() -> None:
    op.drop_index("ix_minute_profiles_minute_of_session", table_name="minute_of_day_profiles")
    op.drop_table("minute_of_day_profiles")

