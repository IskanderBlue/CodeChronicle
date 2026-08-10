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

from django.conf import settings

from config.assets import SIGNED_PREFIXES

#: Query parameter carrying the token.  Short, because it goes on every scan.
TOKEN_PARAM = "s"

#: Hex characters kept from the digest.  128 bits — far beyond guessing, and
#: it keeps the URL readable in a citation or a print footer.
TOKEN_LENGTH = 32


def _secret() -> bytes:
    """The shared secret, as bytes.

    Falls back to ``SECRET_KEY`` so a developer checkout needs no extra
    configuration.  Production sets ``ASSET_SIGNING_KEY`` to the same value
    the Worker holds; if the two disagree every scan 403s, which is loud.
    """
    key = getattr(settings, "ASSET_SIGNING_KEY", "") or settings.SECRET_KEY
    return key.encode("utf-8")


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
