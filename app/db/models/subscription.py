"""Подписка: период, в течение которого разрешён доступ к закрытому сайту."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("subscribers.id", ondelete="CASCADE"), index=True)
    # Например: active, cancelled
    status: Mapped[str] = mapped_column(String(32), default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Канал последней операции над строкой (например manual_cli); для старых строк NULL.
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    subscriber: Mapped[Subscriber] = relationship("Subscriber", back_populates="subscriptions")
