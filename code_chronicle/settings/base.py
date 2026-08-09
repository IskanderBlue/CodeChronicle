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
    # `sitemaps` ships the templates the /sitemap.xml views render; the URL
    # scope itself comes from core.sitemaps.
    "django.contrib.sitemaps",
    "django.contrib.postgres",
    # `intcomma`, for the corpus figures on the landing page — a five-digit
    # count set at display size is unreadable without a thousands separator.
    "django.contrib.humanize",
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
                "core.context_processors.page_metadata",
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
# Page images (``documents/...``), composited e-Laws table images
# (``elaws/...``), composited amended-table images (``amended/...``), and
# e-Laws inline asset bytes (``laws/images/...``) live under this root with
# paths verbatim matching the URL paths in the CCM output JSON.  The list of
# prefixes itself lives in ``config/assets.py``.  Inline ``<img src="/laws/images/...">`` references
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
# asset trees (see ``config/assets.py``) to R2.  Serving is handled at
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

# Dead-man's switch.  The backup pings this URL when it finishes, and the
# service raises the alarm when a ping does not arrive.  That polarity is the
# point: a check that lives on the backup host cannot tell "the run failed"
# from "the host is gone", and the second failure is the one that matters.
# Unset means no ping, which is right for a developer machine.
BACKUP_HEALTHCHECK_URL = os.environ.get("BACKUP_HEALTHCHECK_URL", "")


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
# signup form (clickwrap) and stamp the accepted versions onto the user.
#
# TWO versions, not one.  The checkbox covers both documents, but the two
# documents change independently, so a single stamp forced a choice with no
# right answer whenever only one of them changed: bump it and the acceptance
# record dates the *unchanged* document falsely, or leave it and the record
# points at text that has since been rewritten.  Both failures corrupt the
# evidence the record exists to be.
#
# Each value matches its own document's "Last updated" line.  Bump the one
# that changed, and only when the change is substantive — a typo fix is not a
# new agreement.
ACCOUNT_SIGNUP_FORM_CLASS = "core.forms.CustomSignupForm"
TERMS_VERSION = "2026-06-17"
PRIVACY_VERSION = "2026-08-01"

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
RATE_LIMIT_ANONYMOUS = 1  # full-result searches per day for anonymous users (per IP)
RATE_LIMIT_AUTHENTICATED = 3  # searches per day for logged-in free users

# Above RATE_LIMIT_ANONYMOUS and up to this count, an anonymous search still
# *runs* — the visitor gets provision ids, titles and editions, but no text.
# Two reasons, one for the reader and one for us.  The reader learns that the
# corpus holds an answer to their actual question, which no generic "limit
# reached" page can tell them.  And the run populates QueryCache and the
# scoring path, so the parse a subscriber needs later is already paid for.
# Above this second count the search does not run at all: the teaser costs an
# LLM parse per request, so it needs its own ceiling or it is an open tap.
RATE_LIMIT_ANONYMOUS_TEASER = 10


# ===================
# Free-tier content gating (core.access)
# ===================
# Content-scoped tier split (unconditional since 2026-07: the old
# FREE_TIER_GATING_ENABLED switch soaked on in prod and was removed):
# anonymous and signed-in non-Pro users are limited to the editions named
# below; Pro (active subscription or pro_courtesy) is unrestricted.
# Canonical edition names (CodeEdition.code_name, e.g. "OBC_2006") in the
# free scope.  Env-backed so the free window can widen without a deploy.
# ===================
# Signup notice (core.signup_notice)
# ===================
# Where to write when somebody creates an account.  Empty switches it off,
# which is what a test or a local run wants; every environment that should
# send sets it.  A list, because the second person to want these should not
# need a code change.
SIGNUP_NOTICE_EMAILS = [
    address.strip()
    for address in os.environ.get(
        "SIGNUP_NOTICE_EMAILS", "rob@codechronicle.ca"
    ).split(",")
    if address.strip()
]


FREE_TIER_CODE_NAMES = [
    name.strip()
    for name in os.environ.get("FREE_TIER_CODE_NAMES", "OBC_2006").split(",")
    if name.strip()
]
