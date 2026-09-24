"""Cloudflare Turnstile on the forms that send an email to a typed address.

Signup and password reset each send an email to whatever address is typed in,
so a bot can use them to fill a stranger's inbox (subscription bombing).  The
check runs in the form's ``clean()``, which is before allauth creates a user
or sends anything: a refused POST sends no email.  After ``save()`` the email
is already out, and nothing can take it back.

The browser gets a token from Cloudflare and posts it as
``cf-turnstile-response``.  The server redeems it at siteverify, once.  A
token passes only when all three hold: ``success``, the form's own
``action``, and a ``hostname`` on the allowlist.  The action stops a token
solved on one form from opening the other; the hostname stops a token solved
on somebody else's page that carries our public site key.

An empty ``TURNSTILE_SECRET_KEY`` switches the check off.  That is what a
developer checkout and the test suite want.  A deployed instance must not run
without it, and ``check_turnstile_secret`` refuses the deploy.
"""

import json
import urllib.parse
import urllib.request
from typing import Any

from django import forms
from django.conf import settings
from django.core.checks import CheckMessage, Error

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TOKEN_FIELD = "cf-turnstile-response"

#: Cloudflare's own limit on a token.  Anything longer is not a token.
MAX_TOKEN_LENGTH = 2048

SITEVERIFY_TIMEOUT_SECONDS = 10

REFUSAL = (
    "We could not confirm that a person sent this form. Reload the page, then "
    "send the form again. If you use a content blocker, allow "
    "challenges.cloudflare.com."
)


def is_enabled() -> bool:
    return bool(settings.TURNSTILE_SECRET_KEY)


def siteverify(token: str) -> dict:
    """Redeem ``token`` at Cloudflare and return the answer.

    Raises on a network fault, a timeout or a non-2xx answer; the caller
    treats every one of those as a refusal.
    """
    body = urllib.parse.urlencode(
        {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    ).encode()
    request = urllib.request.Request(
        SITEVERIFY_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=SITEVERIFY_TIMEOUT_SECONDS) as response:
        return json.load(response)


def token_passes(token: object, action: str) -> bool:
    """Is ``token`` a fresh Turnstile answer, solved on this form, on our site?

    Fails closed.  A missing token, an oversized one, an unreachable
    Cloudflare and an unexpected answer all refuse, because an open fallback
    is the path a bot would take.
    """
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
        return False
    try:
        result = siteverify(token)
    except Exception:
        return False
    return (
        result.get("success") is True
        and result.get("action") == action
        and result.get("hostname") in settings.TURNSTILE_HOSTNAMES
    )


class TurnstileMixin(forms.Form):
    """Refuse the POST unless it carries a Turnstile token that passes.

    Put it first in the bases, so its ``clean()`` runs on the way back up
    whatever the form below it does.  ``turnstile_action`` must equal the
    widget's ``data-action`` in the template.
    """

    turnstile_action: str = ""

    @property
    def turnstile_site_key(self) -> str:
        """The key the template renders the widget with; empty when switched off."""
        return settings.TURNSTILE_SITE_KEY if is_enabled() else ""

    def clean(self) -> dict[str, Any]:
        super().clean()
        if is_enabled() and not token_passes(self.data.get(TOKEN_FIELD), self.turnstile_action):
            raise forms.ValidationError(REFUSAL, code="turnstile")
        return self.cleaned_data


def check_turnstile_secret(app_configs: object, **kwargs: object) -> list[CheckMessage]:
    """Refuse to start a deployed instance with the check switched off.

    An empty secret does not break anything a reader can see: the forms work
    and the bots get through, which is the failure this module exists to
    stop.  So the deploy has to say it, the way ``core.E001`` does for the
    asset-signing key.  ``DEBUG`` is exempt, because off is what a developer
    checkout wants.
    """
    secret = getattr(settings, "TURNSTILE_SECRET_KEY", "")
    if settings.DEBUG or secret:
        return []
    return [
        Error(
            "TURNSTILE_SECRET_KEY is empty, so signup and password reset would "
            "send an email to any address a bot types in.",
            hint=(
                "Set TURNSTILE_SECRET_KEY in the app_runtime_secrets bundle to the "
                "secret of the Turnstile widget whose site key is TURNSTILE_SITE_KEY."
            ),
            id="accounts.E001",
        )
    ]
