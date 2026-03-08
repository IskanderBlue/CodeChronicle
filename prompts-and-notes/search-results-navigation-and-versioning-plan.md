# Search Results Navigation and Versioning Plan

Current state: when a user searches, we show all returned results in ranked order. Each result is rendered as a card, and when a PDF is available the user can view the matching section inline starting from the result's page. The current experience is flat, result-first, and query-driven; it does not yet fully support hierarchical grouping, transition-aware comparison, or broader code browsing.

---

## 0.0 Metaplan — Phase Dependencies

```
Phase 1: Accordion results + multi-page viewing
Phase 2: Result grouping (parent/child)         — depends on Phase 1
Phase 3: Transition metadata + overlap display   — depends on Phase 2
Phase 4: Viewer mode (code browsing)             — independent of Phases 2–3
Phase 5: Mobile refinements                      — depends on Phases 2–3
```

- Phases 1–3 are sequential; each builds on the previous.
- Phase 4 (viewer mode) is independent and can be built in parallel with or after any phase.
- Phase 5 should follow Phases 2–3 since it refines their UI for smaller screens.

---

## Phase 1 — Accordion Results + Multi-Page Viewing

Before frontend work in this phase, update CodeChronicle's internal node model to match the PDF rendering behavior we actually want from newer CodeChronicleMapping output.

- Deprecate `bbox` on `CodeMapNode`; CC will not do interior highlight overlays for returned articles/tables.
- Keep `page` and `page_end` as the first and last page of the returned result span.
- Add `initial_page_top` and `final_page_bottom` to `CodeMapNode`.
- Import those bounds from mapping output as CC-facing rendering data rather than storing the full upstream bbox structure.
- Rendering rule: clip the first page from `initial_page_top` downward, clip the last page at `final_page_bottom`, and show intermediate pages full-height.
- For single-page results, apply both `initial_page_top` and `final_page_bottom` on the same page.
- Store `initial_page_top` and `final_page_bottom` in the same PDF coordinate convention already used by CC's PDF.js code: PDF points with origin at bottom-left.

### 1.1 Accordion result list

Replace the current flat card list with an accordion where one result is open at a time.

- Pressing down (keyboard or button) advances to the next result.
- Only one result card is expanded at a time; the rest show a collapsed summary (section ID, title, code edition, score).
- Clicking a collapsed card opens it and collapses the previously open one.

**🎨 Designer review:** Accordion card layout, collapsed vs expanded states, keyboard navigation affordances, transition animation.

### 1.2 Multi-page PDF viewing within a result

The inline viewer must support a result-bounded PDF span using `page`, `page_end`, `initial_page_top`, and `final_page_bottom`.

- Default initial render opens on the first relevant page.
- Add previous/next page controls within the result card.
- Keep the PDF clipped to the result card rather than forcing a full-document browsing jump.
- On the first page, clip from the top boundary of the returned article/table downward.
- On the last page, clip at the bottom boundary of the returned article/table.
- On intermediate pages, show the full page height.
- Do not build highlight overlays for the returned article/table; the bounded PDF span itself is the emphasis.
- If any boundary is missing, fall back to rendering the full relevant page/span rather than failing.

### 1.3 Result justification (post-MVP, stub only)

- Reserve space in the accordion card for optional result justification (e.g. "keyword X appears Y times").
- Do not implement the logic in this phase; just ensure the card layout can accommodate it later.
- Keep it lightweight and collapsible when implemented.

---

## Phase 2 — Result Grouping (Parent/Child)

### 2.1 Backend: group sibling hits in the formatter

Keep retrieval at the article / subsection / table level. Do not change the search engine's retrieval unit. Add a post-search grouping step in `api/formatters.py`.

- Grouping is based on node hierarchy coverage, not PDF geometry.
- When >80% of a parent's direct children are returned, collapse them into a single grouped result under the parent.
- When <80% are returned, show the matching children as individual results.
- When only one child matches, keep the card focused on that child (no grouping).

Clarification: the 80% threshold means 80% of direct child nodes (for example, articles under a subsection), not 80% of pages.

### 2.2 Frontend: grouped accordion cards

Within a grouped card, show all child articles in order:

- The highest-scoring child is visually highlighted (stronger border/background).
- Children that were actually returned from the search render at full emphasis.
- Sibling articles that were *not* returned (filled in for context) render in a lowlighted/de-emphasized style.

**🎨 Designer review:** Highlight treatment for top-scoring child, lowlight treatment for non-matching siblings, grouped card header design, expand/collapse behavior within a grouped card.

### 2.3 Standalone results

If a result has no siblings or its siblings don't meet the 80% threshold, render it as a standalone accordion card (same as Phase 1 behavior).

---

## Phase 3 — Transition Metadata + Overlap Display

### 3.1 Transition metadata model (Tier 1 — MVP fields)

Add an explicit transition metadata model. Start as curated JSON in `config/transitions.json`, later migrate to DB tables.

Tier 1 fields (implement now):

- `old_edition` / `new_edition` — references to edition IDs
- `overlap_start` / `overlap_end` — date range where both editions are valid
- `transition_type` — enum: `grace_period`, `in_stream_project`, `phased_coming_into_force`
- `applicability_text` — short description of what the overlap applies to (e.g. "buildings permitted by X")
- `citation_text` — regulation reference string

Tier 2 fields (defer to later phase):

- `scope_type` — `edition`, `section`, or `table` (for section-level transitions)
- `scope_identifier` — node ID for section-level scope
- `display_priority` / ordering
- `citation_url` — link to source regulation
- `source_excerpt` — verbatim regulation text
- `human_summary` — concise UI summary

### 3.2 Backend: overlap-aware edition resolution

`config/code_metadata.py:get_applicable_codes()` currently returns one edition per system/date.

- Continue to search by effective date as the primary query.
- After primary results are returned, check `config/transitions.json` for any active transitions that overlap the queried date.
- If a transition applies, fetch results from the older edition and attach them to the response as secondary/comparison results.
- Tag each result with a `transition_context` object so the formatter knows *why* two editions appeared (not just that they both matched).

Ranking across overlapping editions: when a transition produces two hits for the same section, merge them into one grouped result. Use the higher relevance score of the two. Display the version matching the queried date more prominently.

Note: there is a small risk that keywords appear in one edition but not the other. Accept this risk for now; the effective-date edition is always the primary search target.

### 3.3 Frontend: transition banner and comparison display

When a transition applies to a result:

- Show a transition banner at the top of the grouped result card containing:
  - Queried date
  - New version effective date
  - Old version last date of overlap / continued applicability
  - Transition type label
  - Short applicability statement
  - Citation text
- This banner must be visible before the user expands deep content.

On desktop: show old and new versions in adjacent panes within the card.

**🎨 Designer review:** Transition banner layout and content hierarchy, side-by-side pane layout, visual emphasis for the query-matching version vs the comparison version (e.g. stronger border/badge on the primary, muted treatment on the secondary).

### 3.4 Curate initial transition data

Enter the known transitions as curated JSON. The five known cases:

- **BCBC 2024** (effective 2024-03-08): 2018 BCBC earthquake design and adaptable dwelling unit requirements continued for permits applied for until 2025-03-09. In-stream project exemptions.
- **QCC Building 2020** (effective 2025-04-17): Previous Chapter I may apply if work begins before 2026-10-17.
- **QECB 2020** (effective 2024-07-13): Previous Chapter I.1 may apply if work begins before 2025-01-13.
- **QPC 2020** (effective 2024-07-11): Previous Chapter III may apply if work begins before 2025-01-11.
- **QSC 2020** (effective 2025-04-17): Previous Chapter VIII may apply before 2026-10-17. Partial delayed coming-into-force for some provisions.

---

## Phase 4 — Viewer Mode (Independent)

### 4.1 Viewer mode UI

A separate full-page view for browsing code content beyond the matched result. This is independent of the search results accordion.

- Entry point: a "Browse in context" button (or similar) on any result card.
- Loads the code's section hierarchy: division → section → subsection → article.
- Starts the user at the clicked result's `page`, positioned to `initial_page_top`.
- User can scroll up and down through the content freely.
- A visible close/return button exits viewer mode and returns to search results.
- The browser Back button also returns to search results.

**🎨 Designer review:** Viewer mode layout, section hierarchy sidebar or navigation, close/return button placement, scroll behavior, visual distinction from search mode.

### 4.2 Edition navigation in viewer mode

Within viewer mode, provide controls to switch between editions of the same code.

- Buttons or dropdown to step to previous/next edition.
- Make it obvious when the user is viewing a different edition than the one matched by their query (e.g. label, muted border).
- No split view across editions — pages do not align across editions, so side-by-side would be misleading.

### 4.3 Visual emphasis for query context

- Highlight the query-matching edition/version with stronger visual treatment.
- Keep dates visible for all editions so the user understands the timeline.
- Label non-query-matching editions as "browse context" rather than hiding metadata.

---

## Phase 5 — Mobile Refinements

### 5.1 Transition comparison on mobile

Stacking two full code sections vertically on mobile makes comparison impractical.

- Use a tab-based switcher (Old / New tabs) instead of stacking.
- Consider a diff-highlight mode that marks changed content.
  - **Legal note:** verify whether we can store diff text. We could potentially store diff bounding boxes, but shaping those is non-trivial. Defer diff implementation until legal and technical feasibility are confirmed.

**🎨 Designer review:** Tab switcher design, diff highlight treatment (if feasible), overall mobile card layout for grouped and transition results.

### 5.2 Accordion and grouping on mobile

Verify that the accordion and grouping behaviors from Phases 1–2 work well on small screens. Adjust touch targets, card sizing, and collapsed summary layout as needed.

**🎨 Designer review:** Mobile accordion interaction, touch targets, collapsed card density.

---

## Design Decisions Record

Decisions made during planning, for reference:

| Decision | Choice | Rationale |
|---|---|---|
| Grouping threshold | >80% of parent's children returned | Concrete, testable; avoids ambiguity |
| Result list style | Accordion, one open at a time | Keeps focus; avoids ten expanded cards |
| Non-matching siblings in group | Shown but lowlighted | Context without false emphasis |
| Search strategy for transitions | Search by effective date, tack in older editions after | Simpler; keyword mismatch risk is small |
| Transition ranking | Merge into one result, use higher score | Avoids duplicate results for same section |
| Mobile transition display | Tabs, not stacking | Stacking is impractical for comparison |
| Viewer mode split view | Not implemented — pages don't align across editions | Would be misleading |
| Result justification | Post-MVP | Nice-to-have, don't let it creep into initial scope |
| Transition metadata start | Curated JSON file | Simpler than DB tables; migrate later |
| Result PDF geometry | `page` + `page_end` + `initial_page_top` + `final_page_bottom` | Matches CC's actual bounded-span rendering intent better than bbox overlays |
| Grouping threshold basis | Direct child nodes, not pages | Grouping is about result hierarchy, independent of PDF span geometry |

---

## Example transitions to support

- **BCBC 2024** (effective 2024-03-08): The 2018 BC Building Code's requirements for earthquake design and adaptable dwelling units continued to be in effect for permits applied for until March 9, 2025. In-stream projects, where certain criteria are met, are exempt from the 2024 BC Building Code's adaptable dwelling unit and earthquake requirements.
- **QCC Building 2020** (effective 2025-04-17): The amendments to Chapter I, Building, of the Construction Code came into force on 17 April 2025 (Order in Council 437-2025, 2025 G.O. 2, 994). Nevertheless, Chapter I of the Construction Code as it read on 16 April 2025 may apply to the construction or transformation of a building, as defined in that Chapter, provided that the work begins before 17 October 2026.
- **QECB 2020** (effective 2024-07-13): The amendments to Chapter I.1, Energy Efficiency of Buildings, of the Construction Code came into force on 13 July 2024 (Order in Council 850-2024, 2024 G.O. 2, 1868). Nevertheless, Chapter I.1 of the Construction Code as it read on 12 July 2024 may apply to construction work referred to in sections 1.1.2 and 1.1.3, provided that the work begins before 13 January 2025.
- **QPC 2020** (effective 2024-07-11): The amendments to Chapter III, Plumbing, of the Construction Code came into force on 11 July 2024 (Order in Council 983-2024, 2024 G.O. 2, 2635, amended by Order in Council 1071-2024, 2024 G.O. 2, 3129). Nevertheless, Chapter III of the Construction Code as it read on 10 July 2024 may apply to construction work on a plumbing system, provided that the work begins before 11 January 2025.
- **QSC 2020** (effective 2025-04-17): The amendments to Chapter VIII, Buildings, of the Safety Code came into force on 17 April 2025 (Order in Council 438-2025, 2025 G.O. 2, 1175), except that sub-subsection VIII of subdivision 1 of Division IV will come into force on 2 December 2027 (Order in Council 1035-2015, 2015 G.O. 2, 3189, and am.); Article 2.1.3.7. of Division B of the NFC will come into force on 17 April 2028. Nevertheless, Chapter VIII of the Safety Code as it read on 16 April 2025 may apply the day before 17 October 2026.

---

## Implementation notes from the current codebase

- `templates/partials/search_results_partial.html` currently renders a flat list of result cards.
- `templates/search.html` currently renders the PDF viewer from a single starting page even though results already carry `page_end`.
- `core/models.py` currently stores `bbox` on `CodeMapNode`; Phase 1 should replace that assumption with `initial_page_top` / `final_page_bottom` span bounds.
- `templates/search.html` already interprets PDF geometry in PDF.js page coordinates, so storing top/bottom in that same bottom-left-origin coordinate system is the easiest path for CC.
- `core/models.py` already includes `parent_id` on `CodeMapNode`, which can support result grouping.
- `core/models.py` and `config/metadata.json` already include edition-level regulation/amendment metadata.
- `config/code_metadata.py:get_applicable_codes()` currently returns one edition per system/date and will need overlap-aware logic in Phase 3.
- Code hierarchy levels in maps: division → section → subsection → article. Viewer mode (Phase 4) should respect this hierarchy.
