"""Free-tier content gate — the single source of truth for tier scoping.

Free users (anonymous and signed-in non-Pro alike) are limited to the
editions named in ``settings.FREE_TIER_CODE_NAMES``; Pro users (active
subscription or ``pro_courtesy``) are unrestricted.  Every gated surface —
search execution, viewer partials, provision permalinks, regulation detail,
edition chain — calls these helpers rather than re-deriving tier logic.

Locked content renders as a teaser with an upgrade CTA, not a silent
omission: free users should see that other editions exist.
"""

from typing import Any

from django.conf import settings


def user_is_unrestricted(user: Any) -> bool:
    """True when ``user`` may access every edition.

    ``user`` may be a ``User``, ``AnonymousUser``, or ``None`` (the service
    layer passes ``None`` for anonymous searches).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "has_active_subscription", False))


def free_tier_code_names() -> frozenset[str]:
    """The canonical edition names (``CodeEdition.code_name``) in free scope."""
    return frozenset(settings.FREE_TIER_CODE_NAMES)


def edition_allowed(user: Any, code_name: str) -> bool:
    """May ``user`` access the edition named ``code_name`` (e.g. "OBC_2006")?"""
    return user_is_unrestricted(user) or code_name in free_tier_code_names()


def allowed_edition_names(user: Any) -> frozenset[str] | None:
    """The editions ``user`` may open, or ``None`` when unrestricted.

    Handed to the search orchestrator so the tier split happens *before* the
    display limit is applied — a gated searcher's cards then come from what
    they can actually read.  ``None`` (rather than "every loaded name") keeps
    the Pro path free of a set membership test per result, and keeps this
    module the only thing that knows what a tier is.
    """
    if user_is_unrestricted(user):
        return None
    return free_tier_code_names()
