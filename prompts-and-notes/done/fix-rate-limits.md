# Fix rate limiting bypass for HTMX endpoint (S, <1h)

Current middleware only applies to /api/search, but the real usage path is POST /search-results/.

## 1 Update RateLimitMiddleware path matching

File: core/middleware.py

Change:

    if request.path.startswith('/api/search'):

To something like:

    if request.path.startswith("/api/search") or request.path.startswith("/search-results/"):

Also consider restricting to POST only:

    if request.method == "POST" and ( ...paths... ):

## 2 Return HTML-friendly errors for HTMX (optional)

Right now middleware returns JsonResponse for rate limit errors. HTMX will render that JSON as text unless you handle it.

Simplest improvement:

- If request is HTMX (HX-Request header), return an HTML partial with the error message (or a 429 with HX-Redirect: /pricing/ for authenticated free users).
- Otherwise keep JSON for API.
