"""
Django settings for production environment.
"""
import json
import os

import dj_database_url

from .base import *  # noqa: F401, F403

DEBUG = False

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
_APP_RUNTIME_SECRETS = None
_SECRET_CLIENT = None


def _get_secret_client():
    global _SECRET_CLIENT
    if _SECRET_CLIENT is None:
        from google.cloud import secretmanager
        _SECRET_CLIENT = secretmanager.SecretManagerServiceClient()
    return _SECRET_CLIENT


def _get_secret(secret_id):
    """Fetch a secret from GCP Secret Manager, falling back to env vars."""
    env_val = os.environ.get(secret_id.upper().replace("-", "_"))
    if env_val:
        return env_val
    if not GCP_PROJECT_ID:
        return ""
    try:
        client = _get_secret_client()
        name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(name=name)
        return response.payload.data.decode("UTF-8")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Failed to fetch secret %s: %s", secret_id, exc)
        return ""


def _get_bundled_secret(key):
    """Fetch key from JSON secret bundle (app_runtime_secrets)."""
    global _APP_RUNTIME_SECRETS
    if _APP_RUNTIME_SECRETS is None:
        raw = _get_secret("app_runtime_secrets")
        if not raw:
            _APP_RUNTIME_SECRETS = {}
        else:
            try:
                parsed = json.loads(raw)
                _APP_RUNTIME_SECRETS = parsed if isinstance(parsed, dict) else {}
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error("Failed to parse app_runtime_secrets: %s", exc)
                _APP_RUNTIME_SECRETS = {}
    value = _APP_RUNTIME_SECRETS.get(key, "")
    return str(value) if value is not None else ""


def _resolve_runtime_setting(env_key, secret_id=None, default=""):
    """Resolve setting from bundle first, then specific secret, then env/default."""
    bundled = _get_bundled_secret(env_key)
    if bundled:
        return bundled
    if secret_id:
        specific = _get_secret(secret_id)
        if specific:
            return specific
    env_val = os.environ.get(env_key, "")
    if env_val:
        return env_val
    return default


DATABASE_URL = _get_secret("database_url")
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'code_chronicle'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }

SECRET_KEY = _get_secret("django_secret_key") or SECRET_KEY
ANTHROPIC_API_KEY = _resolve_runtime_setting("ANTHROPIC_API_KEY", "anthropic_api_key", ANTHROPIC_API_KEY)

ALLOWED_HOSTS_STR = os.environ.get("ALLOWED_HOSTS", "")
if ALLOWED_HOSTS_STR:
    ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_STR.split(",")]

CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h != "localhost"]

# Security settings for production
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# HSTS
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Email
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = _resolve_runtime_setting("EMAIL_HOST", "email_host")
EMAIL_PORT = int(_resolve_runtime_setting("EMAIL_PORT", "email_port", "587"))
EMAIL_HOST_USER = _resolve_runtime_setting("EMAIL_HOST_USER", "email_host_user")
EMAIL_HOST_PASSWORD = _resolve_runtime_setting("EMAIL_HOST_PASSWORD", "email_host_password")
EMAIL_USE_TLS = _resolve_runtime_setting("EMAIL_USE_TLS", "email_use_tls", "true").lower() == "true"
DEFAULT_FROM_EMAIL = _resolve_runtime_setting(
    "DEFAULT_FROM_EMAIL",
    "default_from_email",
    EMAIL_HOST_USER or "admin@codechronicle.ca",
)
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

ACCOUNT_EMAIL_VERIFICATION = os.environ.get("ACCOUNT_EMAIL_VERIFICATION", "mandatory")
