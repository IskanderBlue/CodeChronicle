"""Reader reports — "this looks wrong" on a specific text.

Free for everybody, on purpose.  A reader who disputes a provision is doing
our verification for us, and the report is worth more than the friction of an
account would save.

Deliberately not a general contact form.  A report tied to a version is
actionable; "the dates look wrong somewhere" is not.  The form carries its
target in hidden fields, and ``report_problem`` refuses a submission that
names no target at all.

Posted by HTMX and answered with a fragment, so the panel replaces itself
inside the open dialog.  Same shape as ``web.views.demand`` — read that one
first; the two are meant to stay recognisably alike.
"""

from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import is_staff
from core.models import ProvisionFeedback
from shared.email import clean_optional_email
from shared.ip import extract_client_ip
from telemetry.insights import feedback_row

#: Reports one IP may file per day.  Higher than the edition-request ceiling
#: because a reader working through a chain may legitimately find several
#: faults in one sitting, and the failure we care about is a flood, not a
#: diligent afternoon.  Over-limit posts are accepted silently and discarded:
#: the abuser learns nothing, and the rare honest repeat reader is not scolded.
MAX_REPORTS_PER_IP_PER_DAY = 10

#: Longest note we store.  Long enough to quote a paragraph of the code and
#: say what is wrong with it.
MAX_NOTE = 4000


def _posted_version(raw: Any) -> int | None:
    """The posted version number, or ``None`` when absent or not a number."""
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _target(request: HttpRequest) -> dict[str, Any]:
    """The report's target, read from the form's hidden fields."""
    return {
        "code_edition": (request.POST.get("code_edition") or "").strip()[:50],
        "division": (request.POST.get("division") or "").strip()[:10],
        "provision_id": (request.POST.get("provision_id") or "").strip()[:50],
        "version": _posted_version(request.POST.get("version")),
        "reg_id": (request.POST.get("reg_id") or "").strip()[:50],
    }


def report_form(request: HttpRequest) -> HttpResponse:
    """The empty report form, fetched when the reader opens the dialog.

    The panel is not rendered with the page, and the reason is caching rather
    than weight.  The panel carries ``{% csrf_token %}``; rendering that tag
    makes Django attach ``Set-Cookie: csrftoken`` to the response, and a
    response carrying a cookie is one no shared cache will store.  One hidden
    form on a dialog nobody opened is enough to make every provision page
    uncacheable at the edge, which is most of what the corpus costs to serve.

    Fetching it here moves the cookie onto this request, which is never
    cached.  The reader sees the same dialog; it fills a moment later.

    The target arrives in the query string, the same pieces the hidden fields
    post back.  It is not checked against the corpus, because a report stores
    its target as text on purpose — see ``ProvisionFeedback`` — and a reader
    disputing a provision we hold wrongly must still be able to name it.
    """
    surface = request.GET.get("surface") or ProvisionFeedback.Surface.PERMALINK
    if surface not in ProvisionFeedback.Surface.values:
        surface = ProvisionFeedback.Surface.PERMALINK
    return render(
        request,
        "partials/_report_problem_panel.html",
        {
            "surface": surface,
            "code_edition": (request.GET.get("code_edition") or "").strip()[:50],
            "division": (request.GET.get("division") or "").strip()[:10],
            "provision_id": (request.GET.get("provision_id") or "").strip()[:50],
            "version": _posted_version(request.GET.get("version")),
            "reg_id": (request.GET.get("reg_id") or "").strip()[:50],
        },
    )


@require_POST
def report_problem(request: HttpRequest) -> HttpResponse:
    """Record one "this looks wrong" report."""
    target = _target(request)
    surface = request.POST.get("surface") or ProvisionFeedback.Surface.PERMALINK
    if surface not in ProvisionFeedback.Surface.values:
        surface = ProvisionFeedback.Surface.PERMALINK

    # A report with no target cannot be triaged, and the form always carries
    # one, so this is a malformed post rather than a reader mistake.  Answered
    # as a 400 and not as a form error: there is no field the reader could fix.
    if not target["code_edition"] or not (target["provision_id"] or target["reg_id"]):
        return HttpResponseBadRequest("A report must name what it is about.")

    note = (request.POST.get("note") or "").strip()[:MAX_NOTE]
    context: dict[str, Any] = {"surface": surface, **target}

    if not note:
        return render(
            request,
            "partials/_report_problem_panel.html",
            {**context, "error": "Tell us what is wrong, and we will look at it."},
        )

    user = request.user if request.user.is_authenticated else None
    ip = extract_client_ip(request.META) if user is None else None

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    over_limit = (
        ip is not None
        and ProvisionFeedback.objects.filter(
            ip_address=ip, created_at__gte=today_start
        ).count() >= MAX_REPORTS_PER_IP_PER_DAY
    )

    if not over_limit:
        ProvisionFeedback.objects.create(
            note=note,
            email=clean_optional_email(request.POST.get("email", "")),
            user=user,
            ip_address=ip,
            surface=surface,
            **target,
        )

    return render(
        request,
        "partials/_report_problem_panel.html",
        {**context, "submitted": True},
    )


@user_passes_test(is_staff)
@require_POST
def feedback_status(request: HttpRequest, pk: int) -> HttpResponse:
    """Move one report through triage, from the insights queue.

    A queue whose status cannot change is a list of things nobody has decided
    about, which is what the queue exists to stop.
    """
    status = request.POST.get("status") or ""
    if status not in ProvisionFeedback.Status.values:
        return HttpResponseBadRequest("Unknown status.")

    updated = ProvisionFeedback.objects.filter(pk=pk).update(status=status)
    if not updated:
        return HttpResponseBadRequest("No such report.")

    # Re-render the one row rather than the page: the queue is the only thing
    # that changed, and a full reload would lose the reader's scroll position
    # halfway down a long dashboard.
    return render(
        request,
        "partials/_feedback_row.html",
        {"row": feedback_row(pk), "statuses": ProvisionFeedback.Status.choices},
    )
