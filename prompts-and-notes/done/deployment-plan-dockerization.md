# Deployment Plan - Dockerization and Nginx

## Summary
- Add a production Docker Compose stack with app + nginx (external DB).
- Configure Nginx reverse proxy with Cloudflare Origin CA TLS and Django proxy headers.

## Scope and Goals
- Use Docker Compose for deployment on a 1GiB VM with external DB.
- Terminate TLS at Nginx using Cloudflare Origin CA.

## Proxy and TLS (Nginx + Cloudflare Origin CA)

### Nginx container
- Add Nginx service to `docker-compose.yml`.
- Mount a local `nginx.conf` and certs volume:
  - `ssl_certificate` and `ssl_certificate_key` from Cloudflare Origin CA.

### TLS termination flow
- Cloudflare terminates at edge -> Nginx terminates with Origin CA cert -> proxies to app container over HTTP.

### Django settings
- Add:
  - `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
  - Ensure `ALLOWED_HOSTS` includes domain.
- Keep existing `SECURE_SSL_REDIRECT`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SECURE`.

### Nginx config
- `listen 443 ssl;`
- `proxy_set_header Host`, `X-Forwarded-For`, `X-Forwarded-Proto https`.
- Optional redirect 80 -> 443.

## Docker Deployment (Compose)

### Services
- `web` (Django + gunicorn)
- `nginx` (reverse proxy + TLS)
- External DB (no container in compose)

### Runtime
- `web` container exposes internal port only.
- `nginx` exposes 443/80 publicly.

### Build
- Dockerfile builds prod image, runs:
  - `collectstatic`
  - `gunicorn` with tuned workers (likely 2 workers for 1GiB)

## Tests and Scenarios

1) Proxy Header
- Validate settings handle `X-Forwarded-Proto` correctly (integration smoke test).

## Assumptions and Defaults
- Deployment target is Docker Compose on a 1GiB VM with external DB.
- Cloudflare Origin CA is used for TLS termination.
