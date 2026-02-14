"""
Static and settings page views.
"""

from allauth.account.forms import ChangePasswordForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from config.code_metadata import get_pdf_expectations

from .billing import _sync_subscription_status


def terms_of_service(request):
    """Terms of Service page."""
    return render(request, "terms_of_service.html")


def privacy_policy(request):
    """Privacy Policy page."""
    return render(request, "privacy_policy.html")


def pricing(request):
    """Pricing and subscription tiers (early-access placeholder).

    TODO: restore full Stripe pricing once business bank account is set up.
    Original template is preserved at templates/pricing.html.
    """
    return render(request, "pricing_early_access.html")


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
