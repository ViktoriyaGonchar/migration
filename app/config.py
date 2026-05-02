"""Настройки приложения из переменных окружения."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Корень статического сайта (index.html, assets/)
    site_root: Path = Path(".")
    database_url: str = "sqlite+aiosqlite:///./app.db"
    # Общий «перец» для SHA-256 хэшей login/session токенов (не логировать).
    token_pepper: str = "CHANGE_ME_IN_PRODUCTION"
    # Отдельный секрет только для cookie Starlette у SQLAdmin (/admin).
    admin_session_secret: str = "CHANGE_ME_ADMIN_SESSION"
    # Если true — cookie пользователя с флагом Secure (нужен HTTPS).
    cookie_secure: bool = False
    user_session_cookie_name: str = "mc_user_session"
    # Имя cookie сессии Starlette для админки (namespace отдельно от пользователя).
    admin_session_cookie_name: str = "mc_admin_session"
    base_url: str = "http://127.0.0.1:8000"
    # Phase 2B: ключ для internal API (пусто — маршруты /api/internal/* отвечают 503).
    internal_api_key: str = ""
    # Phase 9: порог (часы) для предупреждения о «зависшей» oldest pending на странице очереди.
    stale_pending_alert_hours: int = Field(default=48, ge=1, le=168, validation_alias="STALE_PENDING_ALERT_HOURS")
    # Phase 3: username бота без @ (для deep link в CLI issue-telegram-link).
    bot_username: str = ""
    # Phase 5: тот же ключ PAYMENT_AMOUNT_LABEL, что у бота (/pay), при общем .env.
    payment_amount_label: str = Field(default="", validation_alias="PAYMENT_AMOUNT_LABEL")
    # Phase 7: заглушки провайдеров (без реальных ключей).
    payments_stubs_enabled: bool = Field(default=False, validation_alias="PAYMENTS_STUBS_ENABLED")
    payments_sandbox_mode: bool = Field(default=False, validation_alias="PAYMENTS_SANDBOX_MODE")
    payments_mock_ui: bool = Field(default=False, validation_alias="PAYMENTS_MOCK_UI")
    payments_callback_base_url: str = Field(default="", validation_alias="PAYMENTS_CALLBACK_BASE_URL")
    # Плейсхолдеры на будущее (не обязательны).
    yookassa_shop_id: str = Field(default="", validation_alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: str = Field(default="", validation_alias="YOOKASSA_SECRET_KEY")

    @field_validator("bot_username", mode="before")
    @classmethod
    def normalize_bot_username(cls, value: object) -> str:
        """Убираем ведущий @ из BOT_USERNAME."""
        if value is None:
            return ""
        s = str(value).strip()
        if s.startswith("@"):
            return s[1:].strip()
        return s

    @field_validator("internal_api_key", mode="before")
    @classmethod
    def strip_internal_api_key(cls, value: object) -> str:
        """Убираем пробелы/переносы из .env, чтобы сравнение ключа было предсказуемым."""
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("payment_amount_label", mode="before")
    @classmethod
    def strip_payment_amount_label(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


def get_settings() -> Settings:
    return Settings()
