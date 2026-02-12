"""
Views for core app (frontend pages).
"""

from allauth.account.forms import ChangePasswordForm
from coloured_logger import Logger
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from api.formatters import format_search_results
from api.llm_parser import parse_user_query
from api.search import execute_search
from config.code_metadata import get_pdf_expectations
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
                "Direct API access",
                "Full text extraction",
                # "Advanced PDF maps",
                # "Amendment alerts",
                # "Search history exports",
            ],
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

    price_id = settings.STRIPE_PRO_PRICE_ID
    if not price_id:
        return render(request, "pricing.html", {"error": "STRIPE_PRO_PRICE_ID not configured"})

    try:
        customer_id = request.user.stripe_customer_id
        if not customer_id:
            cust = stripe.Customer.create(
                email=request.user.email,
                metadata={"django_user_id": str(request.user.id)},
            )
            customer_id = cust["id"]
            request.user.stripe_customer_id = customer_id
            request.user.save(update_fields=["stripe_customer_id"])

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            client_reference_id=str(request.user.id),
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            allow_promotion_codes=True,
            success_url=request.build_absolute_uri(reverse("core:stripe_success"))
                + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.build_absolute_uri(reverse("core:stripe_cancel")),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        logger.error("Stripe checkout error: %s", e)
        from django.contrib import messages

        messages.error(request, f"Checkout failed: {e}")
        return redirect(reverse("core:pricing"))


@login_required
def stripe_success(request):
    """Post-checkout success page — sync dj-stripe data."""
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

    session_id = request.GET.get("session_id")
    verified = False
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            verified = (
                session.customer == request.user.stripe_customer_id
                or str(session.client_reference_id) == str(request.user.id)
            )
            if verified:
                _sync_customer_after_checkout(request.user, session.customer)
        except Exception as e:
            logger.warning("stripe_success sync error: %s", e)

    return render(request, "stripe_success.html", {"verified": verified})


def _sync_customer_after_checkout(user, stripe_customer_id: str):
    """Sync the dj-stripe Customer and its Subscriptions from Stripe."""
    from djstripe.models import Customer

    try:
        customer, _ = Customer.objects.get_or_create(
            id=stripe_customer_id,
            defaults={"livemode": not settings.DEBUG},
        )
        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        import stripe

        stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
        Customer.sync_from_stripe_data(stripe_customer)

        customer.refresh_from_db()
        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=stripe_customer_id, status="all", limit=10)
        from djstripe.models import Subscription

        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("_sync_customer_after_checkout error: %s", e)


def stripe_cancel(request):
    """Checkout cancelled — redirect to pricing with banner."""
    from django.contrib import messages

    messages.info(request, "Checkout cancelled. You can upgrade anytime.")
    return redirect(reverse("core:pricing"))


@login_required
@require_POST
def create_customer_portal_session(request):
    """Create a Stripe Customer Portal session."""
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

    customer_id = request.user.stripe_customer_id
    if not customer_id:
        return redirect(reverse("core:pricing"))

    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=request.build_absolute_uri(reverse("core:user_settings") + "#account"),
    )
    return redirect(portal_session.url, code=303)


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
        formatted = format_search_results(search_results_data["results"])
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
    """User settings page — syncs subscription status from Stripe."""
    if request.user.stripe_customer_id:
        _sync_subscription_status(request.user)

    password_form = ChangePasswordForm(user=request.user)
    return render(
        request,
        "settings.html",
        {
            "pdf_expectations": get_pdf_expectations(),
            "password_form": password_form,
        },
    )


def _sync_subscription_status(user):
    """Re-sync dj-stripe Subscription records from Stripe for this user."""
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

    try:
        from djstripe.models import Customer, Subscription

        stripe_customer = stripe.Customer.retrieve(user.stripe_customer_id)
        customer = Customer.sync_from_stripe_data(stripe_customer)

        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=user.stripe_customer_id, status="all", limit=10)
        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("_sync_subscription_status error: %s", e)

