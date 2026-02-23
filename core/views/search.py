"""
Search-related views.
"""

from coloured_logger import Logger
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.ip_utils import extract_client_ip

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
    ip = extract_client_ip(request.META)

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
