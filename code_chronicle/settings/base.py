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
    # scope itself comes from corpus.sitemaps.
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
    # Local apps, in dependency order.  Every package that holds a model, a
    # management command or a template tag library must be listed, because
    # Django finds all three only inside an INSTALLED_APPS entry.  "shared",
    # "data" and "search" hold none of the three, so they are plain packages.
    "core",
    "accounts",
    "telemetry",
    "corpus",
    "web",
]

MIDDLEWARE = [
    # First on purpose, so its process_response runs last: it removes the
    # ``Vary: Cookie`` that SessionMiddleware adds below, and only from the
    # responses web.http_cache marked public.  See web.http_cache.
    "web.http_cache.PublicCacheVary",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "web.middleware.RateLimitMiddleware",
    # Last, so it runs after authentication has resolved request.user and
    # after the session is available.  It answers from the session on all but
    # the first request of a session, so the DB cost is per sign-in, not per
    # page.
    "web.middleware.TermsReacceptanceMiddleware",
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
                "web.context_processors.masthead_currency",
                "web.context_processors.page_metadata",
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
# prefixes itself lives in ``data/assets.py``.  Inline ``<img src="/laws/images/...">`` references
# in version HTML resolve here without rewriting.
#
# Development: served by Django via ``web.urls`` under ``/`` (see url conf).
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

# Shared secret behind the asset tokens (see ``corpus.asset_signing``).  The edge
# Worker holds the same string as its ASSET_SIGNING_KEY secret; the two must
# match or every gated scan 403s.  Empty falls back to SECRET_KEY, which is what
# a developer checkout wants — dev serves the assets from Django, so nothing
# checks the token there.
ASSET_SIGNING_KEY = os.environ.get("ASSET_SIGNING_KEY", "")


# ===================
# Cloudflare R2 — asset object storage (upload/sync side only)
# ===================
# Used by ``manage.py sync_images --backend r2`` to publish the mirrored
# asset trees (see ``data/assets.py``) to R2.  Serving is handled at
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
ACCOUNT_ADAPTER = "accounts.adapters.AccountAdapter"
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
ACCOUNT_SIGNUP_FORM_CLASS = "accounts.forms.CustomSignupForm"
TERMS_VERSION = "2026-08-21"
PRIVACY_VERSION = "2026-09-24"

# The earliest version that still counts as accepted.  A reader whose latest
# TermsAcceptance is older than one of these meets the re-acceptance wall; see
# accounts.reacceptance.
#
# These move only for a MATERIAL change, which is the distinction the Terms
# themselves draw.  Moving them for a typo trains readers to click past the
# prompt, and a prompt everybody clicks past is not evidence of anything.
#
# Both are at a material change.  The Terms gained an ownership section, a
# review right and post-termination obligations; the Privacy Policy gained the
# record of which provisions an account opens, and the compliance purpose that
# record serves.  Neither is a change a reader should first learn about by
# being audited under it.
#
# The Terms floor moved again on 21 August 2026, when the rewritten document
# went in force.  That edit defined "the Service" for the first time, so every
# restriction in the agreement changed scope — which is material by any
# reading, even though most of the same edit only removed duplicated rules.
#
# The Privacy Policy of 24 September 2026 did NOT move the floor.  It names
# Cloudflare, which already carried every request, and the Turnstile check on
# signup and reset.  That protects the reader and changes nothing the reader
# agreed to, so a new signup records the new text and nobody is asked again.
TERMS_REACCEPT_FROM = "2026-08-21"
PRIVACY_REACCEPT_FROM = "2026-08-19"

# Cloudflare Turnstile on the two forms that send an email to a typed address
# (accounts.turnstile).  The signup form gets the check through
# ACCOUNT_SIGNUP_FORM_CLASS; the reset form needs its own entry here.
ACCOUNT_FORMS = {"reset_password": "accounts.reset_forms.TurnstileResetPasswordForm"}
# The site key is public: the widget prints it into the page.  The one widget
# is registered for codechronicle.ca, localhost and 127.0.0.1, so a developer
# can run the real check by setting only the secret.
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "0x4AAAAAAFB0o3jmJMqubOgU")
# Empty switches the check off.  production.py reads it from the bundle, and
# accounts.E001 refuses a deployed instance without it.
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
# The page hostnames a token may come from.  production.py replaces this list,
# because a production token solved on localhost must not pass.
TURNSTILE_HOSTNAMES: tuple[str, ...] = ("localhost", "127.0.0.1")

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
#: The per-seat price for a firm.  A second price id, read exactly as the Pro
#: one is (``accounts.pricing``).  Empty means a firm cannot buy seats, and the
#: control is hidden rather than offered and refused.
STRIPE_TEAM_PRICE_ID = os.environ.get("STRIPE_TEAM_PRICE_ID", "")

#: Whether a signed-in reader's team memberships are honoured on screen.  A
#: development switch, read through ``accounts.teams.team_memberships_enabled``.
#: Off makes the product behave as though this reader belonged to no firm, so
#: both the "buy seats" and the "manage seats" states are reachable without
#: making and destroying an organization.  It never hides the Team column and
#: never revokes access.
TEAM_MEMBERSHIPS_ENABLED = (
    os.environ.get("TEAM_MEMBERSHIPS_ENABLED", "True").lower() != "false"
)

# A subscription belongs to an organization, never to a person.  Somebody who
# buys for themselves gets an organization of one, so there is one billing
# path and not two, and ``User.has_active_subscription`` has one answer to
# give.  See tasks/complete/team-payments.md.
#
# dj-stripe reads this setting when it imports its own initial migration, so
# the setting decides which table ``djstripe_customer.subscriber_id`` points
# at.  The dependency below is what lets that table be created after the
# organization exists; without it a fresh database cannot resolve the target.
# An existing database also needs core.0058, which moves the column's contents
# and its foreign key.
#
# **It is read from the environment so one deploy can be made in two steps.**
# On a database where dj-stripe is already installed against the old subscriber
# model, `migrate` refuses outright:
#
#     InconsistentMigrationHistory: Migration djstripe.0001_initial is applied
#     before its dependency core.0057_organization_membership_invite
#
# because the setting adds that dependency to a migration Django already
# recorded as applied.  So core.0057 has to land *first*, while dj-stripe still
# believes the subscriber is the user.  Run this once against production,
# from the image being deployed, before the normal migrate:
#
#     docker run --rm -e DJSTRIPE_SUBSCRIBER_MODEL=core.User <image>
#         python manage.py migrate core 0057
#
# The ordinary deploy then runs with the default, finds core.0057 applied, and
# applies core.0058 — which moves the column's contents and its foreign key.
# Rehearsed against a database built from the previous commit.
#
# A fresh database needs no such step: the dependency puts the organization
# table in place before djstripe.0001 asks for it.
DJSTRIPE_SUBSCRIBER_MODEL = os.environ.get("DJSTRIPE_SUBSCRIBER_MODEL", "core.Organization")

# Only meaningful when the subscriber is the organization.  Declaring it while
# the subscriber is the user is what would re-create the inconsistency the
# override exists to avoid.
if DJSTRIPE_SUBSCRIBER_MODEL == "core.Organization":
    DJSTRIPE_SUBSCRIBER_MODEL_MIGRATION_DEPENDENCY = "0057_organization_membership_invite"


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
# Free-tier content gating (accounts.access)
# ===================
# Content-scoped tier split (unconditional since 2026-07: the old
# FREE_TIER_GATING_ENABLED switch soaked on in prod and was removed):
# anonymous and signed-in non-Pro users are limited to the editions named
# below; Pro (active subscription or pro_courtesy) is unrestricted.
# Canonical edition names (CodeEdition.code_name, e.g. "OBC_2006") in the
# free scope.  Env-backed so the free window can widen without a deploy.
# ===================
# Signup notice (accounts.signals.signup_notice)
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

# Who hears that an account has run past its daily API allowance
# (`telemetry.throttle_notice`).  Nothing refuses that account any more, so a person
# reading this message is the control.  Empty switches the notice off, which is
# what a local run wants.
API_THROTTLE_NOTICE_EMAILS = [
    address.strip()
    for address in os.environ.get(
        "API_THROTTLE_NOTICE_EMAILS", "rob@codechronicle.ca"
    ).split(",")
    if address.strip()
]


FREE_TIER_CODE_NAMES = [
    name.strip()
    for name in os.environ.get("FREE_TIER_CODE_NAMES", "OBC_2006").split(",")
    if name.strip()
]
