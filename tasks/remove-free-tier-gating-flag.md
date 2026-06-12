# Remove the FREE_TIER_GATING_ENABLED flag (make gating unconditional)

**Status: BLOCKED on go-live soak — do not start until the flag has been ON
in prod for a few days of real traffic (anonymous, free-account, and Pro
journeys all exercised) with no rollback.**

## Why it exists / why it goes

The flag was the go-live switch and, during the riskiest window, the kill
switch: rollback from a gating surprise is a bundle edit + container
restart instead of revert → rebuild → redeploy. Once gating has soaked in
prod, the off-branch is dead code that doubles the test surface and makes
every gate read conditional. Existing accounts were grandfathered
(`pro_courtesy`) 2026-06-12, so nothing depends on ever flipping it off.

## Scope (pure deletion — the surviving branch is the proven one)

- `core/access.py` — drop the `FREE_TIER_GATING_ENABLED` early-outs in
  `user_is_unrestricted` / scope helpers; gating logic stays as-is.
- Pricing: `core/views/pages.py` `pricing()` loses the branch; delete
  `templates/pricing_early_access.html` (early-access placeholder only
  renders while the flag is off).
- Settings plumbing: the setting in `code_chronicle/settings/` and the
  env/bundle read; remove `FREE_TIER_GATING_ENABLED` from the
  `app_runtime_secrets` bundle afterwards (stale keys in the bundle read
  as still-load-bearing).
- Tests: delete flag-off branch tests; un-parametrise tests that ran both
  ways. `FREE_TIER_CODE_NAMES` stays — it's the scope definition, not the
  switch.
- Docs: update CLAUDE.md "Rate Limiting & Subscriptions" and
  `tasks/free-tier-obc2006-scope.md` (then move it to `tasks/complete/`).

## Acceptance

- No `FREE_TIER_GATING_ENABLED` references anywhere (code, settings,
  templates, tests, docs, bundle).
- Anonymous + non-Pro scoped to OBC 2006, Pro unrestricted — identical
  behaviour to flag-on before the deletion.
