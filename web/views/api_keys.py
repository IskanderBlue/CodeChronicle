"""Where a subscriber issues and revokes their own API keys.

Both views live behind the same test the API itself makes
(``accounts.access.api_access_allowed``), so the page cannot hand out a key the
API will refuse.  A reader without a subscription sees no key section at all —
the pricing page
is where the feature is explained, and a control that only says "not for you"
explains nothing.

The plain token exists for one render.  ``create`` puts it in the session, the
settings page prints it once and takes it back out.  There is no second chance
by design: see :class:`core.models.ApiKey`.
"""

from __future__ import annotations

from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from accounts.access import api_access_allowed
from core.models import ApiKey, User
from web.views.settings_nav import API_KEYS_SECTION, settings_redirect

#: Session key carrying the one plain token, from the POST that made it to the
#: redirect that renders it.  Named for what it is, because anything left in a
#: session under a vague name outlives the reason for it.
NEW_TOKEN_SESSION_KEY = "new_api_key_token"

#: How many live keys one account may hold.  Not a licence limit — it is what
#: keeps "revoke the one that leaked" a decision a person can still make.
MAX_ACTIVE_KEYS = 5



@login_required
@require_POST
def create_api_key(request: HttpRequest) -> HttpResponse:
    """Issue a key, and hand back its only copy through the session."""
    # ``login_required`` has already refused an anonymous caller; the cast
    # states that for the type checker, which cannot read a decorator.
    user = cast(User, request.user)
    if not api_access_allowed(user):
        messages.error(request, "API keys need an active Pro subscription.")
        return settings_redirect(API_KEYS_SECTION)

    active = ApiKey.objects.filter(user=user, revoked_at__isnull=True).count()
    if active >= MAX_ACTIVE_KEYS:
        messages.error(
            request,
            f"You already have {MAX_ACTIVE_KEYS} active keys. "
            "Revoke one before you make another.",
        )
        return settings_redirect(API_KEYS_SECTION)

    name = (request.POST.get("name") or "").strip()
    _, token = ApiKey.generate(user, name)
    request.session[NEW_TOKEN_SESSION_KEY] = token
    return settings_redirect(API_KEYS_SECTION)


@login_required
@require_POST
def revoke_api_key(request: HttpRequest, pk: int) -> HttpResponse:
    """Stop a key working.

    Scoped to the signed-in user's own keys, so a guessed id reaches a 404
    rather than somebody else's credential.  A subscription is *not* required:
    a lapsed customer must still be able to turn off a key that leaked.
    """
    key = get_object_or_404(ApiKey, pk=pk, user=cast(User, request.user))
    key.revoke()
    messages.success(request, f'API key "{key.name}" is revoked.')
    return settings_redirect(API_KEYS_SECTION)
