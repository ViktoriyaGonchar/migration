"""Настройки процесса бота из переменных окружения."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger(__name__)


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Пустые значения допустимы в .env при запуске только app; перед polling проверяет bot/main.py.
    bot_token: str = Field(default="", validation_alias="BOT_TOKEN")
    internal_api_key: str = Field(default="", validation_alias="INTERNAL_API_KEY")
    internal_api_base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias="INTERNAL_API_BASE_URL",
    )

    # Phase 5: реквизиты и уведомления (только отображение в боте).
    payment_card_number: str = Field(default="", validation_alias="PAYMENT_CARD_NUMBER")
    payment_recipient_name: str = Field(default="", validation_alias="PAYMENT_RECIPIENT_NAME")
    payment_bank_name: str = Field(default="", validation_alias="PAYMENT_BANK_NAME")
    payment_amount_label: str = Field(default="", validation_alias="PAYMENT_AMOUNT_LABEL")
    admin_notify_telegram_ids: list[int] = Field(
        default_factory=list,
        validation_alias="ADMIN_NOTIFY_TELEGRAM_IDS",
    )
    # Phase 7: показ /pay_methods (stub-провайдеры); не трогает /pay.
    payments_stubs_enabled: bool = Field(default=False, validation_alias="PAYMENTS_STUBS_ENABLED")

    @field_validator("bot_token", "internal_api_key", mode="before")
    @classmethod
    def strip_bot_secrets(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("internal_api_base_url", mode="before")
    @classmethod
    def strip_base_url(cls, value: object) -> str:
        if value is None:
            return "http://127.0.0.1:8000"
        s = str(value).strip().rstrip("/")
        return s if s else "http://127.0.0.1:8000"

    @field_validator("admin_notify_telegram_ids", mode="before")
    @classmethod
    def parse_admin_notify_ids(cls, value: Any) -> list[int]:
        """Список chat_id через запятую или пусто; битые фрагменты пропускаем (бот не падает)."""
        if value is None or value == "":
            return []
        if isinstance(value, list):
            out: list[int] = []
            for x in value:
                try:
                    out.append(int(x))
                except (TypeError, ValueError):
                    _log.warning("ADMIN_NOTIFY_TELEGRAM_IDS: пропуск элемента %r", x)
            return out
        s = str(value).strip()
        if not s:
            return []
        out = []
        for part in s.split(","):
            p = part.strip()
            if not p:
                continue
            try:
                out.append(int(p))
            except ValueError:
                _log.warning("ADMIN_NOTIFY_TELEGRAM_IDS: пропуск нечислового фрагмента %r", p)
        return out


def get_bot_settings() -> BotSettings:
    return BotSettings()
