FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# postgresql-client-17 and age are for `manage.py backup_userdata` (the
# encrypted off-host backup, disaster-recovery-plan.md §7), which shells out to
# both. pg_dump's major version must match the server: Neon runs Postgres 17,
# and a pg_dump older than the server refuses to dump it. Pinned to 17 rather
# than the `postgresql-client` metapackage so a base-image change cannot move
# it silently. The base image is Debian Trixie, which carries both packages —
# no PGDG repository is needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential libpq-dev postgresql-client-17 age \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY manage.py /app/
COPY code_chronicle /app/code_chronicle
COPY api /app/api
COPY core /app/core
COPY config /app/config
COPY services /app/services
COPY templates /app/templates
COPY static /app/static
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh

RUN pip install --no-cache-dir .
RUN chmod +x /app/scripts/entrypoint.sh

ENV DJANGO_SETTINGS_MODULE=code_chronicle.settings.production

RUN mkdir -p /app/staticfiles

EXPOSE 8000

CMD ["/app/scripts/entrypoint.sh"]
