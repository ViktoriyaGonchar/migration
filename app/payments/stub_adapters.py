"""
Заглушки провайдеров: без HTTP, только синтетические id и текст для UX.
"""

from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.db.models.payment_attempt import (
    PaymentAttempt,
    STATUS_PENDING_CONFIRMATION,
)

if TYPE_CHECKING:
    pass


class StubPaymentAdapter:
    """Базовый stub: после flush у строки есть id — строим provider_payment_id."""

    key: str

    def apply_on_create(self, row: PaymentAttempt, settings: Settings) -> None:
        """Заполняет provider_payment_id, metadata_json, статус pending_confirmation."""
        suffix = secrets.token_hex(4)
        row.provider_payment_id = f"stub_{self.key}_{row.id}_{suffix}"
        row.status = STATUS_PENDING_CONFIRMATION
        row.metadata_json = json.dumps(self._metadata(row, settings), ensure_ascii=False)

    def _metadata(self, row: PaymentAttempt, settings: Settings) -> dict[str, Any]:
        # Фиксированная форма для парсеров: schema_version + display_lines + stub.
        return {
            "schema_version": 1,
            "stub": True,
            "display_lines": [
                f"Провайдер: {self.key} (тестовая заглушка).",
                "Доступ автоматически не выдаётся.",
                f"Сумма/подпись: {row.amount_label or '—'}",
            ],
        }

    def refresh_status(self, row: PaymentAttempt) -> None:
        """У заглушек нет внешнего источника правды — статус не меняется сам."""
        return


class ManualCardStubAdapter(StubPaymentAdapter):
    key = "manual_card"

    def _metadata(self, row: PaymentAttempt, settings: Settings) -> dict[str, Any]:
        base = super()._metadata(row, settings)
        base["display_lines"].insert(
            1,
            "Реальная оплата картой — команда /pay (очередь оператора), это только тест домена.",
        )
        return base


class TelegramStubAdapter(StubPaymentAdapter):
    key = "telegram_stub"

    def _metadata(self, row: PaymentAttempt, settings: Settings) -> dict[str, Any]:
        base = super()._metadata(row, settings)
        base["display_lines"].insert(1, "Имитация Telegram Payments — без реального invoice.")
        return base


class YooKassaStubAdapter(StubPaymentAdapter):
    key = "yookassa_stub"

    def _metadata(self, row: PaymentAttempt, settings: Settings) -> dict[str, Any]:
        base = super()._metadata(row, settings)
        base["display_lines"].insert(1, "Имитация ЮKassa — без API.")
        cb = (settings.payments_callback_base_url or settings.base_url or "").rstrip("/")
        if cb:
            base["display_lines"].append(f"Callback base (заглушка): {cb}")
        return base


class WiseStubAdapter(StubPaymentAdapter):
    key = "wise_stub"

    def _metadata(self, row: PaymentAttempt, settings: Settings) -> dict[str, Any]:
        base = super()._metadata(row, settings)
        base["display_lines"].insert(1, "Имитация Wise — без API.")
        return base


class PayoneerStubAdapter(StubPaymentAdapter):
    key = "payoneer_stub"

    def _metadata(self, row: PaymentAttempt, settings: Settings) -> dict[str, Any]:
        base = super()._metadata(row, settings)
        base["display_lines"].insert(1, "Имитация Payoneer — без API.")
        return base


ADAPTER_BY_PROVIDER: dict[str, StubPaymentAdapter] = {
    ManualCardStubAdapter.key: ManualCardStubAdapter(),
    TelegramStubAdapter.key: TelegramStubAdapter(),
    YooKassaStubAdapter.key: YooKassaStubAdapter(),
    WiseStubAdapter.key: WiseStubAdapter(),
    PayoneerStubAdapter.key: PayoneerStubAdapter(),
}


def canonical_provider(provider: str) -> str:
    """Нормализованный ключ провайдера (без мусора в БД); иначе ValueError с подсказкой."""
    p = (provider or "").strip().lower()
    if not p or p not in ADAPTER_BY_PROVIDER:
        allowed = ", ".join(sorted(ADAPTER_BY_PROVIDER.keys()))
        raise ValueError(f"Неизвестный провайдер. Допустимые ключи: {allowed}")
    return p


def get_adapter(provider: str) -> StubPaymentAdapter:
    """Ожидает уже канонический ключ (см. canonical_provider)."""
    a = ADAPTER_BY_PROVIDER.get(provider)
    if a is None:
        raise KeyError(provider)
    return a


def known_providers() -> tuple[str, ...]:
    return tuple(ADAPTER_BY_PROVIDER.keys())
