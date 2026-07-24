# Free tier scoped to OBC 2006; paid unrestricted

**Status: IMPLEMENTED 2026-06-10 behind `FREE_TIER_GATING_ENABLED` (default
off — no user-facing change until flipped). Go-live checklist below.**

## Goal

Replace the count-based tier split with a **content-scoped** one:

- **Free** (anonymous + signed-in non-Pro — same scope for both; signup
  only removes the anonymous daily cap): queries and browsing limited to
  **OBC 2006** — its provisions, its provision versions/amendment history,
  and the regulations that amend it. Nothing from other editions.
- **Paid** (Stripe sub or `pro_courtesy`): unrestricted — all loaded
  editions, all surfaces.

## Decisions (2026-06-10)

1. **Anonymous vs signed-in free**: same OBC 2006 scope for both; signup
   removes the anonymous per-IP daily cap only.
2. **Lock vs hide**: teaser/lock. Free users *see* that other editions
   exist (locked nav entries, "N results in OBC 2012" notice, 403 teaser
   pages) with an upgrade CTA — never a silent omission.
3. **Rollout**: built behind `FREE_TIER_GATING_ENABLED` (settings/env,
   default off). Flip when Pro is purchasable; nothing changes for users
   until then.
4. **Guides**: deferred — no guide edition is loaded yet. Membership is
   purely by `CodeEdition.code_name` in `FREE_TIER_CODE_NAMES`, so when a
   2006 guide loads, adding its code_name to the env var puts it in free
   scope without code changes.

## What was built

### Gate (single source of truth)

`core/access.py`:

- `user_is_unrestricted(user)` — True while gating is off, or for an
  authenticated user with `has_active_subscription` (`pro_courtesy` OR
  active dj-stripe sub).
- `edition_allowed(user, code_name)` — unrestricted OR code_name in
  `settings.FREE_TIER_CODE_NAMES`.
- `partition_results(user, results)` — splits search results into
  (allowed, {edition: dropped count}) for the teaser notice.

Settings (`code_chronicle/settings/base.py`): `FREE_TIER_GATING_ENABLED`
(env, default False), `FREE_TIER_CODE_NAMES` (env CSV, default `OBC_2006`).

### Gated surfaces

1. **Search execution** (`services/search_service.py:run_search`): results
   partitioned after `execute_search`, before formatting; locked counts
   returned as `locked_editions` and rendered as a teaser notice in
   `search_results_partial.html` (covers the all-locked case, e.g. a 2014
   as-of date resolving entirely to OBC 2012). `applicable_codes`,
   `top_results_metadata`, and SearchHistory `top_results` are filtered
   too. Cross-edition transition pairs degrade safely: the formatter
   already renders an unpaired member plainly (`api/formatters.py`
   "Unpaired" branch).
2. **Viewer section-content**: locked editions render an upsell teaser in
   the partial (no content, no engagement event).
3. **Viewer edition-nav**: adjacent locked editions stay *listed* but link
   to pricing instead of carrying the `data-edition-result` payload.
4. **Viewer edition-dates**: deliberately NOT gated — it exposes only
   in-force date ranges (no provision content) and powers the teaser.
5. **Provision permalink / regulation detail / edition chain**
   (`core/views/regulation.py`): 403 with a `locked_edition.html` teaser
   page naming the edition (gate runs after the lookup so the page can
   name it; garbage URLs still 404 first).
6. **API app**: nothing to gate — `/api/*` is already paid-only via
   `_require_paid_api_access`, and paid means unrestricted.

Tests: `core/tests/test_access.py` (helper units + all gated surfaces,
pro/free/anonymous, gating on/off).

### Lineage / cross-edition links (pending integration)

The provision-lineage UI (other branch work, `core/provision_lineage.py`)
must render cross-edition links through `core.access.edition_allowed` from
day one: a 2006→2012 lineage link for a free user renders as a locked
upsell link, not a 403 surprise after click-through. The 403 teaser is the
backstop if a link slips through ungated.

## Go-live checklist (flip `FREE_TIER_GATING_ENABLED=True`)

Blocked on Pro being purchasable (business bank account → route
`templates/pricing.html` live, `core/views/pages.py:22`). Then:

1. **Grandfather or notify existing accounts.** Flipping the flag drops
   every non-`pro_courtesy` account to OBC 2006. Decide per-account
   `pro_courtesy` grandfathering for early-access signups, or email them
   before the flip.
2. ~~Restore the Stripe pricing page~~ **DONE 2026-06-10**: the `pricing`
   view (`core/views/pages.py`) now branches on the flag — off serves the
   early-access placeholder, on serves `pricing.html` with the
   content-scoped Free ($0, OBC 2006) / Pro ($29, every edition) cards
   (`_pricing_plans`). Page and gate flip together; no skew possible.
   Verify the $29 price and feature copy are still right before go-live.
3. **Stripe must actually work** when the flag flips: the Pro card's
   "Upgrade to Pro" posts to `create_checkout_session`, which needs live
   keys + `STRIPE_PRO_PRICE_ID` (a `price_...` ID, NOT the `prod_...`
   product ID). **Config channel (2026-06-11)**: GCP production does NOT
   use `.env.prod`/`docker-compose.prod.yml` (legacy path — its local copy
   has placeholder ALLOWED_HOSTS). The web container env carries only
   GCP_PROJECT_ID / DJANGO_SETTINGS_MODULE / ALLOWED_HOSTS; Stripe + the
   gate flag resolve in `settings/production.py` via the
   `app_runtime_secrets` JSON bundle in GCP Secret Manager (same as
   email). Add `STRIPE_LIVE_SECRET_KEY` and `STRIPE_PRO_PRICE_ID` to the
   bundle (`gcloud secrets versions add app_runtime_secrets ...`), then
   `docker restart codechroniclenet-web` — the bundle is read once per
   process. `STRIPE_LIVE_MODE` defaults true in production.
4. ~~Sweep remaining copy~~ **DONE 2026-06-11**: `stripe_success.html`
   now says "Pro access" (not "unlimited searches" — that's the free-
   account perk post-flip); the unreachable "Upgrade to Pro for unlimited
   searches" rate-limit branch was deleted (template + middleware context
   key). `base.html`/`settings.html` were clean.
   `pricing_early_access.html` needs no retirement — it simply stops
   being served.
5. Flip the flag: add `FREE_TIER_GATING_ENABLED=true` to the
   `app_runtime_secrets` bundle and restart the web container (see item 3
   for the channel; rollback = remove the key + restart). Confirm
   `FREE_TIER_CODE_NAMES` (add the 2006 guide's code_name if loaded and
   it should be free).
6. Smoke-test the teaser surfaces as an anonymous user: search with a
   2014 as-of date (notice + zero results), a 2012 permalink (403 teaser),
   viewer next-edition (locked link), `/pricing/` (plan cards).
7. **Revisit the example-query chips** (`EXAMPLE_QUERIES`,
   `core/views/search.py`): the transition-demo chip ("when must a
   maintenance inspection be conducted, Ontario, 2014") resolves to the
   OBC 2006 C ↔ 2012 C 1.10.2.4. cross-edition pair — post-flip, a free
   user gets the 2006 side plus the locked-results teaser instead of the
   full compare card. The corpus has only 8 overlapping mapping pairs
   total (2026-06-11 scan), none entirely inside OBC 2006, so a
   free-tier-safe transition demo doesn't exist yet; accept the teaser or
   revisit once more transitions load.
