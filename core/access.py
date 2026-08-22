"""Who may see what — the single source of truth for tier scoping.

Free users (anonymous and signed-in non-Pro alike) are limited to the
editions named in ``settings.FREE_TIER_CODE_NAMES``; Pro users (active
subscription or ``pro_courtesy``) are unrestricted.  Every gated surface —
search execution, viewer partials, provision permalinks, regulation detail,
edition chain — calls these helpers rather than re-deriving tier logic.

Locked content renders as a teaser with an upgrade CTA, not a silent
omission: free users should see that other editions exist.
"""

from collections.abc import Callable
from typing import Any

from django.conf import settings

#: The tier gate, with the reader already answered.  Takes a
#: ``CodeEdition.code_name`` and says whether this reader may open it.
#:
#: This is the form the gate travels in.  A module that reasons about the code
#: text — lineage, comparison, the version axis — must not import this one, or
#: "what a tier is" ends up defined in two places.  It takes the question
#: instead, already closed over the reader.
EditionGate = Callable[[str], bool]


def is_staff(user: Any) -> bool:
    """True when ``user`` may open an operator-only page.

    A different axis from the tier rules below — this one is about who runs
    the product, not who pays for it — but the same kind of question, asked of
    the same object, and it belongs where the answer cannot be given twice.

    ``is_active`` is tested as well as ``is_staff``, because deactivating an
    account is how staff access is taken away, and a stale session must not
    outlive that.  ``Any`` because the check also meets ``AnonymousUser``.
    """
    return bool(getattr(user, "is_active", False) and getattr(user, "is_staff", False))


def user_is_unrestricted(user: Any) -> bool:
    """True when ``user`` may access every edition.

    ``user`` may be a ``User``, ``AnonymousUser``, or ``None`` (the service
    layer passes ``None`` for anonymous searches).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "has_active_subscription", False))


def api_access_allowed(user: Any) -> bool:
    """True when ``user`` may call the direct API.

    The same subscription rule as every other Pro surface, plus one test the
    website never needs: an account that has been deactivated cannot sign in,
    so a page gate never meets one — but an API key is a standing credential
    and would go on working.  It is checked here so deactivating an account
    ends its API access too.
    """
    return bool(user is not None and getattr(user, "is_active", False)) and (
        user_is_unrestricted(user)
    )


def free_tier_code_names() -> frozenset[str]:
    """The canonical edition names (``CodeEdition.code_name``) in free scope."""
    return frozenset(settings.FREE_TIER_CODE_NAMES)


def edition_allowed(user: Any, code_name: str) -> bool:
    """May ``user`` access the edition named ``code_name`` (e.g. "OBC_2006")?"""
    return user_is_unrestricted(user) or code_name in free_tier_code_names()


def edition_gate(user: Any) -> EditionGate:
    """The gate for ``user``, as a question that can be asked many times.

    :func:`edition_allowed` answers one edition for one reader and re-reads
    ``settings.FREE_TIER_CODE_NAMES`` every call.  A caller filtering a version
    list pays that per row.  This resolves the reader's scope once and hands
    back the test, which is also what lets a module that knows nothing about
    tiers apply one.
    """
    allowed = allowed_edition_names(user)
    if allowed is None:
        return lambda _code_name: True
    return lambda code_name: code_name in allowed


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
