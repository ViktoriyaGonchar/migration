# Migration Compass (Django)

Django-проект для Migration Compass с двумя публичными страницами:
- `/` — SEO-лендинг;
- `/app/` — основная продуктовая страница.

Главный принцип проекта: страница `/app/` сохранена визуально и по UX максимально близко к исходному статическому варианту.

## Технологии

- Python 3.11+
- Django 5.x
- SQLite (на старте)

## Архитектура

- `config` — настройки Django, корневой routing.
- `public` — публичные страницы (`seo_landing`, `app_index`).
- `leads` — модель лидов, форма и admin.
- `access` — модель токенов доступа, сервисный слой, management command.
- `static` — фронтовые ассеты (`css`, `js`, `videos`).

## Роутинг

- `/` -> SEO-лендинг.
- `/app/` -> основная продуктовая страница.
- `/admin/` -> Django admin.

## Быстрый старт

1. Создать виртуальное окружение:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Установить зависимости:

```powershell
pip install -r requirements.txt
```

3.## Настройка `.env`

Создайте файл `.env` в корне проекта на основе `.env.example`.

Пример минимального `.env` для локальной разработки:

```env
DJANGO_SECRET_KEY=your-generated-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
SITE_URL=
```

### Что означает каждая переменная

- `DJANGO_SECRET_KEY` — секретный ключ Django.  
  Используется для криптографических операций внутри проекта.  
  Должен быть уникальным и непубличным.  
  Не храните значение из production в открытом виде и не коммитьте `.env` в git.

- `DJANGO_DEBUG` — режим отладки Django.  
  Для локальной разработки обычно `True`.  
  Для staging/production должен быть `False`.

- `DJANGO_ALLOWED_HOSTS` — список разрешённых хостов через запятую.  
  Для локальной разработки обычно:
  `127.0.0.1,localhost`  
  Для сервера, например:
  `example.com,www.example.com`

- `SITE_URL` — базовый URL сайта без завершающего `/`.  
  Используется, например, в `create_dev_token`, чтобы печатать полный URL вида:
  `https://example.com/app/?token=...`  
  В локальной разработке можно оставить пустым, тогда команда выведет относительный путь:
  `/app/?token=...`

### Как сгенерировать `DJANGO_SECRET_KEY`

Самый простой способ — через Python:

```powershell
py -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Скопируйте результат и подставьте в `.env`:

```env
DJANGO_SECRET_KEY=сюда_вставить_сгенерированный_ключ
```

### Рекомендации по значениям

#### Для локальной разработки

```env
DJANGO_SECRET_KEY=сгенерированный-ключ
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
SITE_URL=
```

#### Для staging / production

```env
DJANGO_SECRET_KEY=сгенерированный-ключ
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=example.com,www.example.com
SITE_URL=https://example.com
```

### Важно

- `.env` не должен попадать в git.
- `DJANGO_SECRET_KEY` должен быть разным для разных окружений.
- При `DJANGO_DEBUG=False` обязательно проверьте корректность `DJANGO_ALLOWED_HOSTS`.

4. Применить миграции:

```powershell
py manage.py migrate
```

5. Создать суперпользователя:

```powershell
py manage.py createsuperuser
```

6. Запустить сервер:

```powershell
py manage.py runserver
```

## Лиды и поле `source`

Форма на `/app/` принимает только пользовательские поля:
- `name`
- `email`
- `country`
- `message`

Поле `source` не передается пользователем и выставляется только на backend:
- `app` — обычная отправка формы с `/app/`;
- `app_token` — если в запросе присутствует `token`.

## Токены доступа

Модель `AccessToken` хранит:
- `token` (unique, indexed)
- `email`
- `full_name`
- `is_active`
- `expires_at`
- `created_at`
- `last_used_at`
- `notes`

Сервисный слой `access/services.py`:
- генерирует токены;
- проверяет коллизии и обеспечивает уникальность токена;
- валидирует активность/срок;
- может помечать токен как использованный.

## Команда `create_dev_token`

Базовый запуск:

```powershell
py manage.py create_dev_token
```

Опции:

```powershell
py manage.py create_dev_token --email user@example.com --full-name "Dev User" --save-file
```

Поведение URL:
- если `SITE_URL` задан (например `https://example.com`), команда печатает полный URL:
  - `https://example.com/app/?token=...`
- если `SITE_URL` не задан, команда печатает относительный URL:
  - `/app/?token=...`

Флаг `--save-file` сохраняет токен в `.dev_token`.

## Что уже реализовано под дальнейшее развитие

- отдельный app `access`;
- service layer для токенов;
- готовность к сценариям с `?token=...` или будущим отдельным token-endpoint.

## Что сейчас не реализовано

- полноценная авторизация по токену;
- API-слой для внешних интеграций;
- фоновые задачи.
