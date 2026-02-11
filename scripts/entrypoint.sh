#!/usr/bin/env sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn code_chronicle.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  --error-logfile -
