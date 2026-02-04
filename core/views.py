"""
Views for core app (frontend pages).
"""
import os
from django.shortcuts import render, redirect
from django.conf import settings
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from api.llm_parser import parse_user_query
from api.search import execute_search
from api.formatters import format_search_results


def home(request):
    """Main search page."""
    return render(request, 'search.html')


def pricing(request):
    """Pricing and subscription tiers."""
    is_authenticated = request.user.is_authenticated
    has_active_sub = is_authenticated and getattr(request.user, 'has_active_subscription', False)
    
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
            "is_current": not is_authenticated or not has_active_sub
        },
        {
            "id": "pro",
            "name": "Pro",
            "price": "29",
            "features": [
                "Unlimited searches",
                "Full text extraction",
                "Advanced PDF maps",
                "Amendment alerts",
                "Search history exports",
            ],
            "price_id": os.environ.get('STRIPE_PRO_PRICE_ID', 'price_placeholder'),
            "is_current": is_authenticated and has_active_sub
        },
    ]
    return render(request, 'pricing.html', {"plans": plans})


@login_required
@require_POST
def create_checkout_session(request):
    """Create a Stripe Checkout session for the Pro plan."""
    import stripe
    stripe.api_key = settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    
    price_id = os.environ.get('STRIPE_PRO_PRICE_ID')
    if not price_id:
        # Fallback for dev if not set
        price_id = "price_H5ggYrnNc779vg" # Just an example
        
    try:
        checkout_session = stripe.checkout.Session.create(
            customer_email=request.user.email,
            payment_method_types=['card'],
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode='subscription',
            success_url=request.build_absolute_uri(reverse('core:home')) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(reverse('core:pricing')),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return render(request, 'pricing.html', {"error": str(e)})


@require_POST
def search_results(request):
    """HTMX search results view."""
    query = request.POST.get('query', '')
    date_override = request.POST.get('date')
    province_override = request.POST.get('province')
    
    try:
        # Step 1: Parse query
        params = parse_user_query(query)
        
        # Override if manually specified
        if date_override:
            params['date'] = date_override
        if province_override:
            params['province'] = province_override
            
        # Step 2: Search
        search_results_data = execute_search(params)
        
        if 'error' in search_results_data:
            return render(request, 'partials/search_results_partial.html', {
                "success": False,
                "error": search_results_data['error']
            })
            
        # Step 3: Format
        formatted = format_search_results(search_results_data['results'])
        
        return render(request, 'partials/search_results_partial.html', {
            "success": True,
            "results": formatted,
            "meta": {
                "applicable_codes": search_results_data['applicable_codes']
            }
        })
        
    except Exception as e:
        error_msg = str(e)
        # Handle Anthropic auth error specifically for better UX
        if "401" in error_msg and "invalid x-api-key" in error_msg.lower():
            error_msg = "Search engine authentication failure. Please check the ANTHROPIC_API_KEY in .env settings."
            
        return render(request, 'partials/search_results_partial.html', {
            "success": False,
            "error": f"An unexpected error occurred: {error_msg}"
        })
