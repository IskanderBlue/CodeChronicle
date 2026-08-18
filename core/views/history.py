"""
Search history views.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import render

from core.models import SearchHistory, grouped_by_question


@login_required
def history(request):
    """User search history page.

    One card per *question*, showing the latest run of it.

    **A question is the query text and the date it ran at** — the same
    definition ``core.middleware`` uses for the anonymous allowance, and for
    the same reason: asking what the code said in 2005 and again in 2015 is
    most of what this product is for, so the two are not one entry.  Grouping
    on the words alone collapsed them into a single card that showed the later
    date and linked to it, which left the earlier search in the database,
    counted by the rate limiter, and unreachable by the reader.

    Taking the **latest** row of each question is also what lets a re-ranked
    search update the card the reader comes back to.  Nothing edits a stored
    row: ``services.search_service`` appends one per search that runs, and
    ``EngagementEvent.search`` points at those rows, so rewriting one would
    make clicks already recorded against it describe a search that did not
    run.
    """
    # 200 distinct questions is reasonable for client-side filtering (Alpine.js)
    history_limit = 200

    # The latest record ID and the run count for each question.  A row whose
    # parse read no date groups with the others that read none, which is right:
    # they are all "the same words at no stated date".
    query_stats = list(
        grouped_by_question(SearchHistory.objects.filter(user=request.user))
        .annotate(search_count=Count("id"), latest_id=Max("id"))
        # Also clears Meta.ordering, which would otherwise join the GROUP BY
        # and split every question into one card per timestamp.
        .order_by("-latest_id")[:history_limit]
    )

    latest_ids = [s["latest_id"] for s in query_stats]
    count_map = {s["latest_id"]: s["search_count"] for s in query_stats}

    # Fetch full records for the latest occurrence of each question
    searches = list(SearchHistory.objects.filter(id__in=latest_ids).order_by("-timestamp"))
    for s in searches:
        # Attach the per-question count as a dynamic display attribute (read by
        # history.html). Not a model field — setattr keeps that explicit.
        setattr(s, "search_count", count_map.get(s.id, 1))

    return render(request, "history.html", {"history": searches})
