"""Phase 5: manual_payment_requests для ручной оплаты переводом."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_manual_payment_requests"
down_revision: Union[str, None] = "003_telegram_identity_linking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_payment_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("subscriber_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("amount_label_snapshot", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["subscriber_id"], ["subscribers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_payment_requests_telegram_user_id", "manual_payment_requests", ["telegram_user_id"])
    op.create_index("ix_manual_payment_requests_subscriber_id", "manual_payment_requests", ["subscriber_id"])
    op.create_index("ix_manual_payment_requests_status", "manual_payment_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_manual_payment_requests_status", table_name="manual_payment_requests")
    op.drop_index("ix_manual_payment_requests_subscriber_id", table_name="manual_payment_requests")
    op.drop_index("ix_manual_payment_requests_telegram_user_id", table_name="manual_payment_requests")
    op.drop_table("manual_payment_requests")
