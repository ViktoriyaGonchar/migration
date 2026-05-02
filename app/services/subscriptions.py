"""Проверка активной подписки у подписчика."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.subscription import Subscription
from app.util.timeutil import as_utc


async def get_active_subscription_for_subscriber(
    db: AsyncSession,
    subscriber_id: int,
) -> Subscription | None:
    """Активная подписка: status=active, текущее время в [starts_at, ends_at). Даты из БД приводим к UTC."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Subscription)
        .where(Subscription.subscriber_id == subscriber_id)
        .where(Subscription.status == "active")
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    best: Subscription | None = None
    for sub in candidates:
        if as_utc(sub.starts_at) <= now < as_utc(sub.ends_at):
            if best is None or as_utc(sub.ends_at) > as_utc(best.ends_at):
                best = sub
    return best
