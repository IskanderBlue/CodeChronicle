#!/usr/bin/env sh
set -e

python manage.py collectstatic --noinput

exec gunicorn code_chronicle.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  --error-logfile -
