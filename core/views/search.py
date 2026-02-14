"""
Search-related views.
"""

from coloured_logger import Logger
from django.shortcuts import render
from django.views.decorators.http import require_POST

logger = Logger(__name__)


def home(request):
    """Main search page."""
    initial_query = request.GET.get("q", "")
    return render(request, "search.html", {"initial_query": initial_query})


@require_POST
def search_results(request):
    """HTMX search results view."""
    query = request.POST.get("query", "")
    date_override = request.POST.get("date")
    province_override = request.POST.get("province")

    # Extract IP for anonymous tracking
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")

    from services.search_service import run_search

    result = run_search(
        query,
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        date_override=date_override or None,
        province_override=province_override or None,
    )

    if not result["success"]:
        return render(
            request,
            "partials/search_results_partial.html",
            {"success": False, "error": result["error"]},
        )

    return render(
        request,
        "partials/search_results_partial.html",
        {
            "success": True,
            "results": result["results"],
            "meta": {"applicable_codes": result["applicable_codes"]},
        },
    )
