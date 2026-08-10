"""Tokens that let the edge serve a gated scan without asking the origin.

The problem this solves.  In production a Cloudflare Worker answers the
CCM-mirrored asset trees from R2 at the edge, so Django is not in the request
path and :func:`core.access.edition_allowed` never runs on an image.  The
whole-page scans under ``documents/`` are the primary evidence for the
pre-e-Laws editions, they belong to an edition we gate, and their keys are
sequential — ``documents/ont_reg_1997_v2/221.webp`` names its own neighbours.
So the gate on the reading page was doing nothing for the pictures.

The design.  Django appends a keyed token to the URLs it renders, and the
Worker refuses a signed prefix without a matching one.  Neither side needs a
round trip to the other: they share one secret.  Because a token is only ever
minted while rendering a page the gate has already allowed, the asset gate is
the page gate rather than a second rule that can drift from it.

**The token does not expire, and that is deliberate.**  An expiring token
cannot survive the conditional responses in :mod:`core.http_cache` — a crawler
or a reader holding a cached page would come back to broken images — and it
cannot survive a printed exhibit outliving its own footnotes.  What the token
defeats is *enumeration*, which is the actual exposure: a sequential key space
anybody can walk.  It does not defeat somebody re-posting a URL they were
legitimately given, and it is not meant to.
"""

import hmac
from hashlib import sha256
from typing import Any

from django.conf import settings
from django.core.checks import Error

from config.assets import SIGNED_PREFIXES

#: Query parameter carrying the token.  Short, because it goes on every scan.
TOKEN_PARAM = "s"

#: Hex characters kept from the digest.  128 bits — far beyond guessing, and
#: it keeps the URL readable in a citation or a print footer.
TOKEN_LENGTH = 32


def _secret() -> bytes:
    """The shared secret, as bytes.

    Falls back to ``SECRET_KEY`` so a developer checkout needs no extra
    configuration.  Production sets ``ASSET_SIGNING_KEY`` to the same value the
    Worker holds.

    That fallback is the reason :func:`check_asset_signing_key` exists.  A
    container that never received the key does not fail here: it signs every
    URL with ``SECRET_KEY``, renders a perfect page, and the 403s appear at the
    edge, on images only, for gated readers only, naming the Worker rather than
    the missing setting.  The check turns that into a refused deploy.
    """
    key = getattr(settings, "ASSET_SIGNING_KEY", "") or settings.SECRET_KEY
    return key.encode("utf-8")


def check_asset_signing_key(app_configs: Any, **kwargs: Any) -> list[Error]:
    """Refuse to start a deployed instance with no asset-signing key.

    ``manage.py check`` runs in CI and ahead of ``migrate`` in
    ``scripts/entrypoint.sh``, so this fails the deploy rather than shipping an
    instance that signs with the wrong key.

    It matches what the other half of this gate already does: the Worker
    refuses outright when its ``ASSET_SIGNING_KEY`` binding is missing.  Before
    this, the Worker failed closed and the app failed silently — the same
    misconfiguration, reported by one side and hidden by the other.

    ``DEBUG`` is exempt, because the fallback is the point of the fallback: a
    developer checkout signs and verifies with one key and never meets a
    Worker.
    """
    # Bound to a name rather than inlined into the ``if``: mypy pushes the
    # boolean context of a condition into ``getattr``'s default and then reads
    # ``""`` as the wrong type.
    key = getattr(settings, "ASSET_SIGNING_KEY", "")
    if settings.DEBUG or key:
        return []
    return [
        Error(
            "ASSET_SIGNING_KEY is empty, so page scans would be signed with "
            "SECRET_KEY and the edge would refuse every one of them.",
            hint=(
                "Set ASSET_SIGNING_KEY in the app_runtime_secrets bundle to the "
                "same value the Cloudflare Worker holds "
                "(modules/cloudflare/main.tf, var.asset_signing_key)."
            ),
            id="core.E001",
        )
    ]


def needs_token(asset_key: str) -> bool:
    """Is ``asset_key`` under a prefix the Worker protects?"""
    head, _, _ = asset_key.lstrip("/").partition("/")
    return head in SIGNED_PREFIXES


def asset_token(asset_key: str) -> str:
    """The token for one asset key (e.g. ``documents/x/221.webp``)."""
    normalized = asset_key.lstrip("/")
    digest = hmac.new(_secret(), normalized.encode("utf-8"), sha256).hexdigest()
    return digest[:TOKEN_LENGTH]


def asset_url(asset_key: str) -> str:
    """The root-relative URL for a mirrored asset, signed when it must be.

    Returns ``""`` for an empty key so a template renders no ``src`` rather
    than one pointing at the site root.
    """
    normalized = (asset_key or "").lstrip("/")
    if not normalized:
        return ""
    if not needs_token(normalized):
        return f"/{normalized}"
    return f"/{normalized}?{TOKEN_PARAM}={asset_token(normalized)}"


def token_is_valid(asset_key: str, token: str) -> bool:
    """Constant-time check, for the tests and any origin-side use."""
    return hmac.compare_digest(asset_token(asset_key), token or "")
