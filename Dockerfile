FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY manage.py /app/
COPY code_chronicle /app/code_chronicle
COPY api /app/api
COPY core /app/core
COPY config /app/config
COPY templates /app/templates
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh

RUN pip install --no-cache-dir .
RUN chmod +x /app/scripts/entrypoint.sh

ENV DJANGO_SETTINGS_MODULE=code_chronicle.settings.production

RUN mkdir -p /app/staticfiles

EXPOSE 8000

CMD ["/app/scripts/entrypoint.sh"]
