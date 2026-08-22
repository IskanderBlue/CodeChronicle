"""The re-acceptance wall: the page that keeps the notice promise.

The Terms say we give notice before a material change and ask you to accept
the new documents the next time you sign in. This is the asking. The email is
somebody's job, not this module's.

Three rules:

* **Nothing is recorded until the reader submits.** Arriving at the wall is
  not acceptance, and neither is reading it. The row is written on the POST,
  with the same fields the signup clickwrap writes, because the two events are
  the same kind of evidence and a lawyer reading the table should not have to
  tell them apart by shape.
* **``next`` is validated against this host.** The wall stands in front of
  every page, so it is handed a destination on every request, which is exactly
  the shape an open redirect takes.
* **The wall can be left.** A reader who will not accept can sign out, and the
  page says so and links it. A wall with no exit is a wall that takes an
  account hostage over a document the reader is entitled to refuse.
"""

from __future__ import annotations

from typing import cast

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from core.ip_utils import extract_client_ip
from core.models import TermsAcceptance, User
from core.reacceptance import mark_accepted, outstanding

#: Where a reader lands after accepting, when nothing better is known.
DEFAULT_NEXT = "core:search"


def _safe_next(request: HttpRequest) -> str:
    """The destination to return to, or the default if it is not ours."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse(DEFAULT_NEXT)


@login_required
def accept_terms(request: HttpRequest) -> HttpResponse:
    """Show what changed and record the reader's acceptance of it."""
    user = cast(User, request.user)
    terms_stale, privacy_stale = outstanding(user)

    # Nothing outstanding: the reader followed a stale link, or accepted in
    # another tab.  Send them on rather than showing a wall with nothing
    # behind it.
    if not (terms_stale or privacy_stale):
        mark_accepted(request.session)
        return redirect(_safe_next(request))

    if request.method == "POST":
        if not request.POST.get("accepted"):
            return render(
                request,
                "accept_terms.html",
                _context(request, terms_stale, privacy_stale, unchecked=True),
                status=400,
            )
        TermsAcceptance.objects.create(
            user=user,
            email=user.email,
            terms_version=settings.TERMS_VERSION,
            privacy_version=settings.PRIVACY_VERSION,
            ip_address=extract_client_ip(request.META),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )
        mark_accepted(request.session)
        return redirect(_safe_next(request))

    return render(
        request, "accept_terms.html", _context(request, terms_stale, privacy_stale)
    )


def _context(
    request: HttpRequest,
    terms_stale: bool,
    privacy_stale: bool,
    *,
    unchecked: bool = False,
) -> dict[str, object]:
    """What the wall needs to name the documents and come back here."""
    return {
        "terms_stale": terms_stale,
        "privacy_stale": privacy_stale,
        "terms_version": settings.TERMS_VERSION,
        "privacy_version": settings.PRIVACY_VERSION,
        "next": _safe_next(request),
        # Set only after a submit with the box unticked, so the page does not
        # open by telling a reader off for something they have not done.
        "unchecked": unchecked,
        "meta_title": "Updated Terms — CodeChronicle",
    }
