"""Who is calling the direct API.

The paid endpoints — ``/api/search``, ``/api/codes``, ``/api/history`` — take
an API key in an ``Authorization: Bearer`` header and nothing else.  A signed-in
browser session is not a credential here; see :class:`core.models.ApiKey` for
why.  ``/api/health`` and ``/api/event`` are open and never reach this module.

Every refusal answers in the product's envelope (``success``/``error``/``meta``)
rather than the framework's default, so one client can read every response the
API gives it.
"""

from __future__ import annotations

import secrets
import time
from datetime import timedelta

from coloured_logger import Logger
from django.utils import timezone

from accounts.access import api_access_allowed
from core.models import ApiKey, SearchHistory, User
from telemetry.throttle_notice import notify_api_throttle

logger = Logger(__name__)

#: The scheme the header must use.  Case-insensitive, because clients differ.
BEARER_SCHEME = "bearer"

#: How stale ``last_used_at`` may get before a request refreshes it.  The
#: stamp answers "is anything still calling with this key?", which a minute
#: cannot change the answer to, and this keeps a busy key from writing a row
#: on every request.
LAST_USED_RESOLUTION = timedelta(minutes=1)

#: What the reader does about it, on every refusal.
_HELP = {"docs_url": "/api/docs", "keys_url": "/settings/#api", "upgrade_url": "/pricing/"}

#: Searches one account may run through the API in a UTC day before every
#: further search is made to wait.
#:
#: **Past this number the API slows down; it never refuses.**  It was a hard
#: 429, and a hard stop is the wrong shape for both cases it meets.  A busy
#: subscriber on a deadline is stopped dead by a number nobody warned them
#: about, and a bulk copier simply comes back tomorrow — the corpus is small
#: enough that a wall costs them a day and costs us a customer.
#:
#: A throttle changes both.  Legitimate use is unaffected in practice, because
#: a consultant asks a handful of questions per matter and never reaches this
#: line.  Somebody recording the corpus meets a rate they cannot outrun,
#: keeps working, and leaves a record of doing it while we watch.
#:
#: **This remains a cost control, not an anti-copying one.**  Each search
#: costs a language-model parse, and the delay is what stops a key being an
#: open tap on that bill.  A search returns up to ``SEARCH_RESULT_CAP`` (100)
#: full provision texts, and only 8,865 versions carry text at all — so the
#: corpus fits inside one or two days of any allowance a real customer could
#: live with, and no threshold tells a heavy day from a copy.  What answers
#: copying is the record (``SearchHistory.source``, ``ProvisionFetch``), the
#: Terms, and the revoke.
API_SEARCHES_BEFORE_THROTTLE = 200

#: How much longer each search past the line waits, in seconds.  The delay
#: grows with the overage — the first search past the line waits one step, the
#: tenth waits ten — so the rate falls away the further somebody goes rather
#: than sitting at one flat penalty a script can plan around.
API_THROTTLE_STEP_SECONDS = 2.0

#: The longest any one search waits.  A request that sleeps holds a worker for
#: the whole delay, and one that outlives the gateway timeout is a 502 rather
#: than a slow answer — which is a hard failure again, by accident.  At the
#: ceiling the account is held to roughly three searches a minute, which is
#: far below any bulk rate and far above a person's.
API_THROTTLE_MAX_SECONDS = 20.0


def bearer_token(request) -> str | None:
    """The token from the ``Authorization`` header, or ``None`` when absent.

    An unparsable header is treated as no token, so the caller answers the
    same "send a key" message either way.  Telling a caller *how* their header
    was wrong helps nobody who is not guessing at keys.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != BEARER_SCHEME:
        return None
    return token.strip() or None


def resolve_key(token: str) -> ApiKey | None:
    """The live key this token names, or ``None``.

    Looks up the clear prefix, then compares hashes with
    ``secrets.compare_digest`` so the time taken says nothing about how much
    of a guess was right.  A revoked key resolves to ``None``: revoking is the
    control an operator reaches for when a key leaks, so it has to act at once.
    """
    candidates = ApiKey.objects.filter(
        lookup=token[: ApiKey.LOOKUP_LENGTH], revoked_at__isnull=True
    ).select_related("user")
    digest = ApiKey.hash_token(token)
    for key in candidates:
        if secrets.compare_digest(key.hashed_key, digest):
            return key
    return None


def stamp_used(key: ApiKey) -> None:
    """Record that the key was used, at ``LAST_USED_RESOLUTION`` granularity."""
    now = timezone.now()
    if key.last_used_at is None or now - key.last_used_at >= LAST_USED_RESOLUTION:
        key.last_used_at = now
        key.save(update_fields=["last_used_at"])


def require_api_key(request):
    """``None`` when the caller may proceed; otherwise ``(status, envelope)``.

    On success it sets ``request.user`` to the key's owner, so the endpoints
    attribute the search and read the history against a real account exactly
    as the website does.

    Three refusals, and they are different questions:

    - **No key.** 401. The caller has not said who they are.
    - **A key that resolves to nothing.** 401, with the same wording as a
      revoked one. Whether a key ever existed is not the caller's business.
    - **A key whose owner may not use the API.** 403. A key outlives the
      subscription that justified it, so this is the state a lapsed customer
      meets, and it is fixed by paying rather than by a new key. A deactivated
      account lands here too — ``accounts.access.api_access_allowed`` is what
      decides, and it is the rule every other Pro surface uses.
    """
    token = bearer_token(request)
    if token is None:
        return 401, {
            "success": False,
            "results": [],
            "error": (
                "This endpoint needs an API key. Send it as "
                "'Authorization: Bearer <key>'."
            ),
            "meta": _HELP,
        }

    key = resolve_key(token)
    if key is None:
        return 401, {
            "success": False,
            "results": [],
            "error": "That API key is not valid. It may have been revoked.",
            "meta": _HELP,
        }

    if not api_access_allowed(key.user):
        return 403, {
            "success": False,
            "results": [],
            "error": (
                "The account this key belongs to does not have an active Pro "
                "subscription."
            ),
            "meta": _HELP,
        }

    stamp_used(key)
    request.user = key.user
    return None


def searches_today(user: User) -> int:
    """API searches this account has run since UTC midnight.

    Counts the account, not the key, so a second key does not buy a second
    allowance.  Counts ``source="api"`` rows only: reading on the website is
    unlimited for a subscriber and must not spend an API allowance.
    """
    midnight = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return SearchHistory.objects.filter(
        user=user, source=SearchHistory.Source.API, timestamp__gte=midnight
    ).count()


def throttle_delay(used: int) -> float:
    """Seconds this search waits, given how many ran before it today.

    Zero inside the allowance.  Past it the wait grows one step per search and
    stops at the ceiling, so the answer is always bounded and a caller never
    meets a hung request.
    """
    over = used - API_SEARCHES_BEFORE_THROTTLE
    if over < 0:
        return 0.0
    return min((over + 1) * API_THROTTLE_STEP_SECONDS, API_THROTTLE_MAX_SECONDS)


def apply_search_throttle(request) -> None:
    """Slow this search if the account is past its daily allowance.

    Called after :func:`require_api_key`, and only on ``/api/search`` — the
    allowance is on the searches, which each cost a language-model parse and
    answer with up to a hundred provisions.  Reading ``/api/codes`` costs
    neither.

    **It never refuses.**  The caller always gets their answer; the only thing
    that changes is when.  See ``API_SEARCHES_BEFORE_THROTTLE`` for why a wall
    was the wrong shape.

    The wait happens before the query is read, so a caller over the line waits
    the same whatever they sent, and the parse is not paid for twice.
    """
    used = searches_today(request.user)
    delay = throttle_delay(used)
    if delay <= 0:
        return

    # The notice goes out before the wait, not after: the operator wants to
    # know that it is happening, and a message that arrives twenty seconds
    # late is twenty seconds later than it needed to be.  It is also written
    # once per account per day, so it must not depend on this request
    # finishing.
    notify_api_throttle(request.user, used=used, delay=delay)

    logger.info(
        "Throttling API search for %s: %s used today, waiting %.1fs",
        request.user.email,
        used,
        delay,
    )
    time.sleep(delay)
