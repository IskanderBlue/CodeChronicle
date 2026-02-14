"""
Search history views.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.models import SearchHistory


@login_required
def history(request):
    """User search history page."""
    from django.db.models import Count, Max

    # 200 distinct queries is reasonable for client-side filtering (Alpine.js)
    history_limit = 200

    # Group by query: get the latest record ID and search count per unique query
    query_stats = list(
        SearchHistory.objects.filter(user=request.user)
        .values("query")
        .annotate(search_count=Count("id"), latest_id=Max("id"))
        .order_by("-latest_id")[:history_limit]
    )

    latest_ids = [s["latest_id"] for s in query_stats]
    count_map = {s["latest_id"]: s["search_count"] for s in query_stats}

    # Fetch full records for the latest occurrence of each query
    searches = list(SearchHistory.objects.filter(id__in=latest_ids).order_by("-timestamp"))
    for s in searches:
        s.search_count = count_map.get(s.id, 1)

    return render(request, "history.html", {"history": searches})
