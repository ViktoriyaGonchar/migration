"""Запись в audit_logs без секретов (никогда не писать сырой token)."""

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog


async def write_audit(
    db: AsyncSession,
    *,
    event_type: str,
    actor_type: str,
    actor_id: int | None = None,
    subject_type: str | None = None,
    subject_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Добавляет запись журнала; meta сериализуется в JSON (без токенов)."""
    row = AuditLog(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type=subject_type,
        subject_id=subject_id,
        meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
    )
    db.add(row)
