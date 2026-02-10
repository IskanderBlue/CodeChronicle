"""
Views for core app (frontend pages).
"""

import os
import re

from allauth.account.forms import ChangePasswordForm
from coloured_logger import Logger
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from api.formatters import format_search_results
from api.llm_parser import parse_user_query
from api.search import execute_search
from config.code_metadata import get_pdf_expectations, get_pdf_filename
from core.models import SearchHistory

logger = Logger(__name__)


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


def home(request):
    """Main search page."""
    initial_query = request.GET.get("q", "")
    return render(request, "search.html", {"initial_query": initial_query})


def pricing(request):
    """Pricing and subscription tiers."""
    is_authenticated = request.user.is_authenticated
    has_active_sub = is_authenticated and getattr(request.user, "has_active_subscription", False)

    plans = [
        {
            "id": "free",
            "name": "Free",
            "price": "0",
            "features": [
                "1 Search per day (anonymous)",
                "3 Searches per day (logged in)",
                "Historical code search",
                "Coordinates & Page info",
            ],
            "is_current": not is_authenticated or not has_active_sub,
        },
        {
            "id": "pro",
            "name": "Pro",
            "price": "29",
            "features": [
                "Free features",
                "Unlimited searches",
                "Full text extraction",
                # "Advanced PDF maps",
                # "Amendment alerts",
                # "Search history exports",
            ],
            "price_id": os.environ.get("STRIPE_PRO_PRICE_ID", "price_placeholder"),
            "is_current": is_authenticated and has_active_sub,
        },
    ]
    return render(request, "pricing.html", {"plans": plans})


@login_required
@require_POST
def create_checkout_session(request):
    """Create a Stripe Checkout session for the Pro plan."""
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

    price_id = os.environ.get("STRIPE_PRO_PRICE_ID")
    if not price_id:
        # Fallback for dev if not set
        price_id = "price_H5ggYrnNc779vg"  # Just an example

    try:
        checkout_session = stripe.checkout.Session.create(
            customer_email=request.user.email,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                },
            ],
            mode="subscription",
            success_url=request.build_absolute_uri(reverse("core:home"))
            + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.build_absolute_uri(reverse("core:pricing")),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return render(request, "pricing.html", {"error": str(e)})


@require_POST
def search_results(request):
    """HTMX search results view."""
    query = request.POST.get("query", "")
    date_override = request.POST.get("date")
    province_override = request.POST.get("province")

    try:
        # Step 1: Parse query
        params = parse_user_query(query)

        # Override if manually specified
        if date_override:
            params["date"] = date_override
        if province_override:
            params["province"] = province_override

        # Step 2: Search
        search_results_data = execute_search(params)

        if "error" in search_results_data:
            return render(
                request,
                "partials/search_results_partial.html",
                {"success": False, "error": search_results_data["error"]},
            )

        # Step 3: Format
        pdf_dir = ""
        if request.user.is_authenticated:
            pdf_dir = request.user.pdf_directory
        formatted = format_search_results(search_results_data["results"], pdf_dir=pdf_dir or None)
        logger.info("search frontend payload: %s", formatted)
        # Record search history
        try:
            # Extract IP for anonymous rate limiting/tracking
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                ip = x_forwarded_for.split(",")[0].strip()
            else:
                ip = request.META.get("REMOTE_ADDR")

            SearchHistory.objects.create(
                user=request.user if request.user.is_authenticated else None,
                ip_address=ip if not request.user.is_authenticated else None,
                query=query,
                parsed_params=params,
                result_count=len(formatted),
                top_results=search_results_data.get("top_results_metadata", []),
            )
        except Exception as e:
            # Don't fail the search if history tracking fails
            logger.error("Error recording search history: %s", e)

        return render(
            request,
            "partials/search_results_partial.html",
            {
                "success": True,
                "results": formatted,
                "meta": {"applicable_codes": search_results_data["applicable_codes"]},
            },
        )

    except Exception as e:
        error_msg = str(e)
        # Handle Anthropic auth error specifically for better UX
        if "401" in error_msg and "invalid x-api-key" in error_msg.lower():
            error_msg = "Search engine authentication failure. Please check the ANTHROPIC_API_KEY in .env settings."

        return render(
            request,
            "partials/search_results_partial.html",
            {"success": False, "error": f"An unexpected error occurred: {error_msg}"},
        )


@login_required
def user_settings(request):
    """User settings page (PDF directory configuration)."""
    if request.method == "POST":
        pdf_directory = request.POST.get("pdf_directory", "").strip()

        request.user.pdf_directory = pdf_directory
        request.user.save(update_fields=["pdf_directory"])
        messages.success(request, "Settings saved.")
        return redirect("core:user_settings")

    password_form = ChangePasswordForm(user=request.user)
    return render(
        request,
        "settings.html",
        {
            "pdf_directory": request.user.pdf_directory,
            "pdf_expectations": get_pdf_expectations(),
            "password_form": password_form,
        },
    )


@login_required
def serve_pdf(request, code_edition: str, map_code: str):
    """Serve a PDF from the authenticated user's configured directory."""
    # Validate formats to prevent path traversal
    if not re.match(r"^[A-Z]{2,5}_\d{4}$", code_edition):
        raise Http404
    if not re.match(r"^[A-Z]{2,5}[A-Za-z0-9]*(_[A-Za-z0-9]+)?$", map_code):
        raise Http404

    pdf_dir = request.user.pdf_directory
    if not pdf_dir:
        raise Http404

    filename = get_pdf_filename(code_edition, map_code)
    if not filename:
        raise Http404

    pdf_path = os.path.join(pdf_dir, filename)
    if not os.path.isfile(pdf_path):
        raise Http404

    return FileResponse(
        open(pdf_path, "rb"),
        content_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
