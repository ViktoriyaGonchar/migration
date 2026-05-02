"""
Создание и смена статуса payment_attempts (Phase 7). Не вызывает access_issue.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.payment_attempt import (
    PaymentAttempt,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_PENDING_CONFIRMATION,
    STATUS_SUCCEEDED,
)
from app.payments.stub_adapters import canonical_provider, get_adapter
from app.services import audit as audit_service
from app.services.access_issue import ACTOR_ADMIN, ACTOR_INTERNAL, CHANNEL_ADMIN_UI, CHANNEL_TELEGRAM
from app.services import telegram_linking

# Mock только из черновика/ожидания; succeeded/failed/cancelled не трогаем.
_MOCK_ALLOWED_FROM = frozenset({STATUS_CREATED, STATUS_PENDING_CONFIRMATION})


def _parse_metadata(row: PaymentAttempt) -> dict[str, Any] | None:
    if not row.metadata_json:
        return None
    try:
        return json.loads(row.metadata_json)
    except json.JSONDecodeError:
        return None


async def create_payment_attempt(
    db: AsyncSession,
    *,
    provider: str,
    telegram_user_id: int,
    settings: Settings,
    amount_label: str | None = None,
    currency: str | None = None,
) -> PaymentAttempt:
    """Новая попытка: resolve subscriber, строка created, затем stub adapter."""
    provider = canonical_provider(provider)

    subscriber_id = await telegram_linking.resolve_subscriber_id_by_telegram(db, telegram_user_id)
    cur = (currency or "RUB").strip().upper()[:3] or "RUB"
    label = (amount_label or settings.payment_amount_label or "").strip() or None

    row = PaymentAttempt(
        provider=provider,
        provider_payment_id="",  # заполнит adapter после flush
        telegram_user_id=telegram_user_id,
        subscriber_id=subscriber_id,
        amount_label=label,
        currency=cur,
        status=STATUS_CREATED,
        metadata_json=None,
    )
    db.add(row)
    await db.flush()

    adapter = get_adapter(provider)
    adapter.apply_on_create(row, settings)
    await db.flush()

    await audit_service.write_audit(
        db,
        event_type="payment_attempt_created",
        actor_type=ACTOR_INTERNAL,
        subject_type="payment_attempt",
        subject_id=row.id,
        meta={
            "channel": CHANNEL_TELEGRAM,
            "provider": provider,
            "telegram_user_id": telegram_user_id,
            "subscriber_id": subscriber_id,
            "payment_attempt_id": row.id,
            "status": row.status,
        },
    )
    return row


async def get_payment_attempt(db: AsyncSession, attempt_id: int) -> PaymentAttempt | None:
    return await db.get(PaymentAttempt, attempt_id)


async def list_payment_attempts_for_telegram(
    db: AsyncSession,
    *,
    telegram_user_id: int,
    limit: int = 20,
) -> list[PaymentAttempt]:
    lim = max(1, min(limit, 50))
    r = await db.execute(
        select(PaymentAttempt)
        .where(PaymentAttempt.telegram_user_id == telegram_user_id)
        .order_by(PaymentAttempt.created_at.desc())
        .limit(lim)
    )
    return list(r.scalars().all())


async def refresh_payment_attempt_status(db: AsyncSession, attempt_id: int) -> PaymentAttempt | None:
    row = await db.get(PaymentAttempt, attempt_id)
    if row is None:
        return None
    adapter = get_adapter(row.provider)
    adapter.refresh_status(row)
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def mock_confirm_payment_attempt(
    db: AsyncSession,
    *,
    attempt_id: int,
    admin_user_id: int | None,
) -> PaymentAttempt:
    """Перевод в succeeded (только при PAYMENTS_SANDBOX_MODE на маршруте)."""
    row = await db.get(PaymentAttempt, attempt_id)
    if row is None:
        raise ValueError("Платёж не найден")
    if row.status not in _MOCK_ALLOWED_FROM:
        raise ValueError(
            f"Mock-confirm только из статусов «created» или «pending_confirmation». Сейчас: {row.status}"
        )

    prev = row.status
    row.status = STATUS_SUCCEEDED
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()

    actor = ACTOR_ADMIN if admin_user_id is not None else ACTOR_INTERNAL
    await audit_service.write_audit(
        db,
        event_type="payment_attempt_mock_confirmed",
        actor_type=actor,
        actor_id=admin_user_id,
        subject_type="payment_attempt",
        subject_id=row.id,
        meta={
            "channel": CHANNEL_ADMIN_UI if admin_user_id else CHANNEL_TELEGRAM,
            "payment_attempt_id": row.id,
            "provider": row.provider,
            "admin_user_id": admin_user_id,
            "previous_status": prev,
        },
    )
    return row


async def mock_fail_payment_attempt(
    db: AsyncSession,
    *,
    attempt_id: int,
    admin_user_id: int | None,
) -> PaymentAttempt:
    row = await db.get(PaymentAttempt, attempt_id)
    if row is None:
        raise ValueError("Платёж не найден")
    if row.status not in _MOCK_ALLOWED_FROM:
        raise ValueError(
            f"Mock-fail только из статусов «created» или «pending_confirmation». Сейчас: {row.status}"
        )

    prev = row.status
    row.status = STATUS_FAILED
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()

    actor = ACTOR_ADMIN if admin_user_id is not None else ACTOR_INTERNAL
    await audit_service.write_audit(
        db,
        event_type="payment_attempt_mock_failed",
        actor_type=actor,
        actor_id=admin_user_id,
        subject_type="payment_attempt",
        subject_id=row.id,
        meta={
            "channel": CHANNEL_ADMIN_UI if admin_user_id else CHANNEL_TELEGRAM,
            "payment_attempt_id": row.id,
            "provider": row.provider,
            "admin_user_id": admin_user_id,
            "previous_status": prev,
        },
    )
    return row


def serialize_attempt(row: PaymentAttempt) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "provider_payment_id": row.provider_payment_id,
        "telegram_user_id": row.telegram_user_id,
        "subscriber_id": row.subscriber_id,
        "amount_label": row.amount_label,
        "currency": row.currency,
        "status": row.status,
        "metadata": _parse_metadata(row),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
