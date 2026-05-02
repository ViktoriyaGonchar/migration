"""Частичный UNIQUE: не более одной pending-заявки на telegram_user_id (защита от гонки)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_manual_payment_one_pending_per_telegram"
down_revision: Union[str, None] = "004_manual_payment_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite: один активный pending на пользователя; при гонке второй INSERT получит IntegrityError.
    op.create_index(
        "ix_manual_payment_requests_one_pending_per_telegram",
        "manual_payment_requests",
        ["telegram_user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manual_payment_requests_one_pending_per_telegram",
        table_name="manual_payment_requests",
    )
