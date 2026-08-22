"""Demand capture — "which edition do you need?".

The only place a visitor can tell us about a code we do not carry.  It is not
a signup: the email field is optional, and a visitor who types "Alberta 2014"
and leaves has already given us the valuable half.

Posted by HTMX and answered with a fragment, so the band replaces itself in
place.  Deliberately not a full page: an ask that costs a navigation is an ask
most people will not make.
"""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.email_utils import clean_optional_email
from core.ip_utils import extract_client_ip
from core.models import EditionRequest, SearchHistory

#: Requests one IP may file per day.  A soft abuse ceiling, not a rate limit on
#: the product: an honest visitor files one, maybe two.  Silently accepting the
#: over-limit post (rather than showing an error) is deliberate — the abuser
#: learns nothing and the rare honest repeat visitor is not scolded.
MAX_REQUESTS_PER_IP_PER_DAY = 5

#: Longest text we store.  Matches the model field; enforced here so an
#: oversized post is truncated rather than raising.
MAX_CODE_TEXT = 200


@require_POST
def edition_request(request: HttpRequest) -> HttpResponse:
    """Record one "which edition do you need" submission."""
    code_text = (request.POST.get("code_text") or "").strip()[:MAX_CODE_TEXT]
    surface = request.POST.get("surface") or EditionRequest.Surface.LANDING
    if surface not in EditionRequest.Surface.values:
        surface = EditionRequest.Surface.LANDING

    if not code_text:
        return render(
            request,
            "partials/_edition_request.html",
            {"error": "Tell us the code and year, and we will record it.",
             "surface": surface},
        )

    user = request.user if request.user.is_authenticated else None
    ip = extract_client_ip(request.META) if user is None else None

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    over_limit = (
        ip is not None
        and EditionRequest.objects.filter(
            ip_address=ip, created_at__gte=today_start
        ).count() >= MAX_REQUESTS_PER_IP_PER_DAY
    )

    if not over_limit:
        EditionRequest.objects.create(
            code_text=code_text,
            email=clean_optional_email(request.POST.get("email", "")),
            user=user,
            ip_address=ip,
            surface=surface,
            search_id=_search_id(request.POST.get("search_id")),
        )

    return render(
        request,
        "partials/_edition_request.html",
        {"submitted": True, "code_text": code_text, "surface": surface},
    )


def _search_id(value: Any) -> int | None:
    """The originating search id, or ``None``.

    Checks the row exists rather than trusting the posted number: the value
    arrives from the page, and a stale or invented id on a real ``ForeignKey``
    would raise ``IntegrityError`` and lose the submission over a field that is
    only context.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0 or not SearchHistory.objects.filter(pk=parsed).exists():
        return None
    return parsed
