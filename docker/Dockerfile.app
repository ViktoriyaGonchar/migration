# Образ backend: FastAPI + Alembic + статика сайта. Один процесс uvicorn (без multi-worker).
FROM python:3.11-slim-bookworm

WORKDIR /app

RUN useradd --create-home --uid 1000 app \
    && apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY docker/app-entrypoint.sh /usr/local/bin/app-entrypoint.sh
RUN chmod +x /usr/local/bin/app-entrypoint.sh

COPY pyproject.toml README.md ./
COPY app ./app
COPY bot ./bot
COPY alembic.ini ./
COPY alembic ./alembic
COPY templates ./templates
COPY index.html ./
COPY assets ./assets

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN chown -R app:app /app

EXPOSE 8000

VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/app-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
