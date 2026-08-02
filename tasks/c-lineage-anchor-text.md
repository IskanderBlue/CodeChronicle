# Lineage anchor text: the title, not the version number

**Prefix:** `c-` — low priority, actionable now. Small, and it improves the
page for a reader as much as for a crawler.

## The rule

A link's text is a claim about **what the target page is about**.

- **In the link:** provision id and title. `3.2.5.7. Fire Department Access
  Routes`.
- **Beside the link, as plain text:** the version, the in-force window, the
  amending regulation.

## Why

- **A version number means nothing.** "v2" is an internal ordinal. It tells a
  reader nothing and tells a search engine nothing.
- **Dates do not belong inside the anchor.** A date range says *when the text
  applied*, which is a property of the version, not of the subject. Putting it
  in the anchor dilutes the subject words the page should rank for.
- **A reader scanning a rail reads the link text first.** A column of "v0 v1
  v2 v3" forces them to open pages to find out what they are.

## The exception

When one provision appears several times in one list — an amendment chain rail
is exactly this — the dates are what tell the rows apart. Keep them, still as
adjacent text, not inside the anchor. A row then reads:

> **3.2.5.7. Fire Department Access Routes** — v2, in force 1 Jan 2012 to 1 Jan 2014

The link is the same on every row; the distinguishing text sits outside it.
That is correct: the rows *are* the same subject, which is the fact the anchor
should state.

## Where to change it

Audit every place that links to a provision version:

- `templates/partials/_lineage_link_row.html`
- `templates/partials/_provenance_rail.html`
- `templates/partials/_viewer_edition_nav.html`
- `templates/regulation/_permalink_nav_item.html`
- `templates/regulation/chain.html`
- The lineage nav built in `core/views/search.py` (`_lineage_nav_direction`
  already carries `title`, so the data is there)

Some of these already show the title. Check each; do not assume.

## Watch out for

- **A version with no title.** Fall back to the provision id alone. Never
  render an empty anchor.
- **Space.** The rail is narrow (`--ws-rail`, 19rem). A long heading must
  truncate with an ellipsis and keep the full text in a `title` attribute, not
  wrap to four lines.
- **Do not measure the rail and hard-code a width.** Read the token. See the
  memory note `project_working_measure_tokens`.

## Done when

- Every provision-version link names the provision, not the version.
- The version, dates and regulation are still visible, outside the anchor.
- The untitled-version fallback has a test.
- The rail still renders at its narrowest width without wrapping.
