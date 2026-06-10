# Onboarding & "how it works" — task card

**Goal:** make CodeChronicle legible on first contact. User feedback: people don't
know what to type, what's covered, or that a query for an out-of-scope place/date
silently returns Ontario results. The fix is *in-context* onboarding (empty-state
examples + honest scope + a help panel), **not** a separate landing page users bounce
off before reaching search.

All work lives on the search page (`templates/search.html`, `core/views/search.py::home`,
`core/views/search.py::search_results`). No new top-level route.

---

## Prerequisite — expose a discrete `coverage_end` (already done) + `coverage_start` only if needed

`coverage_end` is already a real `DateField` on `CorpusCurrency` and already flows to
every template via `core/context_processors.py::masthead_currency`. The corpus **start**
date is computed (`first_eff`, `core/models.py:925`) but only baked into the
`corpus_span` *string* (`core/models.py:943`).

We only need a discrete `coverage_start` for the date-picker `min` (#3). The placeholder
(#1) no longer needs it — see below. If we want `min`, add
`coverage_start = models.DateField(null=True, blank=True)` to `CorpusCurrency`
(`core/models.py:848`), set it from `first_eff` in `refresh_corpus_currency()`, migration
+ reload, and surface it in the context processor alongside `coverage_end`. Parsing it
back out of the display string is the runtime-transform-on-dirty-data pattern we avoid.
[[feedback_clean_data]] [[project_masthead_currency]]

---

## 1. Placeholder — just change the year (decided: keep it simple)

`search.html:94` hardcodes `"… Ontario, May 1993"`, which is outside coverage. **Do not**
make this data-driven — it doesn't need to track the corpus, it only needs to be valid,
and a fixed in-range date stays valid as we add data. **Change `May 1993` → `2016`.**
Keep the rest of the placeholder shape.

## 2. Clickable example queries (highest ROI)

The empty state (`search.html:148-155`, "No search performed yet") is recurring, free
teaching real estate — re-shown every visit with no query. Put 3–5 one-click example
chips there.

- Each chip fills the `#query` input and submits the form. The auto-submit machinery
  already exists: `home` reads `?q=` → `initial_query`, and `search.html:169-180`
  triggers the form on load when `initial_query` is set. Chips can either be
  `<a href="?q=…">` (server round-trip, dead simple) or a tiny JS handler that sets
  `#query.value` and calls `htmx.trigger(form,'submit')` (no reload). Prefer the JS
  path — it reuses the existing loading-spinner swap and avoids a full nav.
- **Examples must be real and cover both query modes.** Only one edition is loaded so far,
  so keep the dates plausibly in-range (2016-ish) and Ontario. Include **both**:
  - at least one **specific-article** query, e.g. `"11.5.1.1."` or
    `"fire separation 3.1.8.1."` — exercises the section-reference path
    (`extract_section_references`);
  - at least one **general keyword** query, e.g.
    `"fire separation between dwelling units, Ontario, 2016"` — exercises the
    TF-IDF/keyword path. Source topics from `config/keywords.VALID_KEYWORDS` so they hit.
  - Hardcoding the chips in the template is fine given a single edition; revisit only if
    coverage expands. (No need for the server-rendered/`coverage_start` machinery here.)

## 3. Date picker bounded + jurisdiction as a full word

- **Bound the date input.** `search.html:111` `<input type="date" name="date">` has no
  `min`/`max`. Add `min="{{ coverage_start|date:'Y-m-d' }}"` and
  `max="{{ coverage_end|date:'Y-m-d' }}"`. Browser-native enforcement; the `AS-OF`
  default already sits at `coverage_end`. (Server-side validation still matters — see #4
  — since `min`/`max` are advisory and the field can be bypassed.)
- **Spell out the jurisdiction.** `search.html:100-104` shows `JUR · ON`. Display the
  full word **Ontario** (the abbr/title can stay as a tooltip), and keep the
  `<input type="hidden" name="province" value="ON">` so the posted payload is unchanged.
  This is pure presentation — `search_results` reads `province` from POST, still `"ON"`.

## 4. Surface LLM-detected limitations (the trust fix)

Today the form **hardcodes** `province=ON` (hidden input, `search.html:104`), and
`search_results` passes that as `province_override` — so the parser *does* detect
"British Columbia" from the text, but we silently override and search Ontario. A user
who asks about BC gets Ontario results with no explanation → "this is broken."

The parsed params already flow back: `run_search` returns `parsed_params`
(`core/views/search.py:488-489` already pulls `date`/`keywords` from it). The parser
emits `province` (full enum, `api/llm_parser.py:51-68`) and `date`. We have everything
needed to *compare and warn* without changing what we search:

- **Out-of-scope province.** If `parsed_params["province"]` ≠ `"ON"`, render a notice in
  the results partial: *"You asked about British Columbia. We currently cover Ontario
  only — showing Ontario results."* (Don't refuse — degrade gracefully and be honest.)
  Copy (decided): expansion is a **medium/long-range** plan, much to do first, so say
  *"not yet"* — e.g. *"We don't cover British Columbia yet — see the roadmap on our
  [pricing page](…) for what's planned. Showing Ontario results."* Link the roadmap on
  the pricing page (`templates/pricing.html` / `pricing_early_access.html`), don't
  restate the roadmap inline.
- **Out-of-range date.** If `parsed_params["date"]` falls outside
  `[coverage_start, coverage_end]`, **show the explanation and no results — do not fall
  back to the nearest edition** (decided: don't blow smoke). Copy: *"<date> is outside
  our coverage (<start> – <end>). We don't have a code edition for that date."* There's
  already a sibling path for malformed dates (`invalid_date`, `search.py:477`) — add an
  `out_of_range` flag the same way and render it in `partials/search_results_partial.html`.
- Compute these in the service/formatter layer and pass booleans + the detected values
  to the partial; the template stays logic-light. One shared notice block, not scattered
  conditionals.

> This is the item that most directly answers the feedback: the app currently *knows*
> the query is out of scope and says nothing. Saying it converts "broken" into "not
> covered yet," which is a trust win and costs one comparison.

## 4b. Section-reference trailing period — NO BUG FOUND, DROPPED FROM SCOPE

Reported: *"our id-specific check requires the trailing period; `1.4.3.2.` works but
`1.4.3.2` won't be caught."* **Could not reproduce.** Verified by running the real
codebase functions on both forms:

- `extract_section_references` (regex, `llm_parser.py:14`) catches **both** `1.4.3.2`
  and `1.4.3.2.` (the trailing dot is `\.?` — optional).
- `_ref_parts` (`engine.py:100`) normalizes via `tuple(seg for seg in t.split(".") if
  seg)`, so both forms collapse to `('1','4','3','2')` *before* any comparison.
- `_match_reference(ref, "1.4.3.2.", [])` returns `(3.0, 'exact_id')` for **both** forms.
- The only other id-handling site, `regulation.py:142`, already appends the dot if missing.

So the trailing period is irrelevant everywhere I can find. **Decision: dropped — no bug.**
The normalization (`split(".")` dropping empty segments) already makes both forms
equivalent. Re-open only if a concrete failing query surfaces; if so, look at the
click-to-scroll `fragment`/anchor id in the viewer/results, not reference *matching*.

## 5. "How this works" panel

For the audience (people researching historical code provisions) a *persistent,
re-referenceable* explainer beats a one-time forced tour. Avoid coachmarks / multi-step
overlays — teach the mental model, not the chrome.

- A small `How it works` / `?` affordance near the search bar (next to the meta strip at
  `search.html:121-123`) opening an Alpine `x-show` disclosure panel (`x-cloak` already
  in `base.html`). [[project_tailwind_hidden_display_order]]
- Content, in plain language: (a) the pipeline — *natural-language question → Claude
  parses jurisdiction + as-of date + keywords → searched against the in-force edition*;
  (b) scope — Ontario only, covered window `coverage_start`–`coverage_end`; (c) what a
  good question looks like (mirror the chips); (d) a one-liner on the result viewer +
  edition lineage so the deep features get one signpost.
- Dismissible, remembered in `localStorage` so it doesn't nag returning users, but
  always re-openable from the affordance.

---

## Sequencing (ship in this order — each stands alone)

1. `coverage_start` plumbing (prereq; unblocks 1, 3, 4).
2. Bounded date input + full-word jurisdiction (#3) — tiny, pure template.
3. Example chips + in-range placeholder (#1, #2) — biggest activation gain.
4. Limitation notices (#4) — the trust fix.
5. How-it-works panel (#5) — for the "tell me more" cohort.

## Acceptance criteria

- Placeholder reads `2016` (not 1993); every example chip returns ≥1 real result, and the
  chips include at least one specific-article query and one keyword query.
- Date picker cannot be set (via UI) outside `[coverage_start, coverage_end]`; server
  still validates and explains an out-of-range / malformed date.
- The search bar reads "Ontario", not "ON"; POST payload still sends `province=ON`.
- A non-Ontario province produces a *"not yet"* notice linking the pricing-page roadmap;
  an out-of-coverage date produces an explanation **with no results** (no nearest-edition
  fallback). Neither silently returns Ontario-as-if-asked.
- How-it-works panel opens/closes, survives reload as dismissed, re-openable.

## Resolved decisions

- Placeholder: hardcode `2016`, not data-driven.
- Province notice: "not yet" framing; roadmap lives on the pricing page (link it).
- Out-of-range date: explanation only, no nearest-edition fallback.
- Example chips: plausible 2016/Ontario; one specific-article + one keyword; single
  edition so hardcoding chips is fine.
- Section-reference trailing period: **dropped — no bug** (already normalized; see §4b).

## Open questions

- Pricing page: confirm the exact roadmap anchor/section to link from the province notice.
