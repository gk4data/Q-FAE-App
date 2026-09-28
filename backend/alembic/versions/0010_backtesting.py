"""Add reproducible backtest runs and simulated trades.

Revision ID: 0010_backtesting
Revises: 0009_financial_metrics
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_backtesting"
down_revision: str | None = "0009_financial_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("config_payload", sa.JSON(), nullable=False),
        sa.Column("summary_payload", sa.JSON(), nullable=False),
        sa.Column("breakdowns_payload", sa.JSON(), nullable=False),
        sa.Column("model_versions", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_backtest_runs_created", "backtest_runs", ["created_at"])
    op.create_table(
        "backtest_trades",
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("trade_id", sa.String(32), nullable=False),
        sa.Column("instrument_key", sa.String(160), nullable=False),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("signal_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opportunity_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("net_return_percent", sa.Numeric(18, 6), nullable=False),
        sa.Column("pnl_inr", sa.Numeric(20, 2), nullable=False),
        sa.Column("exit_reason", sa.String(48), nullable=False),
        sa.Column("trade_payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "trade_id"),
    )
    op.create_index(
        "ix_backtest_trades_run_entry", "backtest_trades", ["run_id", "entry_timestamp"]
    )
    op.create_index(
        "ix_backtest_trades_symbol", "backtest_trades", ["symbol", "signal_timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_trades_symbol", table_name="backtest_trades")
    op.drop_index("ix_backtest_trades_run_entry", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index("ix_backtest_runs_created", table_name="backtest_runs")
    op.drop_table("backtest_runs")
