"""
Regulation browsing views.
"""

from django.shortcuts import get_object_or_404, render

from core.models import CodeEdition, Regulation


def regulation_detail(request, pk: int):
    """Show a single regulation with all its clauses."""
    regulation = get_object_or_404(
        Regulation.objects.select_related("edition__code", "amends"),
        pk=pk,
    )
    clauses = regulation.clauses.order_by("clause_id")
    return render(request, "regulation/detail.html", {
        "regulation": regulation,
        "clauses": clauses,
    })


def edition_chain(request, pk: int):
    """Show the amendment chain timeline for a code edition."""
    edition = get_object_or_404(
        CodeEdition.objects.select_related("code"),
        pk=pk,
    )
    regulations = (
        edition.regulations
        .select_related("amends")
        .prefetch_related("clauses")
        .order_by("effective_date")
    )
    return render(request, "regulation/chain.html", {
        "edition": edition,
        "regulations": regulations,
    })
