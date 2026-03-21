# 4 — Template Changes for Provenance Display

## What

Update templates to display Transition provenance: provision quotes, source
links, and not-yet-commenced warnings.

## Changes

### Provenance display (all result types)

Every search result gets an expandable "Legal basis" section:

- **Header:** "{regulation}, {provision_id}"
- **Body:** blockquote with `provision_quote`
- **Link:** `source_url` (when available)
- **Dates:** "In force {effective_date}" / "until {end_date}"

When provenance is not yet populated (blank `provision_quote`), show the
regulation and dates without a quote block. This handles the transition
period where Transition records exist but CCM hasn't populated the quotes
yet.

### National code multi-jurisdiction display

For national codes with multiple Transitions (NRC publication + provincial
adoption), show both:

> "Published by NRC as NBC 2025. Adopted in Saskatchewan by Ministerial
> Order MSO-123-2025, effective 2025-07-01."

### Transition compare view

Replace current `citation_text` display with:
- "{regulation}, {provision_id}" as the header
- Expandable provision quote block
- Keep `applicability_text` as the summary below the quote
- Source URL link

### Provision-level transitions

Replace current amber "Transition note" banner content:
- Currently: hand-written `citation_text` + `applicability_text`
- Updated: provision quote with regulation + provision_id header

### Not-yet-commenced provisions

When a node has a Transition with `effective_date > search_date`:
- Amber banner: "This provision does not commence until {effective_date}"
- Expandable quote of the commencement provision
- This is new functionality — currently we don't detect or display this

### Files to modify

- [ ] `templates/partials/search_results_partial.html` — provenance section,
      transition banners, uncommenced warnings
- [ ] `templates/partials/_result_document_block.html` — provision quote
      block styling
- [ ] CSS for quote blocks, expandable sections, amber banners
- [ ] `api/formatters.py` — ensure Transition fields are passed through
      to template context

## Verification

- Search results show provenance when populated
- Graceful fallback when `provision_quote` is blank
- Transition compare view shows quotes instead of hand-written text
- Not-yet-commenced banner appears for future-dated provisions
- National codes show publication + adoption chain

## Depends On

- Task 2 (code paths pass Transition data to templates)
- Can be developed in parallel with task 2 if template context format is
  agreed

## Notes

- This task can start before CCM populates the quotes — the templates
  should handle blank quotes gracefully
- The "not-yet-commenced" banner is new UX functionality, not just a
  reskinning of existing display
