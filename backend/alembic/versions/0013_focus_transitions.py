"""Add durable intraday focus transition records.

Revision ID: 0013_focus_transitions
Revises: 0012_compact_evidence
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_focus_transitions"
down_revision: str | None = "0012_compact_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "focus_transitions",
        sa.Column("instrument_key", sa.String(160), nullable=False),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("sector", sa.String(120)),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_state", sa.String(24)),
        sa.Column("to_state", sa.String(24), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("opportunity_score", sa.Numeric(8, 4)),
        sa.Column("coverage_percent", sa.Numeric(8, 4)),
        sa.Column("market_regime_state", sa.String(40)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("instrument_key", "candle_timestamp"),
    )
    op.create_index(
        "ix_focus_transitions_session",
        "focus_transitions",
        ["session_date", "candle_timestamp"],
    )
    op.create_index(
        "ix_focus_transitions_state",
        "focus_transitions",
        ["to_state", "candle_timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_focus_transitions_state", table_name="focus_transitions")
    op.drop_index("ix_focus_transitions_session", table_name="focus_transitions")
    op.drop_table("focus_transitions")
