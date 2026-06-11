"""Free-tier content gate — the single source of truth for tier scoping.

Free users (anonymous and signed-in non-Pro alike) are limited to the
editions named in ``settings.FREE_TIER_CODE_NAMES``; Pro users (active
subscription or ``pro_courtesy``) are unrestricted.  Every gated surface —
search execution, viewer partials, provision permalinks, regulation detail,
edition chain — calls these helpers rather than re-deriving tier logic.

The whole gate is inert until ``settings.FREE_TIER_GATING_ENABLED`` is
flipped on (see the go-live checklist in tasks/free-tier-obc2006-scope.md).

Locked content renders as a teaser with an upgrade CTA, not a silent
omission: free users should see that other editions exist.
"""

from typing import Any

from django.conf import settings


def user_is_unrestricted(user: Any) -> bool:
    """True when ``user`` may access every edition.

    Always true while gating is disabled.  ``user`` may be a ``User``,
    ``AnonymousUser``, or ``None`` (the service layer passes ``None`` for
    anonymous searches).
    """
    if not settings.FREE_TIER_GATING_ENABLED:
        return True
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "has_active_subscription", False))


def free_tier_code_names() -> frozenset[str]:
    """The canonical edition names (``CodeEdition.code_name``) in free scope."""
    return frozenset(settings.FREE_TIER_CODE_NAMES)


def edition_allowed(user: Any, code_name: str) -> bool:
    """May ``user`` access the edition named ``code_name`` (e.g. "OBC_2006")?"""
    return user_is_unrestricted(user) or code_name in free_tier_code_names()


def partition_results(
    user: Any, results: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Split search results into (allowed, locked-count-per-edition).

    Each result dict carries its edition under ``code_edition``.  The counts
    let the UI say "N results in OBC 2012 — available on Pro" instead of
    silently returning less.  Unrestricted users get everything back with no
    counts, so callers can pass the counts straight to the template.
    """
    if user_is_unrestricted(user):
        return results, {}
    allowed_names = free_tier_code_names()
    kept: list[dict[str, Any]] = []
    locked: dict[str, int] = {}
    for result in results:
        name = result.get("code_edition", "")
        if name in allowed_names:
            kept.append(result)
        else:
            locked[name] = locked.get(name, 0) + 1
    return kept, locked
