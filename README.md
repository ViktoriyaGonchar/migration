# Migration Compass — backend, бот и закрытый сайт

Репозиторий объединяет статический лендинг (корень `SITE_ROOT`), **FastAPI** с async **SQLAlchemy** и **SQLite**, **SQLAdmin**, **Telegram-бота** (aiogram + httpx) и **Typer CLI**. Основной платёжный контур — **ручные заявки на оплату** (модерация в админке). Домен **payment_attempts** — заглушка провайдеров; не смешивать с ручным потоком.

**С нуля по шагам (новичку):** [START_HERE.md](START_HERE.md) — главный маршрут. Настройки: **`.env.example`** = минимум для первого запуска; **`.env.full.example`** = полный набор (prod, оплата, sandbox). **Полные инструкции:** [TESTING.md](TESTING.md) · [DEPLOY.md](DEPLOY.md) · [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md)

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
2. Скопировать [`.env.example`](.env.example) в `.env`: обязательно `TOKEN_PEPPER` и `ADMIN_SESSION_SECRET`; для бота добавьте `BOT_TOKEN` и `INTERNAL_API_KEY`. Расширенные переменные — [`.env.full.example`](.env.full.example).
3. Установка пакета: `pip install -e .` (или эквивалент из вашего workflow).
4. Миграции: `alembic upgrade head`.
5. Первый админ (если ещё нет): `mc-cli create-admin --email ... --password ...`.
6. Backend: `uvicorn app.main:app --reload` (или без `--reload` в проде).
7. Бот (отдельный процесс): `mc-bot`.

Детали тестирования и деплоя — в файлах по ссылкам выше.

## Где настройки

- Минимум — **`.env.example`**; prod / оплата / sandbox — **`.env.full.example`**. Семантика в **`app/config.py`** и **`bot/config.py`**.
- В Docker часть параметров задаётся в **`docker-compose.yml`**, а не в `.env` (см. [DEPLOY.md](DEPLOY.md)).
- **Главный маршрут для новичка** — [START_HERE.md](START_HERE.md): там пошаговый запуск и раздел **«Где взять и как сгенерировать значения для `.env`»** (что такое `TOKEN_PEPPER`, `ADMIN_SESSION_SECRET`, `INTERNAL_API_KEY`, откуда `BOT_TOKEN` и `BOT_USERNAME`, команды генерации, что не коммитить в git).

## Статический лендинг

Исходники визитки — `index.html`, `assets/`. Отдача через приложение зависит от `SITE_ROOT` и маршрутов в `app/main.py`.
