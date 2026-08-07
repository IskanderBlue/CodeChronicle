# Review the export counts, and remove what nobody used

**Prefix:** `x-` — medium priority, but not yet possible. **Do this on or after 3 October 2026**
(sixty days after the exports shipped, 4 August 2026).

## Why this card exists

`tasks/complete/b-provision-exports.md` shipped four exports at once on
purpose. We did not know which one a code consultant reaches for, and asking
produces an opinion rather than a measurement. Four small exports cost less
than one wrong guess.

The measurement only pays if somebody reads it. This card is the promise to
read it.

## Where the numbers are

`/insights/` → **Exports**. One row per kind, with the window count and the
all-time count. The citation row breaks out its three formats, because a
factum and a report body take different strings and one of them may be
nobody's.

Set the window to 90 days so it covers the whole period.

## What to decide

| Reading | Decision |
|---|---|
| Nobody used it | Remove it. Do not defend it. |
| Used often | Give it the next round of work. |
| Used once per reader, never again | It was probably confusing. Ask that reader before removing it. |

The last row needs a name, not just a number. `EngagementEvent` carries the
user or the IP, so a kind whose count equals its distinct-reader count is the
one to look at.

## The four kinds

- `citation` — with `context.format` in `{legal, report, reference}`.
  `reference` is the incumbent: the structured provenance block the band's
  copy button produced before this work. It is measured like the other two
  and can lose.
- `provision_pdf` — one provision at one date, laid out to print.
- `results_csv` — a result set, for auditing a building against a date.
- `comparison_pdf` — two versions and the pairing, laid out to print.

## What removing one means

Each export is small and separate:

- A citation format is one entry in `core/citations.py` plus its row in
  `templates/partials/_citation_panel.html`.
- The printable provision is the `for_print` branch of
  `core.views.regulation.provision_permalink`, its route, and
  `templates/regulation/provision_print.html`.
- The CSV is `core.views.exports.results_csv`, its route, and the button in
  `templates/partials/search_results_partial.html`.
- The printable comparison is the `for_print` branch of
  `core.views.compare.compare_versions`, its route, and
  `templates/compare_print.html`.

`core/page_crops.py`, `core/print_options.py` and the
`templates/partials/_print_*.html` files are shared by the two printable pages.
Remove them only when both go.

One thing worth watching in the counts: `?tables=on` says a reader wanted the
extracted table beside the scan. If that is common, the scanned tables are hard
to read and the fix is the images, not the option.

## Related

- `tasks/complete/b-provision-exports.md` — the card that shipped them.
- `core/insights.py` — `export_counts`.
