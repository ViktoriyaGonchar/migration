"""Попытка оплаты через провайдера (Phase 7: заглушки, без автовыдачи доступа)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUS_CREATED = "created"
STATUS_PENDING_CONFIRMATION = "pending_confirmation"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_payment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    subscriber_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscribers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Зарезервировано для связи с ручной заявкой; Phase 7 не заполняет.
    manual_payment_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("manual_payment_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
