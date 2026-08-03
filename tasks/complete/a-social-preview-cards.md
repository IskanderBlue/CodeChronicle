# Social preview cards (Open Graph)

**Complete 2026-08-03. Confirmed on Slack. Nothing is outstanding.**

Every page carries `og:` and `twitter:` tags, the static card is drawn and
committed, and a locked page carries a generic card. A pasted link shows the
title, the description and the image in Slack, which is the proof no test can
give: Slack reads the page itself and renders from the tags alone.

A generated card per provision was considered and **rejected**. The image as
imagined would have shown the provision number, the heading and the in-force
window, and `og:title` already carries all three. The version that shows what
text cannot — a lineage strip, or the provision text itself — is parked in
`tasks/maybe/per-provision-social-card.md` with its trigger.

## What shipped

- `core/seo.py` holds `SITE_NAME`, `TITLE_SUFFIX`, `DEFAULT_TITLE`,
  `DEFAULT_DESCRIPTION` and the card's path. The `<title>`, the description,
  the canonical link and the card all read them, so a page cannot describe
  itself one way to a reader and another way to a crawler.
- `core.context_processors.page_metadata` exposes those, plus `site_origin`
  (scheme and host). The canonical link now reads `site_origin` too, instead
  of rebuilding the same string.
- `templates/partials/_social_meta.html` emits the tags. `base.html` includes
  it in a `social` block, so a page can suppress its card by overriding the
  block with nothing. No page does. A **locked** page carries a generic card
  instead: it names the edition, says the edition is Pro content, and names no
  provision. The first design emitted no card there, and a link with no card
  arrives as a bare URL and looks broken — the failure the card exists to
  prevent.
- `provision_page_meta` adds `social_title` (the title without the
  ` | CodeChronicle` tail) and `og_type: "article"`. Both derive from strings
  the function already built.
- The landing page and `pricing.html` lost their `{% block title %}`
  overrides. The landing page carries the site default, because that sentence
  *is* the site; the pricing view supplies its own pair.
- `manage.py make_social_card` draws `static/images/social-card.png` at
  **1200x600**, the one ratio every platform renders whole. Nothing on it is
  typed in: the wordmark is the app bar's (`Code` bold roman, `Chronicle`
  medium italic, `.ca` semibold, all ink, tracked -0.02em, in the vendored
  Source Serif 4), and the edition bands come from `CodeEdition`, the same
  rows the masthead's corpus span measures. **Re-run it after loading an
  edition.** Pillow is a dev dependency; the server never imports it.
- The bands use **edition** dates, not version dates. Five of the 2012
  edition's versions run to 2025-03-31 and three of the 2006 edition's to
  2016-01-01, and a tail of five must not set the width of a band standing
  for thousands.
- Each edition costs 46px in a frame that cannot grow, so the command
  **refuses to draw** a card that would overflow rather than write a clipped
  one. At four editions the staircase must become a single row of contiguous
  segments — the editions abut, so one row is faithful and its height is
  constant. `tasks/c-social-card-single-row.md` holds the design.
- `fonts/` holds the vendored faces, both OFL licences, and how they were
  made. They are build inputs; `collectstatic` never sees them.
- Eight tests in `core/tests/test_seo.py::TestSocialCard`, including the locked
  page naming no provision in any tag that makes a claim. Seven more in
  `core/tests/test_social_card.py` cover the drawing itself: the bands come
  from the edition rows, the file matches the size the tags declare, and seven
  editions raise rather than clip.

The search page keeps a short tab label, "Search | CodeChronicle", and carries
a longer sentence on its card. The two jobs differ: a tab is a label, and a
forwarded link is a claim. Each string is written once, in the view.

## Why this mattered

Before this, every link anybody sent — in email, in Slack, in Teams, on
LinkedIn, in a text message — arrived as a bare URL with no title, no
description and no image. A pasted link to a provision looked broken.

That costs more here than on most sites, because the plan is that people
**forward** these links: the proof article, the demo video chapters, a live
search result sent to a colleague. Every one of those is a link somebody
pastes somewhere.

## What the next person must not undo

- **Do not resolve the static URL at import time.** The manifest does not
  exist during CI `check` or the entrypoint `migrate`. Resolve at request
  time. See the memory note `project_static_url_import_time`.
- **`og:url` is the canonical URL**, not the current page, for the same reason
  the canonical tag is.
- **A locked page carries a generic card, not none and not the provision's.**
  A card that quotes the heading promises a text the page will not deliver. No
  card at all is worse: the link arrives as a bare URL and reads as broken.
- **Slack caches the image separately from the metadata**, keyed on the image
  URL. Because every page shares one card, a fresh page URL does not give the
  image a fresh key. Only a new image URL does, and the filename is
  content-hashed, so the image itself must change.
- **The server must send the card as `image/png`.** A `types` block inside an
  nginx `location` **replaces** the inherited mime map rather than extending
  it, and production served every `/static/` raster as
  `application/octet-stream`. No crawler draws that. The deployed config comes
  from `CodeChronicleTerraform/modules/compute/startup.sh`; the repo's
  `nginx/nginx.conf` is drift. See `project_prod_nginx_source_of_truth`.
- **Re-run `manage.py make_social_card` after loading an edition**, or the
  bands on the card lag the corpus the masthead reports.

## How it was verified

Paste a URL into a Slack message in a private channel. Slack shows what its
crawler actually read. Checked on the landing page, a provision permalink and
the pricing page.

**Read the sent message, not the compose box.** Slack draws a partial preview
while you type — text only, no image — and it looks exactly like a broken
card. Send the message before you judge the result.

One crawler is enough. Every platform reads the same tags off the same
templates, so a second inspector confirms the same thing a second time.

## Done

- ~~Every page carries `og:` and `twitter:` tags with values from
  `core/seo.py`.~~ Done.
- ~~A provision link pasted into Slack shows the provision number, the heading
  and the window.~~ Done. A sent message renders the full card, image
  included. `og:title` reads "1.1.1.1. Application — OBC 2006 (in force 31
  December 2006 to 1 January 2014)".
- ~~Locked pages carry a generic card that names no provision, with a test.~~
  Done (`test_a_locked_page_carries_a_generic_card`).
