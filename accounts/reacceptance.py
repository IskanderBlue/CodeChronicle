"""Whether a signed-in reader still stands on the documents now in force.

The Terms promise notice before a material change, and that promise is worth
what the machinery behind it is worth. ``TermsAcceptance`` already anticipated
this — it is append-only "so the full history is preserved", and its docstring
names a "future re-acceptance prompt". This module is that prompt's rule.

Four decisions worth keeping:

* **Not every bump asks again.** A typo fix and a new audit right are both a
  new version, and treating them alike either trains readers to click past the
  prompt or leaves a material change unaccepted. ``TERMS_REACCEPT_FROM`` and
  ``PRIVACY_REACCEPT_FROM`` name the earliest version that still counts as
  accepted; a minor edit moves ``TERMS_VERSION`` and leaves the floor alone.
* **The two documents are asked for together, and recorded apart.** One
  screen, because two consecutive walls to read one email's worth of change is
  worse for the reader; two stamps on the row, because the documents change
  independently and the record must say which text the reader actually saw.
* **The versions are ISO dates**, so a string comparison is a date comparison.
  Anything that is not one sorts before every date and therefore asks again,
  which is the safe direction.
* **No acceptance row at all means no prompt.** Accounts made before the
  clickwrap existed, and accounts made by a script, have nothing to re-affirm
  and would otherwise be trapped at the wall with no way to have been at fault.
  Those are the operator's problem, not a reader's.

Not to be confused with ``User.has_accepted_terms`` and
``User.has_accepted_privacy``, which predate this and answer a different
question: whether a user has ever accepted one *exact* version string. That is
the right test for "did this person agree to this text" and the wrong one for a
wall, because it asks again after a typo fix. Use those to prove a specific
acceptance; use :func:`outstanding` to decide whether to ask.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

#: Session key holding the versions this session has already been cleared for.
#: The check is one indexed query, but it would run on every request of every
#: signed-in reader, and the answer only changes when the reader accepts or the
#: operator moves a floor — both of which invalidate it explicitly.
ACCEPTED_VERSIONS_SESSION_KEY = "accepted_versions"


def _current() -> str:
    """The marker that says "this session has accepted what is in force"."""
    return f"{settings.TERMS_VERSION}|{settings.PRIVACY_VERSION}"


def _stale(accepted: str, floor: str) -> bool:
    """Is ``accepted`` older than ``floor``? Blank counts as older."""
    return not accepted or accepted < floor


def outstanding(user: Any) -> tuple[bool, bool]:
    """``(terms, privacy)`` — which documents this user must accept again.

    ``(False, False)`` for an anonymous user, for a user with no acceptance on
    record, and for one whose latest acceptance clears both floors.
    """
    if not getattr(user, "is_authenticated", False):
        return (False, False)
    latest = user.latest_terms_acceptance
    if latest is None:
        return (False, False)
    return (
        _stale(latest.terms_version, settings.TERMS_REACCEPT_FROM),
        _stale(latest.privacy_version, settings.PRIVACY_REACCEPT_FROM),
    )


def needs_reacceptance(request: Any) -> bool:
    """Whether this request should be sent to the re-acceptance page.

    Answers from the session where it can, and only asks the database when the
    session carries no verdict for the versions currently in force.
    """
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return False
    session = getattr(request, "session", None)
    if session is not None and session.get(ACCEPTED_VERSIONS_SESSION_KEY) == _current():
        return False
    terms, privacy = outstanding(user)
    if terms or privacy:
        return True
    if session is not None:
        session[ACCEPTED_VERSIONS_SESSION_KEY] = _current()
    return False


def mark_accepted(session: Any) -> None:
    """Record in the session that this reader is clear of the prompt."""
    session[ACCEPTED_VERSIONS_SESSION_KEY] = _current()
