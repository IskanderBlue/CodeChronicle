# Social preview cards (Open Graph)

**Prefix:** `a-` — high priority, actionable now. Half a day, and the whole
distribution plan depends on it.

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
- **Never emit a card for a locked page.** A forwarded link should not promise
  a provision and deliver an upsell.

## Verify

Paste a URL into the LinkedIn Post Inspector, and into a Slack message in a
private channel. Both show what their crawler actually read. Check three
shapes: the landing page, a provision permalink, and the pricing page.

## Done when

- Every page carries `og:` and `twitter:` tags with values from `core/seo.py`.
- A provision link pasted into Slack shows the provision number, the heading
  and the window.
- Locked pages carry no card, with a test.
