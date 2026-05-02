"""Маршруты POST issue/reissue и GET status; только вызов access_issue и чтение подписок."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.internal.deps import verify_internal_api_key
from app.config import Settings, get_settings
from app.deps import get_db
from app.services import access_issue
from app.services import manual_payment_requests
from app.services import payment_attempts as payment_attempts_service
from app.services import telegram_linking
from app.services.subscriptions import get_active_subscription_for_subscriber
from app.util.timeutil import as_utc

router = APIRouter(
    prefix="/api/internal/v1",
    tags=["internal"],
    dependencies=[Depends(verify_internal_api_key)],
)


class AccessIssueBody(BaseModel):
    subscriber_id: int = Field(..., ge=1)
    days: int = Field(..., ge=1, le=3650)


class AccessReissueBody(BaseModel):
    subscriber_id: int = Field(..., ge=1)


class LoginUrlResponse(BaseModel):
    login_url: str


def _http_for_value_error(exc: ValueError) -> HTTPException:
    """Подписчик не найден — 404; остальные ошибки выдачи — 400."""
    msg = str(exc)
    if msg == "Подписчик не найден":
        return HTTPException(status_code=404, detail=msg)
    return HTTPException(status_code=400, detail=msg)


@router.post("/access/issue", response_model=LoginUrlResponse)
async def internal_access_issue(
    body: AccessIssueBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginUrlResponse:
    """Выдача/продление + login URL (канал telegram в audit, actor system)."""
    try:
        url = await access_issue.grant_access_for_days(
            db,
            body.subscriber_id,
            body.days,
            settings,
            channel=access_issue.CHANNEL_TELEGRAM,
            subscription_source=access_issue.CHANNEL_TELEGRAM,
            actor_type=access_issue.ACTOR_INTERNAL,
        )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise _http_for_value_error(e) from e
    except Exception:
        await db.rollback()
        raise
    return LoginUrlResponse(login_url=url)


@router.post("/access/reissue", response_model=LoginUrlResponse)
async def internal_access_reissue(
    body: AccessReissueBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginUrlResponse:
    """Новая ссылка при активной подписке."""
    try:
        url = await access_issue.reissue_login_link(
            db,
            body.subscriber_id,
            settings,
            channel=access_issue.CHANNEL_TELEGRAM,
            actor_type=access_issue.ACTOR_INTERNAL,
        )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise _http_for_value_error(e) from e
    except Exception:
        await db.rollback()
        raise
    return LoginUrlResponse(login_url=url)


class SubscriptionStatusResponse(BaseModel):
    subscriber_id: int
    active: bool
    ends_at: str | None = None


@router.get("/subscriptions/status", response_model=SubscriptionStatusResponse)
async def internal_subscription_status(
    subscriber_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionStatusResponse:
    """Активна ли подписка и дата окончания (ISO UTC)."""
    try:
        await access_issue.require_subscriber_exists(db, subscriber_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    sub = await get_active_subscription_for_subscriber(db, subscriber_id)
    if sub is None:
        return SubscriptionStatusResponse(subscriber_id=subscriber_id, active=False, ends_at=None)
    return SubscriptionStatusResponse(
        subscriber_id=subscriber_id,
        active=True,
        ends_at=as_utc(sub.ends_at).isoformat(),
    )


class TelegramLinkConsumeBody(BaseModel):
    token: str = Field(..., min_length=1)
    telegram_user_id: int = Field(..., ge=1)


class TelegramLinkConsumeResponse(BaseModel):
    subscriber_id: int


@router.post("/telegram/link/consume", response_model=TelegramLinkConsumeResponse)
async def internal_telegram_link_consume(
    body: TelegramLinkConsumeBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TelegramLinkConsumeResponse:
    """Одноразовая привязка Telegram по токену из deep link."""
    try:
        sid = await telegram_linking.consume_telegram_link(
            db,
            raw_token=body.token,
            telegram_user_id=body.telegram_user_id,
            settings=settings,
        )
        await db.commit()
    except telegram_linking.LinkInvalidError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=telegram_linking.LINK_INVALID_MESSAGE) from None
    except telegram_linking.LinkConflictError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception:
        await db.rollback()
        raise
    return TelegramLinkConsumeResponse(subscriber_id=sid)


class TelegramSubscriberResolveResponse(BaseModel):
    subscriber_id: int


@router.get("/telegram/subscriber", response_model=TelegramSubscriberResolveResponse)
async def internal_telegram_subscriber(
    telegram_user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TelegramSubscriberResolveResponse:
    """Найти subscriber_id по telegram_user_id (для бота /status и /get_link)."""
    sid = await telegram_linking.resolve_subscriber_id_by_telegram(db, telegram_user_id)
    if sid is None:
        raise HTTPException(status_code=404, detail="Привязка не найдена")
    return TelegramSubscriberResolveResponse(subscriber_id=sid)


class ManualPaymentRequestCreateBody(BaseModel):
    telegram_user_id: int = Field(..., ge=1)
    note: str | None = Field(None, max_length=2000)


class ManualPaymentRequestResponse(BaseModel):
    request_id: int
    created: bool
    subscriber_id: int | None = None


@router.post("/manual-payment-requests", response_model=ManualPaymentRequestResponse)
async def internal_create_manual_payment_request(
    body: ManualPaymentRequestCreateBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ManualPaymentRequestResponse:
    """Создать pending-заявку на ручную проверку оплаты (или вернуть существующую pending)."""
    try:
        request_id, created, sub_id = await manual_payment_requests.create_pending_manual_payment_request(
            db,
            telegram_user_id=body.telegram_user_id,
            settings=settings,
            note=body.note,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return ManualPaymentRequestResponse(
        request_id=request_id,
        created=created,
        subscriber_id=sub_id,
    )


class ManualPaymentLatestForTelegramOut(BaseModel):
    """Последняя ручная заявка для бота /pay_status (без review_note)."""

    has_request: bool
    request_id: int | None = None
    status: str | None = None
    created_at: str | None = None
    reviewed_at: str | None = None
    subscriber_id: int | None = None
    amount_label_snapshot: str | None = None


@router.get(
    "/manual-payment-requests/latest-for-telegram",
    response_model=ManualPaymentLatestForTelegramOut,
)
async def internal_latest_manual_payment_for_telegram(
    telegram_user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ManualPaymentLatestForTelegramOut:
    """Чтение: последняя заявка по telegram_user_id (Phase 8A, только для бота)."""
    row = await manual_payment_requests.get_latest_manual_payment_request_for_telegram(
        db, telegram_user_id
    )
    await db.commit()
    if row is None:
        return ManualPaymentLatestForTelegramOut(has_request=False)
    return ManualPaymentLatestForTelegramOut(
        has_request=True,
        request_id=row.id,
        status=row.status,
        created_at=as_utc(row.created_at).isoformat(),
        reviewed_at=as_utc(row.reviewed_at).isoformat() if row.reviewed_at else None,
        subscriber_id=row.subscriber_id,
        amount_label_snapshot=row.amount_label_snapshot,
    )


def _payments_sandbox_or_404(settings: Settings) -> None:
    """Mock-маршруты не раскрываем при выключенном sandbox (единое поведение — 404)."""
    if not settings.payments_sandbox_mode:
        raise HTTPException(status_code=404, detail="Not Found")


class PaymentAttemptCreateBody(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    telegram_user_id: int = Field(..., ge=1)
    amount_label: str | None = Field(None, max_length=255)
    currency: str | None = Field(None, max_length=3)


class PaymentAttemptOut(BaseModel):
    id: int
    provider: str
    provider_payment_id: str
    telegram_user_id: int
    subscriber_id: int | None = None
    amount_label: str | None = None
    currency: str
    status: str
    metadata: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.post("/payments", response_model=PaymentAttemptOut)
async def internal_create_payment_attempt(
    body: PaymentAttemptCreateBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaymentAttemptOut:
    """Создать тестовую payment_attempt (stub-провайдер). Не трогает manual_payment_requests."""
    try:
        row = await payment_attempts_service.create_payment_attempt(
            db,
            provider=body.provider.strip(),
            telegram_user_id=body.telegram_user_id,
            settings=settings,
            amount_label=body.amount_label,
            currency=body.currency,
        )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        await db.rollback()
        raise
    return PaymentAttemptOut(**payment_attempts_service.serialize_attempt(row))


@router.get("/payments", response_model=list[PaymentAttemptOut])
async def internal_list_payment_attempts(
    telegram_user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
) -> list[PaymentAttemptOut]:
    rows = await payment_attempts_service.list_payment_attempts_for_telegram(
        db, telegram_user_id=telegram_user_id, limit=limit
    )
    await db.commit()
    return [PaymentAttemptOut(**payment_attempts_service.serialize_attempt(r)) for r in rows]


@router.get("/payments/{attempt_id}", response_model=PaymentAttemptOut)
async def internal_get_payment_attempt(
    attempt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh: bool = False,
) -> PaymentAttemptOut:
    """Статус попытки; refresh=1 вызывает stub refresh_status (для заглушек обычно no-op)."""
    if refresh:
        row = await payment_attempts_service.refresh_payment_attempt_status(db, attempt_id)
    else:
        row = await payment_attempts_service.get_payment_attempt(db, attempt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Платёж не найден")
    await db.commit()
    return PaymentAttemptOut(**payment_attempts_service.serialize_attempt(row))


@router.post("/payments/{attempt_id}/mock-confirm", response_model=PaymentAttemptOut)
async def internal_mock_confirm_payment(
    attempt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaymentAttemptOut:
    _payments_sandbox_or_404(settings)
    try:
        row = await payment_attempts_service.mock_confirm_payment_attempt(
            db, attempt_id=attempt_id, admin_user_id=None
        )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PaymentAttemptOut(**payment_attempts_service.serialize_attempt(row))


@router.post("/payments/{attempt_id}/mock-fail", response_model=PaymentAttemptOut)
async def internal_mock_fail_payment(
    attempt_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaymentAttemptOut:
    _payments_sandbox_or_404(settings)
    try:
        row = await payment_attempts_service.mock_fail_payment_attempt(
            db, attempt_id=attempt_id, admin_user_id=None
        )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PaymentAttemptOut(**payment_attempts_service.serialize_attempt(row))
