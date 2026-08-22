"""
Django settings for production environment.
"""
import json
import logging
import os

import dj_database_url
from google.cloud import secretmanager

from .base import *  # noqa: F401, F403
from .base import (  # noqa: F811
    ANTHROPIC_API_KEY,
    SECRET_KEY,
    STRIPE_LIVE_SECRET_KEY,
    STRIPE_PRO_PRICE_ID,
    STRIPE_TEAM_PRICE_ID,
    STRIPE_TEST_SECRET_KEY,
)

DEBUG = False

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
_APP_RUNTIME_SECRETS: dict | None = None
_SECRET_CLIENT = None


def _get_secret_client():
    global _SECRET_CLIENT
    if _SECRET_CLIENT is None:
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


# Which Secret Manager secret holds the connection string.  The app answers
# `database_url`, which is the least-privilege `cc_app` role and cannot run DDL.
# A deploy overrides this to `database_url_owner` for one `migrate` run, because
# only the owner role can alter a table.
#
# It names a *secret*, never a credential.  Passing the owner connection string
# itself would put a password into a workflow file, an ssh argument, the VM's
# shell history and a CI log — four places it does not belong, to avoid one
# indirection.  The container already reads Secret Manager with the VM's service
# account, so this reuses the channel that serves the app.
#
# An unset value keeps the app's own secret, so a container that starts without
# it behaves exactly as it did before this existed.
DATABASE_URL_SECRET_ID = os.environ.get("DATABASE_URL_SECRET_ID", "") or "database_url"
DATABASE_URL = _get_secret(DATABASE_URL_SECRET_ID)
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

# Stripe — base.py reads these from os.environ, which the GCP deployment
# never populates (the container env-file carries only GCP_PROJECT_ID,
# DJANGO_SETTINGS_MODULE, ALLOWED_HOSTS). Resolve through the
# app_runtime_secrets bundle like email; env vars still win for
# compose-style deploys. Live mode defaults on: this is production.
STRIPE_LIVE_SECRET_KEY = _resolve_runtime_setting(
    "STRIPE_LIVE_SECRET_KEY", default=STRIPE_LIVE_SECRET_KEY
)
STRIPE_TEST_SECRET_KEY = _resolve_runtime_setting(
    "STRIPE_TEST_SECRET_KEY", default=STRIPE_TEST_SECRET_KEY
)
STRIPE_LIVE_MODE = _resolve_runtime_setting("STRIPE_LIVE_MODE", default="true").lower() == "true"
STRIPE_PRO_PRICE_ID = _resolve_runtime_setting("STRIPE_PRO_PRICE_ID", default=STRIPE_PRO_PRICE_ID)
# The per-seat price, resolved for the same reason as the one above: base.py
# reads os.environ, and this container's env-file does not carry it.  Without
# this line the setting is silently "" in production, the Team column offers
# no purchase, and nothing in the logs says why.
STRIPE_TEAM_PRICE_ID = _resolve_runtime_setting(
    "STRIPE_TEAM_PRICE_ID", default=STRIPE_TEAM_PRICE_ID
)

# Off-host encrypted backups — `manage.py backup_userdata`, run inside this
# container on the VM.  `base.py` reads these from `os.environ`, which the GCP
# deployment never populates: the container env-file carries three variables and
# none of them is an R2 key.  So resolve them through the app_runtime_secrets
# bundle, exactly as email and Stripe are resolved above.  Without this block
# the bundle keys are read by nothing and the command aborts with
# "R2_ENDPOINT_URL … not set", which reads like a missing secret rather than a
# setting that is never consulted.
#
# The serving app still needs no R2 credential — a Worker with an R2 binding
# serves the assets.  These exist for the backup command alone.
#
# No `default=` is needed.  `_resolve_runtime_setting` reads the environment
# variable of the same name before it gives up, and that is the one value
# `base.py` had, so a compose-style deploy keeps behaving as it did.
R2_ACCOUNT_ID = _resolve_runtime_setting("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = _resolve_runtime_setting("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = _resolve_runtime_setting("R2_SECRET_ACCESS_KEY")
# Derived here rather than carried over from base.py, which computed it from an
# account id that was empty at that point.  Carrying the value over would leave
# the endpoint empty even once the bundle supplies the account.
R2_ENDPOINT_URL = _resolve_runtime_setting("R2_ENDPOINT_URL") or (
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else ""
)
R2_BACKUP_BUCKET = _resolve_runtime_setting("R2_BACKUP_BUCKET")
BACKUP_AGE_RECIPIENT = _resolve_runtime_setting("BACKUP_AGE_RECIPIENT")
BACKUP_HEALTHCHECK_URL = _resolve_runtime_setting("BACKUP_HEALTHCHECK_URL")

# The asset-token secret (corpus.asset_signing).  Re-resolved here for the same
# reason as the block above: base.py reads os.environ, and the container has no
# such variable, so the value would be "" and every scan would be signed with
# SECRET_KEY instead of the string the edge Worker holds.  The Worker would
# then refuse all of them.
ASSET_SIGNING_KEY = _resolve_runtime_setting("ASSET_SIGNING_KEY")

# Hashed static filenames for cache busting (e.g. tailwind.a1b2c3d4.css)
STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}
