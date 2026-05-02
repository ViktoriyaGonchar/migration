"""Добавление subscriptions.source для разметки канала выдачи (Phase 2A)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_subscription_source"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("source", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "source")
