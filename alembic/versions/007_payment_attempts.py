"""Phase 7: payment_attempts — домен заглушек провайдеров (без реальных API)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_payment_attempts"
down_revision: Union[str, None] = "006_manual_payment_review_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("subscriber_id", sa.Integer(), nullable=True),
        sa.Column("amount_label", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("manual_payment_request_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["manual_payment_request_id"], ["manual_payment_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subscriber_id"], ["subscribers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_attempts_provider", "payment_attempts", ["provider"])
    op.create_index("ix_payment_attempts_telegram_user_id", "payment_attempts", ["telegram_user_id"])
    op.create_index("ix_payment_attempts_subscriber_id", "payment_attempts", ["subscriber_id"])
    op.create_index("ix_payment_attempts_status", "payment_attempts", ["status"])
    op.create_index(
        "ix_payment_attempts_manual_payment_request_id",
        "payment_attempts",
        ["manual_payment_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_attempts_manual_payment_request_id", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_status", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_subscriber_id", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_telegram_user_id", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_provider", table_name="payment_attempts")
    op.drop_table("payment_attempts")
