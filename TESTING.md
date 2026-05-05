# Руководство по ручному тестированию

Кросс-ссылки: [README.md](README.md) · [DEPLOY.md](DEPLOY.md) · [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md)

Документ разделяет **локальную** проверку, **staging/сервер** и **ограничения для production**. Команды CLI: **`mc-cli`**, **`mc-bot`** — точки входа в [`pyproject.toml`](pyproject.toml) (`project.scripts`).

---

## Prerequisites

- Python ≥ 3.11, установленный проект (`pip install -e .` или как у вас принято).
- Файл `.env` по образцу `.env.example`; для полного контура — непустые `INTERNAL_API_KEY`, `BOT_TOKEN`, `INTERNAL_API_BASE_URL`, `BOT_USERNAME` где требуется.
- Доступ к браузеру (сайт + SQLAdmin) и Telegram (бот).

---

## Local setup

1. Скопировать `.env.example` → `.env`, заполнить секреты и URL (сверить с `app/config.py`).
2. `alembic upgrade head`.
3. При пустой БД: `mc-cli create-admin`, при необходимости `mc-cli create-subscriber`, `mc-cli create-subscription` или `grant-access` (см. сценарии ниже).
4. Запуск backend: `uvicorn app.main:app --reload`.
5. Запуск бота: `mc-bot` (в другом терминале, тот же `.env` / cwd с БД, если путь к SQLite относительный).

**Ожидаемый результат:** `GET /health` возвращает JSON со статусом OK; бот отвечает в Telegram.

**Если сломано:** проверить `DATABASE_URL` и cwd, логи uvicorn, что порт 8000 не занят, что `BOT_TOKEN` верный.

---

## Docker Compose smoke (канонический baseline)

Конфигурация: [`docker-compose.yml`](docker-compose.yml), детали — [DEPLOY.md](DEPLOY.md).

- **Prerequisite:** файл `.env` из `.env.example`; для первого запуска — миграции: `docker compose --profile migrate run --rm migrate`.
- **Steps:** `docker compose up -d app bot`; дождаться `healthy` у `app` (`docker compose ps`). С хоста **без** опубликованного порта app проверить только через proxy или `docker compose exec app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read())"`. Убедиться, что бот отвечает в Telegram и вызовы к API не дают 401/503 по internal ключу.
- **Expected:** `/health` OK внутри контейнера `app`; бот стабильно работает с `INTERNAL_API_BASE_URL=http://app:8000`.
- **If broken:** `INTERNAL_API_KEY` в `.env` пустой (internal отключён — 503); рассинхрон ключа между контейнерами; миграции не применялись; том `sqlite_data` не смонтирован.

После вывода в production за HTTPS проверьте дополнительно `BASE_URL`, `COOKIE_SECURE` и вход по login-ссылке через браузер (см. разделы про сессию и proxy в этом файле и в DEPLOY).

---

## Local manual tests

Ниже для важных сценариев: **prerequisite → steps → expected result → if broken / what to check**.

### Миграции

- **Prerequisite:** чистая или существующая БД, актуальный код.
- **Steps:** `alembic upgrade head`; при необходимости сравнить текущую ревизию с `alembic current`.
- **Expected:** без ошибок, схема соответствует моделям.
- **If broken:** конфликт ревизий, другой `DATABASE_URL`, нет прав на файл SQLite.

### Backend start

- **Prerequisite:** `.env`, зависимости.
- **Steps:** `uvicorn app.main:app --reload`.
- **Expected:** сервер слушает порт; `/health` OK.
- **If broken:** импорты, порт, `SITE_ROOT` / путь к статике.

### Bot start

- **Prerequisite:** `BOT_TOKEN`, `INTERNAL_API_BASE_URL`, совпадающий с backend `INTERNAL_API_KEY` (если дергается internal).
- **Steps:** `mc-bot`.
- **Expected:** бот онлайн, команды отвечают.
- **If broken:** 401/503 на internal — ключ или base URL; сеть до backend.

### Тестовые данные (подписчик, доступ)

- **Prerequisite:** backend и БД.
- **Steps:** `mc-cli create-subscriber`; `mc-cli grant-access --subscriber-id N --days 30` (или `create-subscription` + `issue-login-token` по политике).
- **Expected:** печатается login URL; переход открывает gated контент при активной подписке.
- **If broken:** сообщения `ValueError` в CLI — читать текст; подписка не создана.

### Login token / web session

- **Prerequisite:** выданная ссылка с токеном, `COOKIE_SECURE` согласован с тем, http или https вы используете локально.
- **Steps:** открыть URL, обновить страницу, при необходимости выйти и зайти снова.
- **Expected:** сессия пользователя сохраняется (cookie см. `user_session_cookie_name` в `app/config.py`).
- **If broken:** `TOKEN_PEPPER` сменили — старые токены недействительны; за прокси проверить `Forwarded` / cookie Secure.

### Subscriber access (гейт сайта)

- **Prerequisite:** активная подписка, валидная сессия или новая login-ссылка.
- **Steps:** открыть `/` без и после входа.
- **Expected:** без входа — редирект/отказ; с входом — контент.
- **If broken:** срок подписки, неверный subscriber в ссылке.

### Telegram linking

- **Prerequisite:** `BOT_USERNAME` в `.env`, подписчик существует.
- **Steps:** `mc-cli issue-telegram-link --subscriber-id N`; открыть ссылку в Telegram, `/start` с payload.
- **Expected:** привязка `telegram_user_id` к подписчику; бот знает пользователя.
- **If broken:** истёк TTL токена; бот не тот; уже привязан другой аккаунт — смотреть сообщения бота и логи.

### `/pay` (реквизиты и сценарий без автосписания)

- **Prerequisite:** в `.env` заданы `PAYMENT_*` и при необходимости `PAYMENT_AMOUNT_LABEL` / синхрон с backend (`payment_amount_label`).
- **Steps:** в боте вызвать поток оплаты, убедиться что показываются реквизиты и инструкция.
- **Expected:** данные совпадают с env; это **не** автоподтверждение провайдера.

### Manual payment request (основной поток)

- **Prerequisite:** привязанный Telegram, настроенные реквизиты, список `ADMIN_NOTIFY_TELEGRAM_IDS` если нужны пуши.
- **Steps:** пользователь создаёт заявку через бота (ручной перевод); админ видит запись в SQLAdmin в очереди заявок.
- **Expected:** статус pending → после модерации согласно политике; уведомления админам при новой заявке (если настроено).
- **If broken:** уведомление не ушло — см. [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md) «notify»; internal недоступен — 503/401.

### Admin queue: approve / reject

- **Prerequisite:** учётка SQLAdmin, заявка в очереди.
- **Steps:** открыть список заявок, выполнить approve или reject.
- **Expected:** статус заявки обновлён; **доступ (подписка) при этом не выдаётся автоматически** только из-за approve — grant/reissue отдельно (страница Operator / CLI).
- **If broken:** путаница ролей; ожидание авто-grant после approve — это ошибка ожиданий, см. runbook.

### Operator: grant / reissue

- **Prerequisite:** права оператора в админке, корректный subscriber_id.
- **Steps:** выдать доступ или перевыпустить login-ссылку с UI Operator (или через `mc-cli grant-access` / `reissue-link` — как в вашей политике).
- **Expected:** подписка или новая ссылка; аудит согласно коду.
- **If broken:** подписчик не найден; нет активной подписки для reissue — сообщения системы.

### `/pay_status` vs `/payment_status`

- **Prerequisite:** понимание: **`/pay_status`** — статус **ручной** заявки; **`/payment_status`** — контур **stub** (`payment_attempts`), только если заглушки включены.
- **Steps:** с включённым `PAYMENTS_STUBS_ENABLED=true` проверить обе команды на тестовом пользователе с попыткой stub и с ручной заявкой.
- **Expected:** ответы различаются по смыслу; нет смешивания статусов разных доменов.
- **If broken:** stub выключен — `/payment_status` может быть недоступен или пуст; смотреть флаги в `.env.example`.

### Internal API

- **Prerequisite:** `INTERNAL_API_KEY` задан на backend; клиент шлёт заголовок `X-Internal-Key`.
- **Steps:** вызвать типичный internal endpoint (как в вашей интеграции с ботом); запрос без ключа или с неверным ключом.
- **Expected:** 401/403 на неверный ключ; при пустом ключе в конфиге — **503** на internal-маршруты.
- **If broken:** пробелы в ключе — в `app/config.py` ключ trim'ится; разные ключи у бота и API.

### CSV

- **Prerequisite:** данные в очереди / отчёте, если в UI есть экспорт.
- **Steps:** выгрузить CSV из админки (где доступно).
- **Expected:** файл открывается, кодировка/разделитель ожидаемы.
- **If broken:** таймаут на большом объёме; права доступа к разделу.

### Stale pending (сводка очереди)

- **Prerequisite:** заявки в статусе pending разного возраста; `STALE_PENDING_ALERT_HOURS` в `.env`.
- **Steps:** открыть страницу очереди заявок, проверить предупреждение по «самой старой» pending (Phase 9).
- **Expected:** при превышении порога — визуальное предупреждение / summary согласно шаблону админки.
- **If broken:** часовой пояс — метрики в UTC; порог 1–168.

### Logging, request_id, notify fail

- **Prerequisite:** доступ к логам процесса backend и бота.
- **Steps:** воспроизвести запрос к internal API; при ошибке уведомления — найти запись в логах.
- **Expected:** для internal — корреляция (например `internal_request_id` / structured path в логах по дизайну Phase 9); ошибки notify не валят процесс.
- **If broken:** нет логов — уровень логирования; см. [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md).

### Backup / restore validation (только на безопасной копии)

- **Prerequisite:** копия файла SQLite (не на production master).
- **Steps:** остановить процесс, скопировать `app.db` (или путь из `DATABASE_URL`), поднять копию на другом cwd или временном `DATABASE_URL`, `alembic upgrade head` при необходимости, smoke: `/health`, одна чтение из админки.
- **Expected:** данные читаются, целостность не нарушена.
- **If broken:** копирование «на горячую» без WAL checkpoint — см. [DEPLOY.md](DEPLOY.md) про SQLite.

---

## Server / staging manual tests

Повторить подмножество сценариев из «Local manual tests» на окружении, максимально близком к prod:

- HTTPS, `COOKIE_SECURE=true`, реальные секреты в vault/env.
- Отдельные процессы backend и `mc-bot`, health за reverse proxy.
- Internal API только с loopback или приватной сетью, ключ не в репозитории.

**Ожидаемый результат:** те же сценарии проходят с учётом URL и cookie Secure.

**If broken:** см. «Common failure symptoms» и [DEPLOY.md](DEPLOY.md).

---

## What not to test in production

- Деструктивные миграции без бэкапа.
- `PAYMENTS_SANDBOX_MODE` / mock confirm на боевых деньгах или реальных пользователях без политики.
- Массовое создание тестовых заявок и спам админ-уведомлений.
- Нагрузочное тестирование на единственном SQLite без изоляции.

---

## Expected results (кратко)

| Область | Ожидание |
|---------|----------|
| Health | `/health` OK |
| Миграции | `alembic upgrade head` без ошибок |
| Ручная заявка | Жизненный цикл pending → решение модератора |
| Approve/reject | Не путать с grant |
| Статусы | `/pay_status` ≠ `/payment_status` (stub) |

---

## Common failure symptoms

| Симптом | Куда смотреть |
|---------|----------------|
| Internal 503 | Пустой `INTERNAL_API_KEY` |
| Internal 401 | Неверный `X-Internal-Key` у бота |
| SQLite locked | Один писатель, длинные транзакции, бэкап без остановки — [DEPLOY.md](DEPLOY.md), [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md) |
| Бот молчит | `BOT_TOKEN`, сеть до `INTERNAL_API_BASE_URL` |
| Нет уведомления админам | `ADMIN_NOTIFY_TELEGRAM_IDS`, `/start` у бота |
| Сессия не держится | `COOKIE_SECURE`, домен cookie, HTTPS |

---

## Разделение сред

| | Локально | Staging / server | Production |
|---|----------|------------------|------------|
| Данные | Тестовые | Обезличенные или копии | Реальные |
| Секреты | `.env` | Vault / env сервера | Строго из секрет-хранилища |
| Риск | Низкий | Средний | Только безопасные проверки |

Политика деплоя и отката: [DEPLOY.md](DEPLOY.md). Операции в админке: [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md).
