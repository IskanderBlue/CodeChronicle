"""
Views for core app (frontend pages).
"""
from django.shortcuts import render
from django.views.decorators.http import require_POST
from api.llm_parser import parse_user_query
from api.search import execute_search
from api.formatters import format_search_results


def home(request):
    """Main search page."""
    return render(request, 'search.html')


def pricing(request):
    """Pricing and subscription tiers."""
    plans = [
        {
            "name": "Free",
            "price": "0",
            "features": [
                "1 Search per day (anonymous)",
                "3 Searches per day (logged in)",
                "Historical code search",
                "Coordinates & Page info",
            ]
        },
        {
            "name": "Pro",
            "price": "29",
            "features": [
                "Unlimited searches",
                "Full text extraction",
                "Advanced PDF maps",
                "Amendment alerts",
                "Search history exports",
            ]
        },
    ]
    return render(request, 'pricing.html', {"plans": plans})


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
        return render(request, 'partials/search_results_partial.html', {
            "success": False,
            "error": f"An unexpected error occurred: {str(e)}"
        })
