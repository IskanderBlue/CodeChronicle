#!/usr/bin/env sh
set -e

python manage.py migrate --noinput
# Skip the Tailwind build *source* (input.css): it's the v4 CLI entrypoint
# (`@import "tailwindcss"; @config ...`), not a servable asset. The served
# file is the built tailwind.css. Without --ignore, ManifestStaticFilesStorage
# post-processing tries to resolve `@import "tailwindcss"` as `css/tailwindcss`,
# fails with ValueError, and collectstatic exits non-zero (set -e kills boot).
python manage.py collectstatic --noinput --ignore input.css
# Bump the corpus stamp that core.http_cache serves as Last-Modified.  A
# deploy can change how a provision renders without changing the data, and
# without this the read surfaces would answer 304 and keep serving the
# markup of the previous image.  The command is idempotent and safe on an
# empty corpus; a re-crawl after a restart costs less than stale legal text.
python manage.py refresh_corpus_currency

exec gunicorn code_chronicle.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  --error-logfile -
