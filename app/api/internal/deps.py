"""Проверка ключа internal API (заголовок X-Internal-Key)."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings


def _internal_keys_equal(provided: str, expected: str) -> bool:
    """Сравнение ключей защищённое от утечки по времени (длины должны совпадать)."""
    if not provided or not expected or len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def verify_internal_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_key: Annotated[str | None, Header(alias="X-Internal-Key")] = None,
) -> None:
    """Без настроенного ключа internal API отключён; неверный ключ — 401."""
    if not settings.internal_api_key:
        # 503: функция намеренно выключена (не путать с «не найдено»).
        raise HTTPException(status_code=503, detail="Internal API отключён")
    if x_internal_key is None or not _internal_keys_equal(x_internal_key, settings.internal_api_key):
        # Одна формулировка для отсутствующего и неверного ключа.
        raise HTTPException(status_code=401, detail="Доступ к internal API запрещён")
