"""Tell us when somebody creates an account.

At this size every signup is an event worth knowing about on the day it
happens, not on the day somebody next opens ``/insights/``.  A new account is
the only unprompted signal a reader gives us that the product was worth
returning to, and it is the opening for the conversation the price depends on
(``tasks/ao-first-customer-conversations.md``).

Two rules hold this together:

* **A notice must never break a signup.**  The receiver swallows everything.
  Somebody who has just given us their email and password must not meet a 500
  because our mail host was slow, and the account is already created by the
  time this runs — so a failure here would lose the notice *and* leave the
  reader thinking the signup failed.  Same reasoning as ``accounts.signals.auth_audit``.
* **It says what we already know.**  The address, the time, where they came
  from, and how many accounts there now are.  Nothing is inferred, and
  nothing is asked of the reader to produce it.

The recipient list is ``settings.SIGNUP_NOTICE_EMAILS``.  Empty switches the
notice off, which is what a local run wants.

Wired for side effects in ``CoreConfig.ready`` (``core.apps``).
"""

from __future__ import annotations

from typing import Any

from allauth.account.signals import user_signed_up
from coloured_logger import Logger
from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver
from django.http import HttpRequest
from django.utils import timezone

from core.models import User
from shared.ip import client_ip

logger = Logger(__name__)


def _body(user: Any, request: HttpRequest | None) -> str:
    """What we know, in the order it is useful.

    The running total is included because one signup means little and the
    shape of the line means a lot — the number is the reason to open this
    message rather than file it.
    """
    lines = [
        f"{user.email} created an account.",
        "",
        f"When:  {timezone.now().isoformat(timespec='seconds')}",
        f"From:  {client_ip(request) or 'unknown'}",
    ]

    # The count is nice to have, never worth failing over: this runs inside a
    # signup, and a slow or broken count must not cost us the notice itself.
    try:
        lines.append(f"Total: {User.objects.count()} accounts")
    except Exception as exc:  # noqa: BLE001
        logger.error("Signup notice could not count accounts: %s", exc)

    return "\n".join(lines)


@receiver(user_signed_up)
def handle_user_signed_up(sender, request=None, user=None, **kwargs) -> None:
    """Send one plain-text notice per new account.

    ``user_signed_up`` is allauth's own signal and fires once, when the
    account is created — not on each later login, and not again when the
    address is confirmed.  Django's ``post_save`` on the user model would also
    fire for every profile edit and for accounts made by a management command,
    which is why this hooks allauth rather than the model.
    """
    recipients = getattr(settings, "SIGNUP_NOTICE_EMAILS", [])
    if not recipients or user is None:
        return

    try:
        send_mail(
            subject=f"New CodeChronicle account: {user.email}",
            message=_body(user, request),
            from_email=None,  # DEFAULT_FROM_EMAIL
            recipient_list=list(recipients),
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 — a notice is never fatal to a signup
        logger.error("Error sending signup notice for %s: %s", user.email, exc)
