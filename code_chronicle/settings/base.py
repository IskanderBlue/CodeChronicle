"""
Django base settings for code_chronicle project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-key-change-in-production")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.postgres",
    # Third-party apps
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "djstripe",
    # Local apps
    "core",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "core.middleware.RateLimitMiddleware",
]

ROOT_URLCONF = "code_chronicle.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.masthead_currency",
            ],
        },
    },
]

WSGI_APPLICATION = "code_chronicle.wsgi.application"


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"


# ===================
# Asset root — CCM-mirrored images
# ===================
# Page images (``documents/...``), composited amended-table images
# (``amended/...``), and e-Laws inline asset bytes (``laws/images/...``)
# live under this root with paths verbatim matching the URL paths in the
# CCM output JSON.  Inline ``<img src="/laws/images/...">`` references
# in version HTML resolve here without rewriting.
#
# Development: served by Django via ``core.urls`` under ``/`` (see url conf).
# Production: served from Cloudflare R2 at the edge by a Worker bound to the
# ``codechronicle-assets-prod`` bucket (see the CodeChronicleTerraform
# ``modules/cloudflare`` asset proxy) — the origin/app is not in the path.
#
# The default ``BASE_DIR/assets`` directory is the on-disk copy for the local
# backend; it is gitignored and is the local mirror of what ``sync_images
# --backend r2`` publishes to the R2 bucket. Override with the ``ASSET_ROOT``
# env var to point at a checkout of ``CodeChronicleMapping/data/outputs``
# directly during local dev — the layout is identical, so no sync is needed.
ASSET_ROOT = Path(os.environ.get("ASSET_ROOT", BASE_DIR / "assets"))


# ===================
# Cloudflare R2 — asset object storage (upload/sync side only)
# ===================
# Used by ``manage.py sync_images --backend r2`` to publish the mirrored
# asset trees (documents/, amended/, laws/) to R2.  Serving is handled at
# the Cloudflare edge by a Worker with an R2 binding (see the Terraform
# ``modules/cloudflare`` asset-proxy), so the running app needs NO R2
# credentials — only whoever runs the sync does.  S3-compatible: keys are
# minted under R2 > Manage R2 API Tokens.  Endpoint defaults to the
# account-scoped R2 host when unset.
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL", "") or (
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else ""
)

# Off-host encrypted DB backups (manage.py backup_userdata — see
# docs/security/disaster-recovery-plan.md §7).  A *separate* bucket from the
# public assets one is strongly preferred; falls back to R2_BUCKET if unset.
# BACKUP_AGE_RECIPIENT is an age *public* key ("age1…") — the backup box
# encrypts to it but never holds the private key, which stays offline for restore.
R2_BACKUP_BUCKET = os.environ.get("R2_BACKUP_BUCKET", "")
BACKUP_AGE_RECIPIENT = os.environ.get("BACKUP_AGE_RECIPIENT", "")


# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user model
AUTH_USER_MODEL = "core.User"


# ===================
# Authentication (django-allauth)
# ===================
SITE_ID = 1
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# allauth v0.65+ configuration
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_ADAPTER = "core.adapters.AccountAdapter"
# Mix a required Terms of Service / Privacy Policy acceptance checkbox into the
# signup form (clickwrap) and stamp the accepted version onto the user.  Bump
# TERMS_VERSION to match the Terms' "Last updated" date whenever they change.
ACCOUNT_SIGNUP_FORM_CLASS = "core.forms.CustomSignupForm"
TERMS_VERSION = "2026-06-17"

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"


# ===================
# Anthropic (LLM)
# ===================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


# ===================
# Stripe (dj-stripe)
# ===================
STRIPE_LIVE_MODE = os.environ.get("STRIPE_LIVE_MODE", "False").lower() == "true"
STRIPE_LIVE_SECRET_KEY = os.environ.get("STRIPE_LIVE_SECRET_KEY", "")
STRIPE_TEST_SECRET_KEY = os.environ.get("STRIPE_TEST_SECRET_KEY", "")
DJSTRIPE_FOREIGN_KEY_TO_FIELD = "id"
DJSTRIPE_USE_NATIVE_JSONFIELD = True
STRIPE_PRO_PRICE_ID = os.environ.get("STRIPE_PRO_PRICE_ID", "")
DJSTRIPE_SUBSCRIBER_MODEL = "core.User"


# ===================
# Rate Limiting
# ===================
RATE_LIMIT_ANONYMOUS = 1  # searches per day for anonymous users (per IP)
RATE_LIMIT_AUTHENTICATED = 3  # searches per day for logged-in free users


# ===================
# Free-tier content gating (core.access)
# ===================
# Master switch for the content-scoped tier split: when on, anonymous and
# signed-in non-Pro users are limited to the editions named below; Pro
# (active subscription or pro_courtesy) is unrestricted.  Ships OFF so the
# gate can be deployed and tested before Pro is purchasable — flipping it
# while the pricing page still says "free unlimited" would strand free
# users with nothing to buy (go-live checklist:
# tasks/free-tier-obc2006-scope.md).
FREE_TIER_GATING_ENABLED = (
    os.environ.get("FREE_TIER_GATING_ENABLED", "False").lower() == "true"
)
# Canonical edition names (CodeEdition.code_name, e.g. "OBC_2006") in the
# free scope.  Env-backed so the free window can widen without a deploy.
FREE_TIER_CODE_NAMES = [
    name.strip()
    for name in os.environ.get("FREE_TIER_CODE_NAMES", "OBC_2006").split(",")
    if name.strip()
]
