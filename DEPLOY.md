# Деплой (vendor-neutral)

Кросс-ссылки: [README.md](README.md) · [TESTING.md](TESTING.md) · [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md)

Общая схема: один (или несколько) процессов **ASGI (uvicorn)** для `app.main:app`, отдельный процесс **`mc-bot`**, файловая **SQLite**, миграции **Alembic**. Точные команды обёртки (systemd, docker, k8s) — по вашей инфраструктуре.

---

## Prerequisites

- Python ≥ 3.11 на сервере или в образе.
- Установка проекта: `pip install -e .` (сверить с `pyproject.toml`).
- Файл окружения (не коммитить): переменные из **`.env.example`**, семантика в **`app/config.py`**.

---

## Env / secrets

- Минимум для работы сайта и админки: `DATABASE_URL`, `TOKEN_PEPPER`, `ADMIN_SESSION_SECRET`, `BASE_URL` (публичный URL без завершающего `/`), при HTTPS — `COOKIE_SECURE=true`.
- Бот и internal: `INTERNAL_API_KEY`, `INTERNAL_API_BASE_URL`, `BOT_TOKEN`, `BOT_USERNAME`; платежи вручную — `PAYMENT_*`, `ADMIN_NOTIFY_TELEGRAM_IDS`.
- Заглушки провайдеров: `PAYMENTS_STUBS_ENABLED`, `PAYMENTS_SANDBOX_MODE`, `PAYMENTS_MOCK_UI` — на production обычно выключены; включать только осознанно.
- Phase 9: `STALE_PENDING_ALERT_HOURS` (1–168).

Секреты хранить в менеджере секретов или правах файла env, не в git.

---

## Filesystem permissions

- Процесс **app** (uvicorn) должен **читать/писать** файл SQLite и каталог с ним (создание `-wal`/`-shm` при WAL). В Docker baseline бот том с БД не монтирует.
- `SITE_ROOT` должен быть читаем для статики.
- Логи (если пишутся в файлы) — отдельный каталог с правами на запись.

---

## SQLite notes

- Один основной писатель; избегать длительных блокировок и копирования БД «с живого» файла без остановки процессов или использования backup API (см. runbook).
- Путь в `DATABASE_URL` должен быть согласован с процессом, который **пишет** в SQLite (в каноническом **Docker Compose** baseline том БД только у `app`; бот к файлу БД не обращается). Вне Docker при локальном запуске uvicorn и `mc-bot` на одной машине часто используют один и тот же путь к файлу.
- Перед обновлением схемы — бэкап файла БД.

---

## Migrations

- Остановить или перевести в режим без записи (по политике), сделать копию БД.
- Выполнить: `alembic upgrade head` от каталога проекта с тем же `DATABASE_URL`.
- Проверить `alembic current`, smoke: `/health`, вход в `/admin`.

---

## Backend process

- Команда вида: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (workers и логирование — по нагрузке; для SQLite многопроцессная запись ограничена).
- За reverse proxy пробросить заголовки, нужные для корректного `BASE_URL`/HTTPS, если приложение их использует.

---

## Bot process

- Отдельный долгоживущий процесс: `mc-bot` (см. `pyproject.toml`).
- `INTERNAL_API_BASE_URL` должен указывать на HTTP API приложения (в Docker baseline — внутренний URL сервиса `app`, см. ниже). Публичный `BASE_URL` для ссылок в браузере задаётся отдельно.

---

## Reverse proxy / HTTPS / cookies

- Терминация TLS на proxy; backend может быть HTTP за ним.
- При HTTPS выставить `COOKIE_SECURE=true`, иначе cookie сессии пользователя не установятся в браузере (см. `Settings.cookie_secure`).
- Проверить, что cookie админки и пользователя не конфликтуют с другими приложениями на том же домене (имена в `app/config.py`).

---

## Health checks

- `GET /health` — лёгкий endpoint для балансировщика (см. `app/main.py`).
- Не путать с защищёнными маршрутами: health должен быть доступен без авторизации.

---

## Post-deploy smoke

Краткий список (детали в [TESTING.md](TESTING.md)):

1. `/health`
2. Статика главной страницы
3. Вход в SQLAdmin
4. Очередь ручных заявок открывается
5. Бот отвечает; internal не отдаёт 503 из-за пустого ключа

---

## Logs

- Настроить сбор stdout/stderr процессов (journald, контейнер, файловый агент).
- Для расследований: correlation id для internal (см. Phase 9 в коде/шаблонах), ошибки notify у бота.

---

## Backup policy

- Регулярное копирование файла БД в недоступное для приложения хранилище.
- Перед миграциями и опасными операциями — точечный снимок.
- Процедура восстановления прогнать на **копии** (см. [TESTING.md](TESTING.md)).

---

## Rollback basics

- Откат **кода** на предыдущий релиз + рестарт процессов.
- Откат **миграций** — только если есть обратная ревизия Alembic и это согласовано; иначе откат только приложения при совместимой схеме.
- После отката — smoke и проверка бота.

---

## Опасные действия / не делать

- Удалять или перезаписывать файл SQLite без бэкапа.
- Коммитить `.env` с реальными ключами.
- Включать sandbox/mock платежи на боевом контуре без явной политики.
- Менять `TOKEN_PEPPER` на живой базе — действующие токены станут невалидны.
- Давать публичный доступ к internal API без сетевой изоляции и сильного ключа.
- Полагаться на approve в админке как на автоматическую выдачу подписки — **approve/reject ≠ grant** ([ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md)).

---

## Опциональные примечания

### systemd

Пример идеи: два unit-файла — `migration-api.service` (uvicorn) и `migration-bot.service` (`mc-bot`), `After=network.target`, `WorkingDirectory=` на корень проекта, `EnvironmentFile=` на путь к env.

### Docker Compose (канонический baseline в репозитории)

В корне лежит [`docker-compose.yml`](docker-compose.yml) — эталонная схема для контейнеров.

**Топология:**

- Сервис **`app`**: образ из [`docker/Dockerfile.app`](docker/Dockerfile.app), один процесс uvicorn (без multi-worker), том **`sqlite_data`** смонтирован в **`/data`** только у этого сервиса; `DATABASE_URL` в compose переопределён на `sqlite+aiosqlite:////data/app.db`.
- Сервис **`bot`**: образ из [`docker/Dockerfile.bot`](docker/Dockerfile.bot), том БД **не** монтируется; в compose задано `INTERNAL_API_BASE_URL=http://app:8000` (Docker DNS, внутренняя сеть **`backend`**).
- **`migrate`**: тот же образ, что у `app`, профиль **`migrate`**; команда `alembic upgrade head`, тот же том. Запуск **до** приёма трафика:  
  `docker compose --profile migrate run --rm migrate`  
  Затем: `docker compose up -d app bot`.
- Порт **8000** у `app` только **`expose`** (доступен другим контейнерам в сети compose), **не** публикуется на хост через `ports:`. В production в WAN смотрит только **reverse proxy**; proxy проксирует на `app:8000` по внутренней сети (proxy может быть вне этого compose — см. комментарии в `docker-compose.yml`).

**Согласованность env:**

- Один файл **`.env`** подключается к `app` и `bot`; **`INTERNAL_API_KEY`** должен совпадать. **`BASE_URL`** — публичный `https://…` (login-ссылки), при HTTPS **`COOKIE_SECURE=true`**. Значение **`INTERNAL_API_BASE_URL`** для бота в compose переопределено и не должно дрейфовать относительно имени сервиса `app`.

**Сборка образов:**

- `docker compose build` или сборка при первом `up`. Build context и исключения — [`.dockerignore`](.dockerignore).

Подробный smoke после compose — в [TESTING.md](TESTING.md) (раз про Docker).
