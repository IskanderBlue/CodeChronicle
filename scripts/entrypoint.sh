#!/usr/bin/env sh
set -e

python manage.py migrate --noinput
# Skip the Tailwind build *source* (input.css): it's the v4 CLI entrypoint
# (`@import "tailwindcss"; @config ...`), not a servable asset. The served
# file is the built tailwind.css. Without --ignore, ManifestStaticFilesStorage
# post-processing tries to resolve `@import "tailwindcss"` as `css/tailwindcss`,
# fails with ValueError, and collectstatic exits non-zero (set -e kills boot).
python manage.py collectstatic --noinput --ignore input.css

exec gunicorn code_chronicle.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  --error-logfile -
