"""SQLite/async возвращают часто naive datetime — приводим к UTC для сравнений."""

from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    """Если naive — считаем UTC; иначе приводим к UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
