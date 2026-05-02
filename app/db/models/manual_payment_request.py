"""Заявка на ручную проверку оплаты переводом на карту (Phase 5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Статусы очереди; approve/reject не выдают доступ автоматически.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class ManualPaymentRequest(Base):
    __tablename__ = "manual_payment_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    subscriber_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscribers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Кто пометил заявку в админке (Phase 6); при удалении admin_users — NULL.
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Заметка оператора при approve/reject (Phase 6).
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # MVP: может содержать короткий комментарий от плательщика при отправке заявки.
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
