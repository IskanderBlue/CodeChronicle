# Social preview cards (Open Graph)

**Prefix:** `a-` — high priority. The code is done and a real crawler confirms
it.

**Status 2026-08-02: shipped and confirmed on Slack.** Every page carries
`og:` and `twitter:` tags, the static card is drawn and committed, and a locked
page carries no card. A pasted link now shows a caption in Slack, which is the
proof no test can give: Slack reads the page itself and renders from the tags
alone. The LinkedIn Post Inspector is the one surface still unchecked, and it
reads the same tags. The generated per-provision image (option 2 under "The
image") is still open and is its own piece of work.

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
- `manage.py make_social_card` draws `static/images/social-card.png` from
  `CorpusCurrency`, so the coverage span on the card is the corpus's own
  figure. Re-run it after loading an edition. Pillow is a dev dependency; the
  server never imports it.
- Six tests in `core/tests/test_seo.py::TestSocialCard`, including the locked
  page carrying no `og:` or `twitter:` string at all.

The search page keeps a short tab label, "Search | CodeChronicle", and carries
a longer sentence on its card. The two jobs differ: a tab is a label, and a
forwarded link is a claim. Each string is written once, in the view.

## The gap

`templates/base.html` carries **no** Open Graph or Twitter Card tags. Verified
2026-08-01: zero `og:` properties anywhere in the templates.

So every link anybody sends — in email, in Slack, in Teams, on LinkedIn, in a
text message — appears as a bare URL with no title, no description and no
image. A pasted link to a provision looks like a broken link.

This matters more here than on most sites, because the plan is that people
**forward** these links: the proof article, the demo video chapters, a live
search result sent to a colleague. Every one of those is a link somebody
pastes somewhere, and right now every one of them lands badly.

## What to add

To `base.html`, beside the `meta_description` and `canonical` blocks that are
already there, and overridable per page the same way:

```
og:type          article (provision pages) / website (everything else)
og:title         the page title, without the " | CodeChronicle" tail
og:description   the same string as meta_description — one source, not two
og:url           the canonical URL
og:site_name     CodeChronicle
og:image         see below
twitter:card     summary_large_image
```

Reuse the values `core/seo.py` already computes. Do not build a second title
and a second description: two strings that mean the same thing will disagree
within a month.

## The image

Two options. Do the first, and treat the second as a later improvement.

1. **One static card**, 1200 x 630, in `static/`. The nameplate, the tagline,
   and the coverage span. Good enough, and it ships today.
2. **A generated card per provision** showing the provision number, the
   heading and the in-force window. Much stronger — a forwarded link that
   already shows "3.2.5.7., in force 2006 to 2009" does the persuading before
   the click. Needs a rendering endpoint, so it is its own piece of work.

## Watch out for

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

## Verify

Paste a URL into the LinkedIn Post Inspector, and into a Slack message in a
private channel. Both show what their crawler actually read. Check three
shapes: the landing page, a provision permalink, and the pricing page.

Slack: done. A sent message shows the title, the description and the card
image.

**Read the sent message, not the compose box.** Slack draws a partial preview
while you type — text only, no image — and it looks exactly like a broken
card. Send the message before you judge the result.

## Done when

- ~~Every page carries `og:` and `twitter:` tags with values from
  `core/seo.py`.~~ Done.
- ~~A provision link pasted into Slack shows the provision number, the heading
  and the window.~~ Done. A sent message renders the full card, image
  included. `og:title` reads "1.1.1.1. Application — OBC 2006 (in force 31
  December 2006 to 1 January 2014)".
- ~~Locked pages carry a generic card that names no provision, with a test.~~
  Done (`test_a_locked_page_carries_a_generic_card`).
