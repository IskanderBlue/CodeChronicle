"""
Views for core app (frontend pages).
"""
from django.shortcuts import render


def home(request):
    """Main search page."""
    return render(request, 'search.html')


def pricing(request):
    """Pricing page showing subscription tiers."""
    plans = [
        {
            'name': 'Free',
            'price': 0,
            'features': [
                '1 search per day (anonymous)',
                '3 searches per day (logged in)',
                'Section metadata only',
            ]
        },
        {
            'name': 'Pro',
            'price': 30,
            'features': [
                'Unlimited searches',
                'Full historical access',
                'Export results',
                'Priority support',
            ]
        },
    ]
    return render(request, 'pricing.html', {'plans': plans})
