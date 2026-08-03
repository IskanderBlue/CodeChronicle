# General comparison: any two versions, from any editions

**Complete, 2026-08-03.** The URL route, the entry controls and the version
timeline all shipped, and the old `?compare=` view is retired.

## Goal

Let a reader compare **any two provision versions**, including versions in
different editions, by two routes:

1. **By text.** Name the two versions in a form or a URL, and get the diff.
2. **By clicking.** From any version in a chain, click a second version to
   compare against — including a version in an earlier or later edition.

Before this card, the comparison was narrower: the permalink's `?compare=`
parameter paired two versions of the *same* provision inside *one* edition, and
the transition pairing groups a cross-edition pair only when the upstream data
already marked it as a pair (`pair_key` / `is_primary`; see the memory note
`project_transition_pairing`). A reader could not ask for a comparison the data
did not anticipate.

## Why this is the paid feature

"What did this provision say in 1997, and what does it say now?" is the
question the product exists to answer, and it is the one question a reader
cannot answer with two browser tabs — the two texts are long, the changes are
small, and the amending regulation is not visible in either. The diff is the
answer. It is also the thing no free source has.

## What already exists — reuse it

- `templates/provenance/_compare_pane.html` renders one side of a redline with
  the `--strike` / `--insert` functional colour tokens. (`_compare_diff.html`
  was the `?compare=` wrapper around two panes. It is deleted; see "`?compare=`
  is retired".)
- `_diff_html_content()` in `api/formatters.py` builds the two sides.
- `ProvisionMapping` links a provision in one edition to its counterpart in
  another. This is what makes cross-edition comparison possible at all.
- `core/permalinks.py` reverses a version URL, and handles the empty-division
  case that OBC 1997 needs.

Reuse each of these. Do not write a second differ. See the memory note
`feedback_reuse_dont_transcribe`.

## What shipped

- `core/compare.py` — the reference form, the prepared pair, and the pairing
  basis. `/compare/?a=OBC_1997/3.2.5.7./v3&b=OBC_2006/B/3.2.5.7./v0` parses and
  builds through one pair of functions, so the two directions cannot drift.
  Slashes stay unencoded: the point of reusing the permalink form is that a
  reader can read the URL.
- `core/views/compare.py` and `templates/compare.html` — the page. It drops the
  provenance rail that every other provision surface carries, because the rail
  states the provenance of *one* version and here there are two. The twin
  header is the rail's content, re-cut for two.
- `templates/partials/_compare_button.html` — "Compare versions", on the search
  result rail and the permalink rail, opt-in per surface (`allow_compare`) like
  `allow_report`.
- `diff_similarity()` in `api/formatters.py`, over the same tokens
  `_diff_html_content` diffs, so the redline floor measures what the redline
  would draw.
- `EngagementEvent.EventType.VERSION_COMPARISON` (migration
  `0050_alter_engagementevent_event_type`), recorded **after** the gate, so a
  refusal counts as a `LOCKED_CONTENT_VIEW` and never also as value delivered —
  the two are the numerator and the denominator of one question.
  `context.cross_edition` carries the split that matters. `/insights/` shows
  both totals.
- `templates/partials/_compare_link.html` — the per-row `compare` link. Every
  row that names another version carries it: each amendment-chain row, the
  next-version row, and each cross-edition lineage row
  (`_lineage_link_row.html`). A locked counterpart gets no link, because the
  page would refuse it.
- `diff_is_empty()` in `api/formatters.py`, and the "the text is unchanged"
  line it drives on **both** comparison surfaces: `/compare/` and the
  transition-compare card in the search results. A redline marks what changed,
  so it cannot show that it marked nothing — an unchanged pair and an
  unfinished read look alike until the reader has been down both columns. It
  compares the words the redline compares, so re-wrapped markup is not a change.
- Citations inside the comparison panes are links. `/compare/` runs
  `annotate_versions` once per side, because a link is scoped to one edition
  and a cross-edition pair has two.
- `templates/partials/_transition_compare_link.html` — the transition card's
  own link to `/compare/`, built from the card's two versions and never through
  the ladder (the ladder's first rung is the local comparison, which is not
  what the card is about). Beside it, the inline toggle now reads **inline
  compare** / **hide**: two comparisons on one card must each say which one
  they are.
- Both breakpoint trees carry the control. Below `lg` the rail arrives through
  `_provenance_banner.html`, so `allow_compare` is set at the banner's two call
  sites — `_result_body.html` and `provision_permalink.html`. Not inside the
  banner: the banner is a stacker, and the surface owns the decision, which is
  what lets the landing page's specimen rail show no compare control.
- 56 tests in `core/tests/test_compare.py`, plus six in
  `api/tests/test_formatters.py` and four in `core/tests/test_templates.py`.

### `?compare=` is retired

`?compare=` and `/compare/` were one feature built twice, and the older one was
worse on every axis: it could not cross an edition, it had no redline floor (so
two unrelated texts drew a wall of red), and its URL named a permalink plus a
modifier rather than naming the comparison. Deleted with it: `_compare_version()`
in `core/views/regulation.py`, the `compare` section key, and
`templates/provenance/_compare_diff.html`, which nothing else reached.

One comparison, one URL. The transition view is *not* this: two active versions
on one date is a real date overlap, which is a different fact and keeps its own
view.

### The arming mode became a prepared pair

The design below asked for a two-click arm/disarm mode, and then said a mode a
reader cannot leave is a trap. Both objections are answered by not having a
mode. The rail's existing one-click `compare` already worked without one,
because the anchor was implicit: the version you are viewing.

So "Compare versions" opens a comparison that is already chosen. The ladder is
`core.compare.prepared_pair`, in order:

1. The previous version in this edition — the tightest answerable question, and
   the least likely to fall through the redline floor.
2. A mapped predecessor in an earlier edition. **This is the good rung**: a
   provision with no local history crosses the edition boundary by itself, and
   that is exactly the provision whose interesting comparison is cross-edition.
3. The next version in this edition.
4. A mapped successor.
5. No control at all. An affordance that fails on click is worse than none.

The ladder is pure over data the caller already holds — the version, this
edition's chain, and the resolved lineage — so a page of results costs no query
beyond the batched lineage resolve that already ran.

There is no "stop comparing" control on `/compare/`, and none is needed. The
reader arrives by a link and leaves by browser back or by either side, each of
which links to its own permalink.

### The version timeline

`core.compare.version_timeline` and `templates/partials/_version_timeline.html`.
Every version behind the comparison on one date axis, the two on screen marked,
every other one click away. It is what makes a *prepared* pair safe to offer:
the ladder guesses, and a guess the reader cannot see is a guess they cannot
correct.

Eight rules it keeps:

- **One row per pin, not one row for both.** A single row must decide which pin
  a click moves, and every rule for deciding leaves pairs unreachable. "Move
  the nearer pin" cannot reach two ticks that are both nearer the same pin:
  each click replaces the one that has just moved, so the far pin never leaves,
  and a reader asking for the two most recent versions of a long-lived
  provision cannot get there. The row you click in is the pin that moves.
- **Real dates, not even spacing.** A decade of silence between two amendments
  is the fact the axis exists to carry. Marks that would land on top of each
  other stack into lanes (`TICK_LANE_GAP`) — a mark half-covering another mark
  draws nothing.
- **Each row's date follows its own dot, on its own line.** A date at the end
  of a row labels the row, and a row is not what the reader is reading. The
  track reserves a trailing margin so the last dot's date stays inside the box.
  Every other mark carries its date on hover, because labelling all of them
  collides at the first pair of amendments a month apart. The scale's two ends
  print under the axis, or the marks have positions but no units.
- **Three marks, one meaning each.** A filled circle is this side's version; a
  quiet outline circle is the version the other side holds — a real option but
  for that; a strong outline circle is a move. The strong outline is reserved
  for the only mark a click does anything to. The marks are joined by a faint
  dotted connector that stops at the row's last mark rather than running on to
  promise a choice that is not there.
- **A row omits the version it can never hold** — the newest for the earlier
  side, the oldest for the later one, since either would leave the other side
  nothing to be. Every pair is still reachable, in at most two clicks: move the
  later side first, then the earlier.
- **A click replaces history, it does not push it.** Five nudges must not cost
  six back presses to escape. The ticks are real anchors, so copy-link and
  middle-click still work; only the history entry changes.
- **One mapping hop each way.** Mapping rows are only emitted between adjacent
  editions, so a longer walk would invent links the data does not assert.
- **A locked edition is left off, not drawn and locked.** A tick is a control,
  and a control that fails on click is worse than none — the ladder's last rung
  again.

The axis is omitted when it would draw only the two pins already on screen
(`is_useful`).

## What is still open

Nothing. Every "Done when" item is met.

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

### The click route — superseded, kept for the reasoning

*Read "The arming mode became a prepared pair" above. What shipped is a
prepared pair and a per-row `compare` link, not an armed mode.*

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

- ~~Any two versions can be compared by URL, in either direction, within and
  across editions.~~ Done. The pair is ordered by effective date, not by which
  parameter it arrived in.
- ~~The chain rail offers a click route with a clear armed state and an
  escape.~~ Superseded. There is no armed state, so there is nothing to
  escape — see "The arming mode became a prepared pair".
- ~~The pairing basis is stated on every cross-edition comparison.~~ Done, in
  three states: same provision (says nothing, and that silence is what teaches
  the reader what the other two mean), mapped (cites the mapping and says the
  legislature did not enact the pair), and unmapped (a hand-built URL, said
  plainly).
- ~~Tier gating goes through `core/access.py`, with tests.~~ Done. The rule is
  applied once per side, never redefined.
- ~~The unreadable-diff and missing-mapping cases each have a test.~~ Done. The
  redline floor is a default and not a verdict: `?redline=on` overrules it.
- ~~The timeline draws every version across every edition, and moving a pin
  replaces history rather than pushing it.~~ Done, with one qualification worth
  recording: "every edition" means every edition the reader can open, reached
  by one mapping hop each way. A locked edition is left off rather than drawn
  and locked.

## Related

- `tasks/b-provision-exports.md` — a comparison is the most useful thing to
  export.
- Memory: `project_transition_pairing`, `project_table_image_html_precedence`.
