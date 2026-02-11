"""
Django settings for production environment.
"""
import os

import dj_database_url

from .base import *  # noqa: F401, F403

DEBUG = False

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")


def _get_secret(secret_id):
    """Fetch a secret from GCP Secret Manager, falling back to env vars."""
    env_val = os.environ.get(secret_id.upper().replace("-", "_"))
    if env_val:
        return env_val
    if not GCP_PROJECT_ID:
        return ""
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(name=name)
        return response.payload.data.decode("UTF-8")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Failed to fetch secret %s: %s", secret_id, exc)
        return ""


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

# Email - configure for production
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
