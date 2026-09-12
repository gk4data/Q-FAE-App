"""Create durable historical market-data tables.

Revision ID: 0001_historical_market_data
Revises:
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_historical_market_data"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_candles",
        sa.Column("instrument_key", sa.String(length=160), nullable=False),
        sa.Column("interval", sa.String(length=20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(20, 6), nullable=False),
        sa.Column("high", sa.Numeric(20, 6), nullable=False),
        sa.Column("low", sa.Numeric(20, 6), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("open_interest", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("adjustment_status", sa.String(length=24), server_default="raw", nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_key", "interval", "timestamp"),
    )
    op.create_index(
        "ix_market_candles_interval_timestamp",
        "market_candles",
        ["interval", "timestamp"],
    )
    op.create_table(
        "data_sync_state",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("instrument_key", sa.String(length=160), nullable=False),
        sa.Column("data_through", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("provider", "dataset", "instrument_key"),
    )


def downgrade() -> None:
    op.drop_table("data_sync_state")
    op.drop_index("ix_market_candles_interval_timestamp", table_name="market_candles")
    op.drop_table("market_candles")

