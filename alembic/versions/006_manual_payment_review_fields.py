"""Phase 6: заметка оператора и кто проверил заявку (без автовыдачи доступа)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_manual_payment_review_fields"
down_revision: Union[str, None] = "005_manual_payment_one_pending_per_telegram"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_review_admin_fk(insp, table: str) -> bool:
    """SQLite может не отдавать имя FK; достаточно пары колонка → admin_users."""
    for fk in insp.get_foreign_keys(table):
        cols = fk.get("constrained_columns") or []
        if fk.get("referred_table") == "admin_users" and "reviewed_by_admin_id" in cols:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    col_names = {c["name"] for c in insp.get_columns("manual_payment_requests")}
    ix_names = {ix["name"] for ix in insp.get_indexes("manual_payment_requests")}
    has_rba_col = "reviewed_by_admin_id" in col_names
    need_fk = not _has_review_admin_fk(insp, "manual_payment_requests")
    need_ix = "ix_manual_payment_requests_reviewed_by_admin_id" not in ix_names

    # SQLite batch: два шага — иначе topological sort даёт CircularDependencyError на параллельных add_column.
    if "review_note" not in col_names:
        with op.batch_alter_table("manual_payment_requests") as batch_op:
            batch_op.add_column(sa.Column("review_note", sa.Text(), nullable=True))

    if not has_rba_col:
        with op.batch_alter_table("manual_payment_requests") as batch_op:
            batch_op.add_column(sa.Column("reviewed_by_admin_id", sa.Integer(), nullable=True))
            if need_fk:
                # ON DELETE SET NULL: при удалении admin_users reviewed_by_admin_id обнуляется (при включённых FK в SQLite).
                batch_op.create_foreign_key(
                    "fk_manual_payment_requests_reviewed_by_admin",
                    "admin_users",
                    ["reviewed_by_admin_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if need_ix:
                batch_op.create_index(
                    "ix_manual_payment_requests_reviewed_by_admin_id",
                    ["reviewed_by_admin_id"],
                )
    elif need_fk or need_ix:
        # Колонка уже есть (например сбой после первого batch), а FK/индекс нет — дорисовываем без duplicate column.
        with op.batch_alter_table("manual_payment_requests") as batch_op:
            if need_fk:
                batch_op.create_foreign_key(
                    "fk_manual_payment_requests_reviewed_by_admin",
                    "admin_users",
                    ["reviewed_by_admin_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if need_ix:
                batch_op.create_index(
                    "ix_manual_payment_requests_reviewed_by_admin_id",
                    ["reviewed_by_admin_id"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    col_names = {c["name"] for c in insp.get_columns("manual_payment_requests")}
    if "reviewed_by_admin_id" in col_names:
        ix_names = {ix["name"] for ix in insp.get_indexes("manual_payment_requests")}
        with op.batch_alter_table("manual_payment_requests") as batch_op:
            if "ix_manual_payment_requests_reviewed_by_admin_id" in ix_names:
                batch_op.drop_index("ix_manual_payment_requests_reviewed_by_admin_id")
            if _has_review_admin_fk(insp, "manual_payment_requests"):
                batch_op.drop_constraint("fk_manual_payment_requests_reviewed_by_admin", type_="foreignkey")
            batch_op.drop_column("reviewed_by_admin_id")
    if "review_note" in col_names:
        with op.batch_alter_table("manual_payment_requests") as batch_op:
            batch_op.drop_column("review_note")
