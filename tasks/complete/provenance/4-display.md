# 4 — Display: Provision View, Provenance, Regulation Browsing

## What

Build the user-facing views for provenance-aware provision display,
regulation chain browsing, and transition comparison.

## Depends On

- Task 3 (code paths provide version + provenance data to templates)
- Can be developed in parallel if template context format is agreed

## Aesthetic Direction: Archival Precision

The interface communicates authority, precision, and trustworthiness.
Every design choice should answer: "Does this help the engineer trust
and verify the answer?"

### Typography

- **Legal content** (provision text, regulation citations): Literata —
  a serif designed for long-form legal reading. Variable weight for
  hierarchy. Generous line-height (1.7+).
- **References** (provision IDs, regulation numbers, dates): JetBrains
  Mono — monospace signals "this is an exact reference." Anything the
  engineer might need to transcribe or verify.
- **UI** (buttons, labels, navigation): System sans-serif stack.

### Color

Existing teal primary + slate neutral + amber accent, refined:

- **Provenance spine**: Teal for base provisions. Muted brick/terracotta
  for amended provisions — signals "something changed" without alarm.
- **Transition warning**: Warm amber (already partially in place).
- **Content background**: Near-white light mode, true dark (not gray)
  dark mode. Document images and provision text should feel like they're
  on paper.

### Motion

Minimal — trust-critical interface. No decorative animations.

- Accordion expand/collapse: 200ms ease-out, no bounce.
- Copy button: "Copied" tooltip fades after 1.5s.
- Amendment chain expand: simple slide-down. List items stagger with
  30ms delay (reads as "ordered" without being decorative).
- Page image load: fade in from 0 opacity over 300ms.

## Provision View (Search Result)

Vertical single-column flow. Provenance is an integrated header, not a
separate metadata block.

```
 +-----------------------------------------------------+
 |                                                     |
 |  Div B . S 3.1.4.7.                                |
 |  FIRE SEPARATIONS                                   |
 |                                                     |
 |  | In force 2015-01-01                              |
 |  | O. Reg. 332/12, s. 4.4.1.1(2)                   |
 |  |                                                  |
 |  | * O. Reg. 139/17, s. 82  .  2017-07-01          |
 |  |   4 earlier amendments >                         |
 |  |                                                  |
 |  | Next: O. Reg. 88/19 (not in force until          |
 |  |       2020-01-01)                           [Cp] |
 |                                                     |
 +-----------------------------------------------------+
 |                                                     |
 |  [provision text — HTML or page image]              |
 |                                                     |
 +-----------------------------------------------------+
 |                                                     |
 |  Table 3.1.4.7. FIRE RESISTANCE RATINGS             |
 |  +-----------------------------------------------+  |
 |  |                                               |  |
 |  |  [table image(s) in scrollable container]     |  |
 |  |                                               |  |
 |  +-----------------------------------------------+  |
 |  Note (1): For buildings of...                      |
 |                                                     |
 +-----------------------------------------------------+
 +-----------------------------------------------------+
 |                                                     |
 |  v Appendix Notes (3)                               |
 |    A-3.1.4.7.(1) — [note text/image]                |
 |    A-3.1.4.7.(2) — [note text/image]                |
 |    A-3.1.4.7.(3) — [note text/image]                |
 |    Each with mini provenance line if amended         |
 |                                                     |
 +-----------------------------------------------------+
 |  > View amending regulation (O. Reg. 139/17)        |
 +-----------------------------------------------------+
```

### Provenance header

Always visible. Integrated with provision identity:

- **Provision ID** in monospace. Section sign (S). Title in small caps
  or uppercase tracking.
- **Left border accent** ("spine") runs full height of the provenance
  section. Teal for base, brick/terracotta for amended.
- **Amendment chain**: most recent shown; "N earlier" is Alpine.js toggle
  revealing the rest with staggered slide-down.
- **"Next amendment"** line is the trust closer — visually distinct,
  muted styling with "not in force" clearly readable.
- **Copy button** at trailing edge of provenance section.

### Content area

- **Page images**: shown cropped/focused to the provision's bbox by
  default. Paper-like container (subtle warm tint, hairline border).
  "View full page" toggle shows the uncropped image with the bbox
  region highlighted (tinted overlay). Provisions spanning columns or
  pages show multiple crops stacked vertically in reading order.
- **Amended provision (v1+)**: Rendered HTML in matching container.
  Literata serif, generous line-height.
- Both container styles match — scrolling from page image to HTML
  shouldn't feel like a visual jump.
- Same image component used for provision page images, table images,
  and gazette clause images in the regulation browsing view.

### Tables

Tables are `ProvisionVersionTable` records, displayed inline.

- Caption above in small caps.
- Render rule — per version, per table:
  - If `html` is non-empty, render it directly inside the table container
    with `|safe`. Trust boundary is CCM, not the template: same
    convention already in use for `CodeEditionProvisionVersion.html`
    and `ProvisionVersionTable.notes`-adjacent HTML (see the `|safe`
    calls in `templates/partials/_result_document_block.html`). If a
    future source is less trusted than e-Laws, add the sanitizer in
    CCM, not here — keeping the render path uniform.
  - Else render `images` in a scrollable container (`overflow-y: auto`,
    max-height). Multi-page tables scroll vertically — no pagination
    clicks. Engineers scan tables looking for specific rows; free
    scrolling is faster than clicking through 20 pages.
- Both forms share the same outer container styling so the switch
  between HTML and image tables is not visually jarring: subtle
  blue-gray tinted background (engineering drawings convention),
  hairline border, caption band on top.
- HTML tables inherit the `prose` stack already applied to provision
  HTML. Specific typographic refinements (Literata for cells, numeric
  alignment, header weighting) layer on via a `provision-table-html`
  class without changing the render contract.
- Notes below with thin top rule, smaller size. When the HTML form
  already embeds notes, CCM sends `notes=""` — don't render the notes
  block in that case (avoid duplication).

#### Why the dual representation

`html` is available only where e-Laws (or another structured source)
publishes a point-in-time form. That's typically base v0 of the source
edition and the latest consolidation; historical amended versions stay
image-only. Picking per-version keeps the authoritative artifact on
screen for each slice of history without forcing a reconstruction pass.

### Mobile

Same vertical flow, just narrower. Single-column design is inherently
responsive. No layout changes needed.

## Transition View

When the query date falls in a transition period, two versions are active.
Stacked layout with the transition provision text as block quote header:

```
 +- TRANSITION ACTIVE ------------------------------+
 |                                                   |
 |  > "The code as it read on 2014-12-31 applies    |
 |  >  to buildings whose permit was applied for     |
 |  >  before 2015-01-01"                            |
 |  >             -- O. Reg. 332/12, s. 4.1.2       |
 |                                                   |
 +-----------+---------------------------------------+
 | v O. Reg. 139/17 version                          |
 |   [provenance + text + tables]                    |
 |                                                   |
 | > O. Reg. 332/12 version (collapsed)              |
 |   [provenance + text + tables]                    |
 +-----------+---------------------------------------+
```

- **Transition quote** styled as block quote — indented, left rule,
  italics. This is literally a legal quote.
- **Versions labeled by regulation**, not "Current" / "Previous". The
  engineer needs to know *which* regulation.
- Current version open by default. Previous version collapsed with
  slightly muted container.

### Cross-edition transitions

For transitions between editions (OBC 1997 -> OBC 2006), the old
edition's provision is found via `ProvisionEditionMapping`. Same stacked
layout with edition labels on each version.

## Regulation Browsing View

Separate page, reached by clicking a regulation link in the provenance
header. Reference document layout — not search results.

```
 +-----------------------------------------------------+
 | O. REG. 22/98                                        |
 | Amending O. Reg. 403/97 (OBC 1997)                  |
 | Filed: 1998-01-27 | Effective: 1998-04-06            |
 |                                                      |
 |  1.(1) [revoke_and_substitute]                       |
 |    Target: Article 1.1.3.2.                          |
 |    > View provision                                  |
 |    v [gazette page image — collapsible]              |
 |                                                      |
 |  1.(2) [amend_strike_sub]                            |
 |    Target: Sentence 2.4.1.1.(1)                      |
 |    "institutional occupancies" ->                     |
 |    "care or detention occupancies"                    |
 |    > View provision                                  |
 |                                                      |
 |  ... (38 clauses)                                    |
 +-----------------------------------------------------+
```

- Regulation metadata as sticky header.
- **Clause number** as primary visual anchor, large monospace.
- **Action type** as color-coded pill/tag per action.
- Target provision as link.
- Gazette page images collapsible — engineers may want just the text
  list for navigation.

## Edition Regulation Chain View

Vertical timeline layout — the "completeness confidence" view.

```
 +-----------------------------------------------------+
 | OBC 1997 — REGULATION CHAIN                          |
 | [checkmark] All 20 amendments captured                |
 |                                                      |
 | O----  O. Reg. 403/97 (base)                         |
 | |      effective 1998-04-06                           |
 | |      > Browse provisions                            |
 | |                                                    |
 | O----  O. Reg. 22/98                                 |
 | |      effective 1998-04-06                           |
 | |      34 provisions affected  |  > Browse clauses    |
 | |                                                    |
 | O----  O. Reg. 102/98                                |
 | |      effective 1998-04-06                           |
 | |      2 provisions affected  |  > Browse clauses     |
 | |                                                    |
 | ...                                                  |
 | |                                                    |
 | X----  Revoked 2006-12-31 by O. Reg. 350/06          |
 +-----------------------------------------------------+
```

- **Completeness badge** at top: "20/20 amendments captured" with
  checkmark. This is the confidence builder.
- Timeline metaphor reinforces chronological completeness — any gap
  would be visually obvious.
- Base regulation at top, revocation at bottom.
- Each node: reg ID, effective date, provisions affected count, link
  to clause view.

### Appendix notes

Appendix provisions (`appendix_of` FK set) displayed as a collapsible
section below tables. Each note shows its text/image and a mini
provenance line if amended independently.

- Collapsed by default: "Appendix Notes (N)"
- `(See Note A-1.1.1.1.(2))` references in provision text become anchor
  links that expand the section and scroll to the specific note.
- When an appendix note is a direct search result, it shows standalone
  with the parent provision context visible (link + collapsed parent
  text above).

## Color Coding

### Base provision (v0, never amended)

- Provenance spine: teal
- Text: `text-neutral-500 dark:text-neutral-400`
- No amendment section — quiet default

### Amended provision

- Provenance spine: brick/terracotta (`border-l-2`)
- Text: `text-neutral-700 dark:text-neutral-300` (slightly more prominent)
- Signals "this provision has its own amendment story"

### Transition active

- Block quote: `bg-amber-50 dark:bg-amber-900/20 border-amber-300`
- Draws attention to the overlap

### Action type pills (regulation view)

- `revoke_and_substitute`: strong accent
- `amend_add`: muted positive
- `amend_strike_sub`: neutral
- `revoke`: muted danger

## Copy Button

Clipboard icon in provenance header. Copies:

```
OBC 1997, Div B, S 3.1.4.7. -- Fire Separations
In force: 1998-04-06 (O. Reg. 403/97)
Amended by: O. Reg. 22/98, cl. 1.(1) (1998-04-06)
Next amendment: O. Reg. 152/99 (1999-04-01)
```

Built in JavaScript from data attributes on the provenance header.

## Files

### New templates
- [ ] `templates/provenance/_provenance_header.html`
- [ ] `templates/provenance/_provision_content.html` (text + tables)
- [ ] `templates/provenance/_transition_view.html`
- [ ] `templates/regulation/detail.html` (clause browsing)
- [ ] `templates/regulation/chain.html` (edition regulation chain)

### Modified templates
- [ ] `templates/partials/search_results_partial.html` — use new
      provision view layout
- [ ] `templates/partials/_result_document_block.html` — show page
      images or HTML based on version

### CSS / Fonts
- [ ] Google Fonts: Literata (legal content), JetBrains Mono (references)
- [ ] Paper-like container styling for document images and HTML
- [ ] Provenance spine styling (teal base, brick amended)
- [ ] Action type pill colors

### JavaScript
- [ ] Copy button: build reference string from data attributes
- [ ] Amendment chain expand/collapse (Alpine.js)
- [ ] Transition accordion (Alpine.js)

## Verification

- Provision view: provenance header visible, text/table content shown
- Base provision: page image displayed, teal spine
- Amended provision: HTML text displayed, brick spine
- Revoked provision: previous version shown with "Revoked" banner
- Table (image form): scrollable image container with caption and notes
- Table (HTML form, e-Laws-sourced versions): sanitized `<table>`
  rendered inline; matches image-form container styling; notes
  suppressed when embedded in HTML
- "Next amendment" shown when applicable
- Transition: both versions visible with block quote header
- Regulation view: all clauses listed, action pills, links work
- Edition chain: timeline layout, completeness badge
- Copy button: correct formatted string
- Mobile: single-column layout works without modification
