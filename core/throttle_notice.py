"""Tell us when an account runs past its daily API allowance.

The allowance no longer refuses anybody (``api.auth.apply_search_throttle``);
it only slows them down.  That makes the notice the point.  Nothing stops a
caller now, so the operator is the control: a person reads the message, looks
at the account, and decides whether it is a busy subscriber or somebody
recording the corpus.  This is the same "detection, not prevention" rule the
rest of the anti-copying work follows.

Three rules hold this together:

* **A notice must never break a search.**  Every failure is swallowed.  The
  caller is a paying subscriber whose request is valid; a slow mail host must
  not turn their answer into a 500.  Same reasoning as
  ``core.signup_notice`` and ``core.auth_audit``.
* **Once per account per UTC day.**  The trigger fires on every search past
  the line, and an account that runs a thousand of them must produce one
  message, not eight hundred.  The ``EngagementEvent`` row written here is
  what remembers that, so the count survives a restart and a second worker.
* **It says what we already know.**  The address, the count, the delay now in
  force, and where to look.  Nothing is inferred.

The recipient list is ``settings.API_THROTTLE_NOTICE_EMAILS``.  Empty switches
the notice off, which is what a local run wants.
"""

from __future__ import annotations

from typing import Any

from coloured_logger import Logger
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from core.models import EngagementEvent

logger = Logger(__name__)


def _already_notified_today(user: Any) -> bool:
    """Whether this account has already produced a notice since UTC midnight.

    Read against ``EngagementEvent`` rather than a cache: the row is also the
    record that the throttle bound at all, and a record that a restart can
    lose is not a record.
    """
    midnight = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return EngagementEvent.objects.filter(
        user=user,
        event_type=EngagementEvent.EventType.API_THROTTLE,
        timestamp__gte=midnight,
    ).exists()


def _throttle_body(user: Any, used: int, delay: float) -> str:
    """What we know, in the order it is useful.

    The delay is included because it says how hard the throttle is biting,
    which the count alone does not: the wait grows with the overage and stops
    at a ceiling, so a long wait means somebody is well past the line rather
    than just over it.
    """
    return "\n".join(
        [
            f"{user.email} has passed the daily API search allowance.",
            "",
            f"When:     {timezone.now().isoformat(timespec='seconds')}",
            f"Searches: {used} today",
            f"Delay:    {delay:.0f}s on each further search",
            "",
            "Nothing has been refused. The account keeps working, more slowly.",
            "",
            "A heavy day and a bulk copy look the same in this number, so the",
            "question is what the account is fetching, not how much:",
            "",
            "  /insights/  — API coverage, the new-vs-repeat share",
            "",
            "A share near 100% new, climbing in a straight line, is a copy.",
            "A consultant returns to the same provisions and flattens out.",
        ]
    )


def notify_api_throttle(user: Any, *, used: int, delay: float) -> None:
    """Record the throttle and, on the first one today, send the notice.

    Safe to call on every throttled search.  The record is written first, so a
    mail failure still leaves the evidence that the throttle bound.
    """
    try:
        if _already_notified_today(user):
            return

        EngagementEvent.objects.create(
            user=user,
            event_type=EngagementEvent.EventType.API_THROTTLE,
            context={"searches_today": used, "delay_seconds": delay},
        )

        recipients = list(getattr(settings, "API_THROTTLE_NOTICE_EMAILS", []))
        if not recipients:
            return

        send_mail(
            subject=f"[CodeChronicle] {user.email} is past the API allowance",
            message=_throttle_body(user, used, delay),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - a notice must never break a search
        logger.warning("Could not send the API throttle notice: %s", exc)
