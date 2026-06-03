# Viewer edition-nav: resolve cross-edition identity via ProvisionMapping

**Status: OPEN — scoped feature, not a cleanup.**
Raised 2026-06-03 during the `cepv` code review of the viewer edition-navigation
path.

## The problem

The viewer's previous/next-**edition** links resolve "the same provision in
another edition" with a heuristic in `core/views/search.py`:

- `_build_viewer_url_params` looks up `CodeEditionProvision` by
  `(edition, provision_id)` **only** (division omitted), then picks among the
  matches by a fixed division preference
  `[preferred_division, "B", "C", "D", "A", ""]`, falling back to
  `candidates[0]`.
- `_build_viewer_navigation` passes the **source** edition's division as
  `preferred_division`.

This treats raw `provision_id` as a stable cross-edition key and the source
division as a tiebreak. It works for OBC today only because modern OBC keeps
division numbering stable across editions and division-less editions (1997)
resolve through the trailing `""`. It will silently pick the **wrong** provision
the day an edition renumbers a provision across divisions, splits one into
several, or merges several into one — because the heuristic has no concept of
those.

Note: this is *not* a determinism bug. The unique constraint
`(edition, provision_id, division)` means each division has at most one match,
so `_pick` is deterministic and the order-dependent `candidates[0]` fallback is
unreachable for valid A/B/C/D/`""` data. The issue is **identity fidelity**, not
ordering.

## We already have the right object

`core.models.ProvisionMapping` is the explicit old↔new provision identity map,
produced by CCM's edition matcher:

- `old_provision` / `new_provision` — FKs to `CodeEditionProvision`, so each
  endpoint already carries the correct **edition and division**.
- `mapping_type` — `renumbered | split | merged | replaced`.
- `introduced_by_version` — set for intra-edition renumbers.

The **search-results** transition compare already uses it
(`api/search/orchestration._merge_provision_mapping_transitions`, per the
`project_transition_pairing` decision). The viewer edition-nav path is the
holdout still guessing.

## Why it's a feature, not a one-line swap

`ProvisionMapping` is **partial and many-valued by design**, whereas the
heuristic is total and single-valued:

1. **Sparse coverage.** Mappings are emitted only where identity *changed*
   (renumber/split/merge/replace). A provision that keeps its id across editions
   has no row, so same-id lookup must remain the **fallback** when no mapping
   exists. The plan is mapping-first, same-id-fallback — not a replacement.
2. **Cardinality.** `split` (1→N) and `merged` (N→1) aren't 1:1, but prev/next
   nav is a single link. Needs a policy: pick a primary endpoint, or surface
   "this became N provisions / came from N provisions."
3. **Adjacency / chaining.** Nav targets the *immediately* prev/next edition by
   date. A mapping endpoint may point at a non-adjacent edition, and mappings
   can chain (X→Y→Z), so resolution must walk to the edition actually being
   navigated to rather than trusting a single hop.

## Plan

1. In `_build_viewer_navigation`, for the target (prev/next) edition, first try
   to resolve the provision via `ProvisionMapping` from the **current**
   provision (`mapped_forward` toward newer, `mapped_back` toward older),
   walking the chain to the target edition.
2. Fall back to the existing `(edition, provision_id)` + division-preference
   lookup when no mapping reaches the target edition (the unchanged-id common
   case).
3. Decide and implement the split/merge policy (primary endpoint vs. multi-link
   UI). Smallest first cut: pick the primary and note the fan-out.
4. Keep the same-id heuristic as the documented fallback; add a comment at its
   site pointing here.

## Definition of done

Viewer prev/next-edition links land on the provision CCM actually mapped to
(correct edition **and** division) for renumbered/split/merged/replaced
provisions, with the same-id heuristic retained only as the no-mapping
fallback — verified by a test using a `ProvisionMapping` whose endpoints differ
in division across editions.

## Do NOT

- Do not delete the `(edition, provision_id)` + division-preference path — it
  remains the correct fallback for unmapped (unchanged-id) provisions.
- Do not assume 1:1 — handle `split`/`merged` explicitly before shipping.
