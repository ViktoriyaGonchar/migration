#!/bin/sh
set -e
# Том с SQLite монтируется в /data. При старте от root выставляем владельца для пользователя приложения.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data
  chown -R app:app /data
  exec gosu app "$@"
fi
exec "$@"
