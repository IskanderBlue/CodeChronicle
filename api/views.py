"""
Django Ninja API endpoints for CodeChronicle.
"""
from ninja import NinjaAPI
from ninja.security import django_auth

api = NinjaAPI(
    title="CodeChronicle API",
    version="0.1.0",
    description="Historical Canadian Building Code Search API",
)


@api.get("/health")
def health_check(request):
    """Health check endpoint."""
    return {"status": "ok"}


@api.post("/search")
def search(request, query: str):
    """
    Search building codes with natural language query.
    
    Rate limited:
    - Anonymous: 1/day
    - Logged in: 3/day
    - Pro: Unlimited
    """
    # TODO: Implement LLM parsing and search
    # This is a stub for initial setup
    
    from core.models import SearchHistory
    
    # Record the search
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    
    search_record = SearchHistory.objects.create(
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        query=query,
        parsed_params={},
        result_count=0,
    )
    
    return {
        "query": query,
        "parsed_params": {},
        "results": [],
        "result_count": 0,
        "message": "Search not yet implemented - skeleton only",
    }


@api.get("/history", auth=django_auth)
def get_search_history(request):
    """Return user's recent searches."""
    from core.models import SearchHistory
    
    history = SearchHistory.objects.filter(
        user=request.user
    ).order_by('-timestamp')[:20]
    
    return {
        "history": [
            {
                "query": h.query,
                "timestamp": h.timestamp.isoformat(),
                "result_count": h.result_count,
            }
            for h in history
        ]
    }


@api.get("/codes")
def list_available_codes(request):
    """List all code editions in the system."""
    # Will be populated from config/code_metadata.py
    return {
        "codes": [
            {"name": "OBC 2024", "province": "ON", "status": "Current"},
            {"name": "NBC 2025", "province": "Federal", "status": "Current"},
            # More will be loaded from CODE_EDITIONS
        ],
        "message": "Stub data - will load from CODE_EDITIONS"
    }
