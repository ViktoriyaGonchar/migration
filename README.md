# Migration Compass — backend, бот и закрытый сайт

Репозиторий объединяет статический лендинг (корень `SITE_ROOT`), **FastAPI** с async **SQLAlchemy** и **SQLite**, **SQLAdmin**, **Telegram-бота** (aiogram + httpx) и **Typer CLI**. Основной платёжный контур — **ручные заявки на оплату** (модерация в админке). Домен **payment_attempts** — заглушка провайдеров; не смешивать с ручным потоком.

**Полные инструкции:** [TESTING.md](TESTING.md) · [DEPLOY.md](DEPLOY.md) · [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md)

## Ключевые контуры

| Контур | Назначение |
|--------|------------|
| Публичный сайт | Статика + gated `/` после входа по ссылке с токеном |
| SQLAdmin `/admin` | Очередь ручных заявок, approve/reject (**не** выдача доступа), операторские grant/reissue |
| Бот | `/pay`, статус ручной заявки (`/pay_status`), при stub — отдельно `/payment_status`; уведомления админам |
| Internal API `/api/internal/*` | Ключ `X-Internal-Key`; пустой ключ → ответы 503 на internal |
| CLI `mc-cli` | Подписчики, подписки, login-ссылки, привязка Telegram, создание admin |

## Быстрый локальный старт

1. Python **≥ 3.11**, виртуальное окружение.
2. Скопировать [`.env.example`](.env.example) в `.env`, заполнить минимум: `TOKEN_PEPPER`, `ADMIN_SESSION_SECRET`, при работе с ботом — `BOT_TOKEN`, `INTERNAL_API_KEY`, `INTERNAL_API_BASE_URL`, `BOT_USERNAME` (см. комментарии в `.env.example` и [`app/config.py`](app/config.py)).
3. Установка пакета: `pip install -e .` (или эквивалент из вашего workflow).
4. Миграции: `alembic upgrade head`.
5. Первый админ (если ещё нет): `mc-cli create-admin --email ... --password ...`.
6. Backend: `uvicorn app.main:app --reload` (или без `--reload` в проде).
7. Бот (отдельный процесс): `mc-bot`.

Детали тестирования и деплоя — в файлах по ссылкам выше.

## Где настройки

- Переменные окружения и `.env` — см. **`.env.example`** и загрузку в **`app/config.py`** (`Settings`).
- Пути к БД и статике задаются через env (например `DATABASE_URL`, `SITE_ROOT`).

## Статический лендинг

Исходники визитки — `index.html`, `assets/`. Отдача через приложение зависит от `SITE_ROOT` и маршрутов в `app/main.py`.
