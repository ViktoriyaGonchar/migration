"""
Создание заявок на ручную проверку оплаты переводом на карту.
Не выдаёт доступ и не подтверждает платёж автоматически.
Phase 6: approve/reject из админки — только статус и аудит, без подписки.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.manual_payment_request import (
    ManualPaymentRequest,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from app.services import audit as audit_service
from app.services.access_issue import (
    ACTOR_ADMIN,
    ACTOR_INTERNAL,
    CHANNEL_ADMIN_UI,
    CHANNEL_TELEGRAM,
)
from app.services import telegram_linking

# Лимит текста заметки в теле формы и в meta audit (обрезка для JSON).
_REVIEW_NOTE_MAX_LEN = 2000
_META_REVIEW_NOTE_MAX = 400

# Phase 8A: список в админке и CSV (без лишней нагрузки на SQLite).
QUEUE_PAGE_LIMIT_DEFAULT = 500
QUEUE_CSV_EXPORT_LIMIT = 2000

# Phase 9: скользящее окно для операционных счётчиков на сводке (строго 24 часа, UTC).
ROLLING_WINDOW_HOURS = 24

# Допустимые значения фильтра status на странице очереди.
QUEUE_STATUS_PENDING = "pending"
QUEUE_STATUS_APPROVED = "approved"
QUEUE_STATUS_REJECTED = "rejected"
QUEUE_STATUS_ALL = "all"


@dataclass(frozen=True)
class ManualPaymentQueueSummary:
    """Сводка для блока в /admin/payment-requests (Phase 8A + Phase 9)."""

    pending_count: int
    oldest_pending_created_at: datetime | None
    # Phase 9: pending с created_at старше порога (UTC).
    pending_older_than_24h: int
    pending_older_than_48h: int
    pending_older_than_72h: int
    # За последние 24 часа (скользящее окно от now UTC).
    created_rolling_24h: int
    approved_rolling_24h: int
    rejected_rolling_24h: int


async def _pending_for_telegram(
    db: AsyncSession,
    telegram_user_id: int,
) -> ManualPaymentRequest | None:
    r = await db.execute(
        select(ManualPaymentRequest).where(
            ManualPaymentRequest.telegram_user_id == telegram_user_id,
            ManualPaymentRequest.status == STATUS_PENDING,
        )
    )
    return r.scalar_one_or_none()


async def create_pending_manual_payment_request(
    db: AsyncSession,
    *,
    telegram_user_id: int,
    settings: Settings,
    note: str | None = None,
) -> tuple[int, bool, int | None]:
    """
    Создаёт заявку со статусом pending или возвращает существующую pending по тому же telegram_user_id.
    Возвращает (request_id, created, subscriber_id): created=False если заявка уже была в очереди.
    """
    # Несколько попыток: при гонке UNIQUE после rollback конкурент мог ещё не закоммитить — повторяем чтение.
    for _ in range(5):
        existing = await _pending_for_telegram(db, telegram_user_id)
        if existing is not None:
            return existing.id, False, existing.subscriber_id

        subscriber_id = await telegram_linking.resolve_subscriber_id_by_telegram(db, telegram_user_id)
        # Должно совпадать с PAYMENT_AMOUNT_LABEL в процессе бота (/pay), если общий .env.
        snapshot = (settings.payment_amount_label or "").strip() or None
        note_clean = (note or "").strip() or None
        if note_clean and len(note_clean) > 2000:
            note_clean = note_clean[:2000]

        row = ManualPaymentRequest(
            telegram_user_id=telegram_user_id,
            subscriber_id=subscriber_id,
            status=STATUS_PENDING,
            operator_note=note_clean,
            amount_label_snapshot=snapshot,
        )
        try:
            db.add(row)
            await db.flush()
            await audit_service.write_audit(
                db,
                event_type="manual_payment_request_created",
                actor_type=ACTOR_INTERNAL,
                subject_type="manual_payment_request",
                subject_id=row.id,
                meta={
                    "channel": CHANNEL_TELEGRAM,
                    "telegram_user_id": telegram_user_id,
                    "subscriber_id": subscriber_id,
                    "request_id": row.id,
                },
            )
        except IntegrityError:
            await db.rollback()
            continue

        return row.id, True, subscriber_id

    raise RuntimeError("Не удалось создать заявку: повторите запрос позже")


def _normalize_review_note(note: str | None) -> str | None:
    """Обрезка пробелов и длины для review_note."""
    s = (note or "").strip()
    if not s:
        return None
    if len(s) > _REVIEW_NOTE_MAX_LEN:
        return s[:_REVIEW_NOTE_MAX_LEN]
    return s


def _review_note_for_meta(note: str | None) -> str | None:
    """Укороченная копия для audit meta."""
    if note is None:
        return None
    if len(note) <= _META_REVIEW_NOTE_MAX:
        return note
    return note[:_META_REVIEW_NOTE_MAX] + "..."


async def approve_manual_payment_request(
    db: AsyncSession,
    *,
    request_id: int,
    admin_user_id: int,
    review_note: str | None = None,
) -> ManualPaymentRequest:
    """Перевод pending → approved; меняет только поля review заявки (без подписки и выдачи доступа)."""
    row = await db.get(ManualPaymentRequest, request_id)
    if row is None:
        raise ValueError("Заявка не найдена")
    if row.status != STATUS_PENDING:
        raise ValueError("Заявка уже обработана")

    note_clean = _normalize_review_note(review_note)
    row.status = STATUS_APPROVED
    row.reviewed_at = datetime.now(timezone.utc)
    row.reviewed_by_admin_id = admin_user_id
    row.review_note = note_clean
    await db.flush()

    await audit_service.write_audit(
        db,
        event_type="manual_payment_request_approved",
        actor_type=ACTOR_ADMIN,
        actor_id=admin_user_id,
        subject_type="manual_payment_request",
        subject_id=row.id,
        meta={
            "channel": CHANNEL_ADMIN_UI,
            "request_id": row.id,
            "telegram_user_id": row.telegram_user_id,
            "subscriber_id": row.subscriber_id,
            "admin_user_id": admin_user_id,
            "review_note": _review_note_for_meta(note_clean),
        },
    )
    return row


async def reject_manual_payment_request(
    db: AsyncSession,
    *,
    request_id: int,
    admin_user_id: int,
    review_note: str | None = None,
) -> ManualPaymentRequest:
    """Перевод pending → rejected; только поля review заявки, без подписки."""
    row = await db.get(ManualPaymentRequest, request_id)
    if row is None:
        raise ValueError("Заявка не найдена")
    if row.status != STATUS_PENDING:
        raise ValueError("Заявка уже обработана")

    note_clean = _normalize_review_note(review_note)
    row.status = STATUS_REJECTED
    row.reviewed_at = datetime.now(timezone.utc)
    row.reviewed_by_admin_id = admin_user_id
    row.review_note = note_clean
    await db.flush()

    await audit_service.write_audit(
        db,
        event_type="manual_payment_request_rejected",
        actor_type=ACTOR_ADMIN,
        actor_id=admin_user_id,
        subject_type="manual_payment_request",
        subject_id=row.id,
        meta={
            "channel": CHANNEL_ADMIN_UI,
            "request_id": row.id,
            "telegram_user_id": row.telegram_user_id,
            "subscriber_id": row.subscriber_id,
            "admin_user_id": admin_user_id,
            "review_note": _review_note_for_meta(note_clean),
        },
    )
    return row


def normalize_queue_status_filter(status_raw: str | None) -> str:
    """Нормализация фильтра status; по умолчанию pending."""
    s = (status_raw or "").strip().lower()
    if s in (QUEUE_STATUS_APPROVED, QUEUE_STATUS_REJECTED, QUEUE_STATUS_ALL):
        return s
    return QUEUE_STATUS_PENDING


def parse_queue_sort_desc(sort_raw: str | None) -> bool:
    """True = новые сверху (desc), False = старые сверху (asc)."""
    s = (sort_raw or "").strip().lower()
    if s in ("asc", "old"):
        return False
    return True


def parse_queue_search_int(q_raw: str | None) -> int | None:
    """Поиск только по числу: id / subscriber_id / telegram_user_id."""
    if q_raw is None:
        return None
    s = str(q_raw).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


async def manual_payment_queue_summary(db: AsyncSession) -> ManualPaymentQueueSummary:
    """Сводка очереди: pending, возрастные корзины, скользящие 24ч счётчики (всё в UTC)."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=ROLLING_WINDOW_HOURS)
    t24 = now - timedelta(hours=24)
    t48 = now - timedelta(hours=48)
    t72 = now - timedelta(hours=72)

    r_pending_n = await db.execute(
        select(func.count()).select_from(ManualPaymentRequest).where(
            ManualPaymentRequest.status == STATUS_PENDING
        )
    )
    pending_count = int(r_pending_n.scalar_one() or 0)

    def _pending_older_than(cutoff: datetime):
        return select(func.count()).select_from(ManualPaymentRequest).where(
            ManualPaymentRequest.status == STATUS_PENDING,
            ManualPaymentRequest.created_at < cutoff,
        )

    p24 = int((await db.execute(_pending_older_than(t24))).scalar_one() or 0)
    p48 = int((await db.execute(_pending_older_than(t48))).scalar_one() or 0)
    p72 = int((await db.execute(_pending_older_than(t72))).scalar_one() or 0)

    r_created_24 = await db.execute(
        select(func.count()).select_from(ManualPaymentRequest).where(
            ManualPaymentRequest.created_at >= since_24h,
        )
    )
    created_rolling_24h = int(r_created_24.scalar_one() or 0)

    r_appr_24 = await db.execute(
        select(func.count()).select_from(ManualPaymentRequest).where(
            ManualPaymentRequest.status == STATUS_APPROVED,
            ManualPaymentRequest.reviewed_at.is_not(None),
            ManualPaymentRequest.reviewed_at >= since_24h,
        )
    )
    approved_rolling_24h = int(r_appr_24.scalar_one() or 0)

    r_rej_24 = await db.execute(
        select(func.count()).select_from(ManualPaymentRequest).where(
            ManualPaymentRequest.status == STATUS_REJECTED,
            ManualPaymentRequest.reviewed_at.is_not(None),
            ManualPaymentRequest.reviewed_at >= since_24h,
        )
    )
    rejected_rolling_24h = int(r_rej_24.scalar_one() or 0)

    r_old = await db.execute(
        select(func.min(ManualPaymentRequest.created_at)).where(
            ManualPaymentRequest.status == STATUS_PENDING
        )
    )
    oldest = r_old.scalar_one_or_none()

    return ManualPaymentQueueSummary(
        pending_count=pending_count,
        oldest_pending_created_at=oldest,
        pending_older_than_24h=p24,
        pending_older_than_48h=p48,
        pending_older_than_72h=p72,
        created_rolling_24h=created_rolling_24h,
        approved_rolling_24h=approved_rolling_24h,
        rejected_rolling_24h=rejected_rolling_24h,
    )


async def list_manual_payment_requests_filtered(
    db: AsyncSession,
    *,
    status: str,
    q_int: int | None,
    sort_desc: bool,
    limit: int,
) -> list[ManualPaymentRequest]:
    """Список заявок для админки: фильтр статуса, числовой поиск OR по id/subscriber/telegram, сортировка."""
    st = normalize_queue_status_filter(status)
    lim = max(1, min(limit, QUEUE_CSV_EXPORT_LIMIT))

    stmt = select(ManualPaymentRequest)
    if st != QUEUE_STATUS_ALL:
        stmt = stmt.where(ManualPaymentRequest.status == st)
    if q_int is not None:
        stmt = stmt.where(
            or_(
                ManualPaymentRequest.id == q_int,
                ManualPaymentRequest.subscriber_id == q_int,
                ManualPaymentRequest.telegram_user_id == q_int,
            )
        )
    if sort_desc:
        stmt = stmt.order_by(ManualPaymentRequest.created_at.desc())
    else:
        stmt = stmt.order_by(ManualPaymentRequest.created_at.asc())
    stmt = stmt.limit(lim)

    r = await db.execute(stmt)
    return list(r.scalars().all())


async def get_latest_manual_payment_request_for_telegram(
    db: AsyncSession,
    telegram_user_id: int,
) -> ManualPaymentRequest | None:
    """Последняя заявка по дате создания для пользователя Telegram (для /pay_status)."""
    r = await db.execute(
        select(ManualPaymentRequest)
        .where(ManualPaymentRequest.telegram_user_id == telegram_user_id)
        .order_by(ManualPaymentRequest.created_at.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def get_latest_pending_manual_payment_request_for_subscriber(
    db: AsyncSession,
    subscriber_id: int,
) -> ManualPaymentRequest | None:
    """Текущая pending по подписчику (если несколько — не должно быть по правилам Phase 5, берём новую)."""
    r = await db.execute(
        select(ManualPaymentRequest)
        .where(
            ManualPaymentRequest.subscriber_id == subscriber_id,
            ManualPaymentRequest.status == STATUS_PENDING,
        )
        .order_by(ManualPaymentRequest.created_at.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def list_recent_manual_payment_requests_for_subscriber(
    db: AsyncSession,
    subscriber_id: int,
    *,
    limit: int = 10,
) -> list[ManualPaymentRequest]:
    """Последние заявки по subscriber_id для карточки оператора."""
    lim = max(1, min(limit, 50))
    r = await db.execute(
        select(ManualPaymentRequest)
        .where(ManualPaymentRequest.subscriber_id == subscriber_id)
        .order_by(ManualPaymentRequest.created_at.desc())
        .limit(lim)
    )
    return list(r.scalars().all())


async def list_pending_manual_payment_requests(
    db: AsyncSession,
) -> list[ManualPaymentRequest]:
    """Очередь pending (совместимость Phase 6); лимит как у страницы админки."""
    return await list_manual_payment_requests_filtered(
        db,
        status=QUEUE_STATUS_PENDING,
        q_int=None,
        sort_desc=True,
        limit=QUEUE_PAGE_LIMIT_DEFAULT,
    )
