# General comparison: any two versions, from any editions

**Prefix:** `a-` — high priority, actionable now. All the data this needs is
loaded. This is the feature that justifies the Pro price.

## Goal

Let a reader compare **any two provision versions**, including versions in
different editions, by two routes:

1. **By text.** Name the two versions in a form or a URL, and get the diff.
2. **By clicking.** From any version in a chain, click a second version to
   compare against — including a version in an earlier or later edition.

Today the comparison is narrower: `?compare=` pairs two versions of the *same*
provision inside *one* edition, and the transition pairing groups a
cross-edition pair only when the upstream data already marked it as a pair
(`pair_key` / `is_primary`; see the memory note `project_transition_pairing`).
A reader cannot ask for a comparison the data did not anticipate.

## Why this is the paid feature

"What did this provision say in 1997, and what does it say now?" is the
question the product exists to answer, and it is the one question a reader
cannot answer with two browser tabs — the two texts are long, the changes are
small, and the amending regulation is not visible in either. The diff is the
answer. It is also the thing no free source has.

## What already exists — reuse it

- `templates/provenance/_compare_diff.html` and `_compare_pane.html` render a
  redline with the `--strike` / `--insert` functional colour tokens.
- `_diff_html_content()` in `core/views/regulation.py` builds the two sides.
- `ProvisionMapping` links a provision in one edition to its counterpart in
  another. This is what makes cross-edition comparison possible at all.
- `core/permalinks.py` reverses a version URL, and handles the empty-division
  case that OBC 1997 needs.

Reuse each of these. Do not write a second differ. See the memory note
`feedback_reuse_dont_transcribe`.

## Design

### The URL is the feature

A comparison must be linkable, because the reason to make one is usually to
send it to somebody. Two version references in, one page out:

```
/compare/?a=OBC_1997/3.2.5.7./v3&b=OBC_2006/B/3.2.5.7./v0
```

Keep the reference form identical to the permalink path form, so a reader can
build one by copying two URLs. Do not invent internal ids for this: see the
memory note `feedback_no_internal_url_params`.

### The click route

On any version row in the amendment chain rail, add a **compare against this**
affordance. The first click arms the comparison and marks the row; the second
click on another row runs it. A visible "comparing X against …" state, and an
escape, are required — a mode a reader cannot leave is a trap.

Cross-edition rows appear in the same list, resolved through
`ProvisionMapping`. A mapped counterpart is offered; an unmapped one is not
offered at all, rather than offered and then failing.

### What the page must state

- Both in-force windows, in full.
- Both amending regulations, named.
- **That the two provisions are counterparts, and how we know.** A
  cross-edition diff compares two texts that the legislature never placed side
  by side. The page must say that the pairing comes from the mapping, not from
  the statute, or it asserts an equivalence nobody enacted.
- When the two texts are unrelated enough that a redline is noise, say so and
  show them side by side instead of a diff full of red.

### Gating

Same-edition comparison stays available in the free tier, since OBC 2006's
chain is already free. Cross-edition comparison is Pro, because it needs an
edition the free tier does not cover on at least one side. Route the check
through `core/access.py`; do not add a second definition of a tier.

## Risks

- **A diff of two long provisions is unreadable if everything changed.**
  Detect this and fall back to side-by-side.
- **Tables and images do not diff.** The image-first rule
  (`project_table_image_html_precedence`) means one side may be a page scan
  and the other extracted HTML. Show both as images when both have them, and
  state the limitation when they differ.
- **A missing mapping is normal**, not an error. Provisions are added and
  removed between editions. Say "no counterpart in OBC 2006" rather than
  showing an empty pane.

## Done when

- Any two versions can be compared by URL, in either direction, within and
  across editions.
- The chain rail offers a click route with a clear armed state and an escape.
- The pairing basis is stated on every cross-edition comparison.
- Tier gating goes through `core/access.py`, with tests.
- The unreadable-diff and missing-mapping cases each have a test.

## Related

- `tasks/b-provision-exports.md` — a comparison is the most useful thing to
  export.
- Memory: `project_transition_pairing`, `project_table_image_html_precedence`.
