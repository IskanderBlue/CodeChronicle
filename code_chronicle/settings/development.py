"""
Django settings for local development.
"""

import os

import dj_database_url

from .base import *  # noqa: F401, F403

DEBUG = True

# Database
# Requires DATABASE_URL (PostgreSQL)
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required for development settings.")

DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}

# Email backend for development (prints to console)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable HTTPS requirements for local development
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Django Debug Toolbar (optional, add to dev dependencies if needed)
# INSTALLED_APPS += ['debug_toolbar']
# MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
# INTERNAL_IPS = ['127.0.0.1']
