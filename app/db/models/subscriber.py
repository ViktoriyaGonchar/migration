"""Подписчик — внутренний субъект доступа (без привязки к Telegram в first pass)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Внутренняя метка для админов (не ПДн); можно оставить пустой.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    subscriptions: Mapped[list[Subscription]] = relationship("Subscription", back_populates="subscriber")
    login_tokens: Mapped[list[LoginToken]] = relationship("LoginToken", back_populates="subscriber")
    web_sessions: Mapped[list[WebSession]] = relationship("WebSession", back_populates="subscriber")
