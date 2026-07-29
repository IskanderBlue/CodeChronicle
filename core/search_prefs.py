"""The reader's stored relevance floor.

Two stores behind one pair of helpers: a ``User`` field when signed in, the
session otherwise.  Anonymous searches are capped at one a day, so the session
is plenty — the preference doesn't warrant an account, and it survives long
enough to matter within a visit.

There is deliberately only one preference.  A page-size control and a relevance
floor are two ways of asking how much you see, and two such controls can
disagree on screen; the floor decides, and ``SEARCH_RESULT_CAP`` is a backstop
rather than a choice.
"""

from typing import Any

from django.http import HttpRequest

from config.search_limits import coerce_match_threshold

#: Session key for an anonymous reader's floor.  Same name as the model field
#: and the form field, so the three can't drift apart.
SESSION_KEY = "match_threshold"


def resolve_match_threshold(request: HttpRequest) -> float:
    """The floor this request should search at.

    Present in the POST -> the reader just moved the line, so persist it;
    absent -> read back whatever they last set.  Returns the coerced value, not
    the raw one: silently storing a coercion while rendering the raw request is
    how a control ends up disagreeing with the list beneath it.
    """
    if request.method == "POST" and SESSION_KEY in request.POST:
        return _store(request, request.POST[SESSION_KEY])

    user: Any = request.user
    if getattr(user, "is_authenticated", False):
        return coerce_match_threshold(getattr(user, SESSION_KEY, None))
    return coerce_match_threshold(request.session.get(SESSION_KEY))


def _store(request: HttpRequest, value: object) -> float:
    stored = coerce_match_threshold(value)
    user: Any = request.user
    if getattr(user, "is_authenticated", False):
        if getattr(user, SESSION_KEY) != stored:
            setattr(user, SESSION_KEY, stored)
            user.save(update_fields=[SESSION_KEY])
    else:
        request.session[SESSION_KEY] = stored
    return stored
