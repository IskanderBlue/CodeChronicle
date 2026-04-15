# 4 — Provenance Rail Display

## What

Add a provenance rail alongside each search result that shows commencement
and amendment history. Immediately visible on card expand — not behind a
toggle. Includes a copy button for the full structured legal reference.

**Audience**: forensic engineers who need certainty about what was in force
on what date. This is the primary differentiator of CodeChronicle.

## Layout

### Single result card (non-transition)

Provenance rail sits to the **right** of the content area:

```
┌──────────────────────────────────────────────────────┐
│  § 3.1.4.7. — Fire Separations        Score: 0.85   │
│  ┌─ CONTENT ──────────────────┐  ┌─ PROVENANCE ───┐ │
│  │                            │  │ In force        │ │
│  │  [provision text / PDF]    │  │  2015-01-01     │ │
│  │                            │  │  O.Reg. 332/12  │ │
│  │                            │  │  s. 4.4.1.1(2)  │ │
│  │                            │  │                 │ │
│  │                            │  │ ● O.Reg. 139/17│ │
│  │                            │  │   s. 82         │ │
│  │                            │  │   ▸ 4 earlier   │ │
│  │                            │  │                 │ │
│  │                            │  │ [📋 Copy ref]   │ │
│  └────────────────────────────┘  └─────────────────┘ │
└──────────────────────────────────────────────────────┘
```

Content area: `sm:col-span-3`. Provenance rail: `sm:col-span-1`.
Use `grid sm:grid-cols-4` inside the expanded card body.

### Transition compare card

Provenance rails bookend the content — **left** for older, **right** for
current:

```
┌────────────────────────────────────────────────────────────────────┐
│  Transition compare                                                │
│  ┌─ PROV ──┐  ┌─ OLD ──────────┐  ┌─ NEW ──────────┐  ┌─ PROV ─┐│
│  │ v07     │  │ [old content]  │  │ [new content]  │  │ v11    ││
│  │ 2015-01 │  │                │  │                │  │ 2017-07││
│  │ 332/12  │  │                │  │                │  │ 332/12 ││
│  │         │  │                │  │                │  │        ││
│  │ ●361/13 │  │                │  │                │  │ ●139/17││
│  │ s. 34   │  │                │  │                │  │ s. 82  ││
│  │ ▸2 more │  │                │  │                │  │ ▸4 more││
│  │         │  │                │  │                │  │        ││
│  │ [📋]    │  │                │  │                │  │ [📋]   ││
│  └─────────┘  └────────────────┘  └────────────────┘  └────────┘│
└────────────────────────────────────────────────────────────────────┘
```

Use `grid sm:grid-cols-6` — prov rails each `sm:col-span-1`, content panes
each `sm:col-span-2`.

### Mobile

Provenance collapses to a section **below** the content (not a sidebar).
Same information, stacked vertically.

## Color Coding

### Edition-general provenance (inherited)

When a section's commencement is the edition default and it has no
amendments (base regulation text):

- Provenance rail: `text-neutral-500 dark:text-neutral-400`
- No left border accent
- This is the quiet default — most sections look like this

### Provision-specific provenance

When a section has its own commencement override OR has amendments:

- Provenance rail: left border `border-l-2 border-primary-400
  dark:border-primary-500`
- Text: `text-neutral-700 dark:text-neutral-300` (slightly more prominent)
- Signals "this provision has its own story — look here"

## Provenance Rail Content

### Commencement section

Always shown. Two variants:

**Edition-level (inherited):**
```
In force
  2014-01-01
  O. Reg. 332/12
  s. 4.4.1.1(1)
```

**Provision-specific (overridden):**
```
In force (provision-specific)
  2015-01-01
  O. Reg. 332/12, s. 4.4.1.1(2)
  "...this Regulation comes into force..."
```

When provision_quote is available, show first ~80 chars with expandable
full text. When blank (not yet populated), show regulation + date only.

### Amendment section

Only shown when the section has Amendment records.

**Default (most recent only):**
```
● Amended by
  O. Reg. 139/17, s. 82
  Effective 2017-07-01
  ▸ 4 earlier amendments
```

**Expanded:**
```
● Amended by
  O. Reg. 139/17, s. 82 — 2017-07-01
  O. Reg. 88/19, s. 156 — 2020-01-01
  O. Reg. 361/13, s. 34 — 2015-01-01
  O. Reg. 360/13, s. 12 — 2015-01-01
  O. Reg. 332/12 (base regulation)
```

The "N earlier amendments" is an Alpine.js toggle. The full chain is
rendered in the HTML but hidden by default.

### No-provenance fallback

When no Transition or Amendment data exists (not yet populated):

```
Provenance not yet available
  Effective: 2015-01-01
  (from edition metadata)
```

Shows the bare date from `CodeEdition.effective_date` with a note that
full provenance is pending. Graceful degradation.

## Copy Button

Clipboard icon button at the bottom of the provenance rail. Copies:

```
OBC 2012, Div B, § 3.1.4.7. — Fire Separations
In force: 2015-01-01 (O. Reg. 332/12, s. 4.4.1.1(2))
Amended by: O. Reg. 139/17, s. 82 (2017-07-01)
```

For unamended base regulation provisions:

```
OBC 2012, Div B, § 3.1.4.7. — Fire Separations
In force: 2014-01-01 (O. Reg. 332/12, s. 4.4.1.1(1))
```

The copy string is built in JavaScript from data attributes on the
provenance rail element. Not a server-side template — avoids Django
template complexity for string formatting.

## Files to Modify

### New partial
- [ ] `templates/partials/_provenance_rail.html` — the provenance rail
      component, included by search results partial

### Modified templates
- [ ] `templates/partials/search_results_partial.html` — wrap content in
      grid layout, include provenance rail for each result
- [ ] `templates/partials/_result_document_block.html` — adjust width to
      share space with provenance rail

### CSS
- [ ] Provenance rail styling (compact text, accent border)
- [ ] Mobile responsive: rail → stacked section below

### JavaScript
- [ ] Copy button: build reference string from data attributes, copy to
      clipboard, show brief "Copied" feedback
- [ ] Amendment expand/collapse (Alpine.js)

### Backend
- [ ] `api/formatters.py` — include commencement and amendment data in
      result context (query Transition + Amendment for each node)
- [ ] `api/search/orchestration.py` — prefetch Transitions and Amendments
      for matched nodes (avoid N+1)

## Verification

- Single result: provenance rail visible immediately on expand
- Transition compare: provenance rails on both sides
- Base regulation provision: neutral styling, no amendment section
- Amended provision: accent border, amendment chain shown
- "N earlier" expands to full chain
- Copy button produces correct formatted string
- Mobile: stacked layout, same information
- No provenance: graceful fallback with edition date
- National codes: shows publication + adoption chain

## Depends On

- Task 2 (code paths pass Transition + Amendment data to templates)
- Can be developed in parallel if template context format is agreed:
  - `result.commencement` → dict with regulation, provision_id, quote, date
  - `result.amendments` → list of dicts, most recent first
  - `result.is_provision_specific` → bool (has own commencement or amendments)

## Notes

- This is the most user-visible change — the provenance rail is the
  primary new feature for forensic engineers
- Start with the non-transition card layout, then adapt for compare view
- The copy button string format may evolve based on user feedback
