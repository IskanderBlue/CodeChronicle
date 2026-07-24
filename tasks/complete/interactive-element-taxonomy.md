# Interactive-element taxonomy

**Done 2026-06-12.** The app had no shared representation for clickables —
every button/link was a hand-copied Tailwind utility string, and the weakest
pattern (a bare mono-uppercase `text-secondary` label) was visually identical
to a *static* accent label, so toggles read as headings. That's why the
transition-compare banner's "compare" toggle was invisible.

## What was added

Four affordance roles + one shared `:focus-visible` ring, defined in
`templates/base.html`'s inline always-present `<style>` block (not Tailwind
utilities — those get purged; same rationale as `.font-legal`). All colours are
role tokens, so light + dark resolve automatically.

| Class | Role | Treatment |
|---|---|---|
| `.ui-link` | inline prose link | solid underline, accent, hover deepens |
| `.ui-cite` | quiet metadata-citation link | faint 35% underline at rest, strengthens on hover |
| `.ui-action` | interactive mono/uppercase label | dotted underline + `.ui-caret` (rotates on `[aria-expanded="true"]`) + optional `.ui-hint` |
| `.ui-btn` | primary filled action | accent bg, Inter Tight 600 |
| `.ui-btn-ghost` | bordered/chip action | frame + hover only; **type-agnostic** (inherits font/case) |

The app previously had **no** focus-visible styling anywhere; all four roles
now share one ring.

## Migrated

- `.ui-action` → the transition-compare banner (`_result_citation_header.html`,
  `compare_toggle=True`). Replaces the foot-of-card button.
- `.ui-btn` → search submit; nav "Sign up"; all account/* submit buttons
  (~13 files, identical pattern); pricing / pricing_early_access / stripe_success
  CTAs; settings action buttons.
- `.ui-btn-ghost` → example-query chips, "Got it"/"Close", viewer edition-nav
  rows (predecessor + successor, locked + unlocked).
- `.ui-link` → in-content notices (search results partial), legal pages
  (data_sources / terms / privacy), locked-edition + viewer-section Pro notices,
  account prose links.
- `.ui-cite` → provenance rail reg/version links, lineage rows, result-body
  amending-reg link, result-document-block source link, commencement gazette
  link, permalink nav items, provision-permalink prev/next, reg-detail
  contributor links.

## The governing rule (after critique)

A follow-up question — "won't *not* forcing every clickable into the taxonomy
confuse users?" — surfaced the real principle: **no interactive text may rely on
colour alone at rest.** Variety of weight is fine (hierarchy); ambiguity (hidden
/ false affordance) is the enemy. That closed one loophole: the dense citation
links used accent-colour-at-rest + hover-only underline — the same too-weak
signal the compare toggle had. They now use `.ui-cite` (faint persistent
underline). The footer got a persistent faint underline too (kept muted).

## Deliberately NOT migrated (own valid idioms)

- **Footer chrome** — kept muted (`text-ink-3`, no accent) but given a persistent
  faint underline so it also has an at-rest signal without shouting.
- **Muted helper toggles** — the search "How it works" `?`/`–` toggle is
  `text-ink-3` + a glyph (a non-colour signal), so it passes the rule as-is.
- **Structural full-card / row clickables** — history card (`p-6 no-underline`),
  the result accordion row toggle, the mobile "previous version" disclosure.
  These are layout components with their own borders, not text/button roles.
- **BYOD PDF toolbar** — a self-consistent outline-accent button cluster behind
  the open-fate BYOD feature (`tasks/byod-pdf-viewer-fate.md`). Low traffic;
  left to avoid changing its character.

## Possible follow-ups

- If the BYOD viewer ships, fold its toolbar into `.ui-btn-ghost` + an
  outline-accent variant.
- Consider a `.ui-link-quiet` only if the metadata-citation pattern needs to be
  named rather than left inline.
