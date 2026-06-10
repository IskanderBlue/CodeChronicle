# Free tier scoped to OBC 2006; paid unrestricted

**Status: DRAFT 2026-06-10 — direction set, open questions below need
answers before implementation.**

## Goal

Replace the current count-based tier split with a **content-scoped** one:

- **Free** (anonymous + signed-in non-Pro): queries and browsing limited to
  **OBC 2006** — its provisions, its provision versions/amendment history,
  and the regulations that amend it. Nothing from other editions.
- **Paid** (Stripe sub or `pro_courtesy`): unrestricted — all loaded
  editions, all surfaces.

The pricing page must be updated to describe the new split.

## Where the code is today (verified 2026-06-10)

- `core/middleware.py` `RateLimitMiddleware`: anonymous users get
  `RATE_LIMIT_ANONYMOUS`/day per IP on `POST /search-results/`;
  **authenticated users are currently unlimited** (the free-3/day in
  CLAUDE.md §Rate Limiting is stale). There is no content gating anywhere.
- Pro check: `User.has_active_subscription` (`core/models.py:76`) —
  `pro_courtesy` OR active dj-stripe subscription. Also referenced at
  `api/views.py:82`.
- The **live** pricing page is `templates/pricing_early_access.html`
  (placeholder; "Early Access — free for now, unlimited"). The full Stripe
  plan-cards template `templates/pricing.html` is preserved but unrouted
  (`core/views/pages.py:22` renders the early-access one; TODO says restore
  once the business bank account exists).
- Editions are `CodeEdition` rows keyed `(code, edition_id)`; canonical name
  is `code_name` = `f"{code.code}_{edition_id}"` (e.g. `OBC_2006`).
  `config/code_metadata.py:get_applicable_codes(province, date)` picks
  in-force editions for a search date.

## Design

### Single source of truth for the gate

One helper, e.g. `core/access.py`:

```python
FREE_TIER_CODE_NAMES = {"OBC_2006"}  # settings-backed, not hardcoded

def edition_allowed(user, code_edition: CodeEdition) -> bool: ...
def user_is_unrestricted(user) -> bool:  # has_active_subscription
```

Every surface below calls this — no surface re-derives tier logic.
`FREE_TIER_CODE_NAMES` should live in settings so the free window can widen
without a deploy-time code change.

### Surfaces to gate (choke points)

1. **Search execution** (`core/views/search.py:search_results` →
   `api/search.execute_search` → `get_applicable_codes`). For free users,
   intersect the applicable-editions list with the free set *after* the
   normal date-based resolution. When editions were dropped, say so in the
   results header ("N results in OBC 2012 hidden — upgrade to see them" or
   at minimum "results limited to OBC 2006 on the free plan") rather than
   silently returning less. The AS-OF picker stays usable — a 2014 as-of
   date for a free user resolves to OBC 2012, which then filters to
   nothing; that case needs an explicit notice, not an empty result.
2. **Viewer endpoints** (`/viewer/edition-nav/`, `/viewer/edition-dates/`,
   `/viewer/section-content/` — `core/urls.py:19-21`): reject or lock
   requests for non-free editions; edition-nav should still *list* other
   editions but render them as locked/upsell entries (see teaser question
   below).
3. **Provision permalink** (`/provision/<code_edition>/…` —
   `core/urls.py:27-40`): `code_edition` is in the URL; gate on it. Free
   users keep full version-history access *within* OBC 2006 (that history
   — amendments — is explicitly part of the free offer).
4. **Regulation detail** (`/regulation/<pk>/`): allowed for free iff the
   regulation belongs to / amends OBC 2006 (`Regulation.code_edition` FK).
5. **Edition chain** (`/edition/<pk>/chain/`): gate on the edition.
6. **Cross-edition links** the UI emits: transition-compare pairs and the
   incoming provision-lineage rows (`tasks/provision-lineage.md`) will link
   2006 → 2012. For free users these must render as locked upsell links,
   not 403 surprises after click-through. Lineage implementation should
   take the gate helper as a rendering input from day one.
7. **API app** (`/api/search`, `/api/codes`, `/api/history`): mirror the
   same filtering; `/api/codes` should mark non-free editions as
   `locked: true` rather than omitting them.

### What does NOT change

- LLM parsing, QueryCache (caches the *parse*, which is tier-independent).
- SearchHistory recording.
- Loading/admin paths.

### Pricing page

- Update **`pricing_early_access.html`** (the live page) — its "Early
  Access = unlimited everything" card is what this change invalidates.
- Update **`pricing.html`** (the dormant Stripe page) in the same pass so
  the two don't skew: Free card lists "OBC 2006 — all provisions, full
  amendment history"; Pro card lists "every loaded edition (2006, 2012, …),
  cross-edition history & compare".
- Decide whether this change is the trigger to route `pricing.html` live
  (it only makes sense to gate content once there's a purchasable Pro —
  see open questions).
- Also sweep other copy stating the old limits: `templates/base.html`,
  `templates/settings.html`, rate-limit upsell partial
  (`templates/partials/search_results_partial.html`), CLAUDE.md §Rate
  Limiting (already stale), AGENTS.md:33.

### Rate limits

Content scoping replaces the *content* dimension only. Decide whether the
anonymous per-IP daily cap stays as an abuse guard (recommended: yes, keep
it, it's orthogonal). The middleware grows the edition gate or a new
`core/access.py` is consulted from the views — prefer the views/service
layer over the middleware, since the gate needs route params (edition ids)
that the middleware would have to re-parse.

## Open questions (blocking)

1. **Anonymous vs signed-in free** — same OBC 2006 scope for both, with
   signup only removing the daily cap? Or is sign-in required for any
   browsing beyond search results?
2. **Lock vs hide** — do free users *see* that 2012 results/links exist
   (teaser + upgrade CTA — better conversion, more UI work) or are other
   editions invisible? Recommendation: teaser, since lineage/compare
   already surface the cross-edition structure.
3. **Stripe go-live coupling** — gating content while `pricing` still
   renders the early-access placeholder means free users lose access with
   nothing to buy. Does this task wait on the bank account / live
   `pricing.html`, or do early-access signups get `pro_courtesy`
   grandfathered?
4. **Guides** (`CodeEdition.is_guide`) — does the 2006 *guide* edition (if
   loaded) count as part of the free scope?

## Test plan

- Free user: search with 2014 as-of date → OBC 2012 filtered, notice shown.
- Free user: direct URL to a 2012 provision permalink / regulation /
  viewer section-content → locked response (and HTMX partial, not JSON,
  for HTMX requests — same split as `RateLimitMiddleware`).
- Pro user (`pro_courtesy=True` fixture, as in `api/tests/test_api.py:21`):
  all of the above unrestricted.
- Pricing page renders new copy in both templates.
