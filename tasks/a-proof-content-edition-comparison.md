# Proof content: one provision across four editions

**Prefix:** `a-` — high priority, actionable now. The corpus and every surface
this article needs are already on production.

## Goal

Write one public article that shows what the Ontario Building Code said about
one subject in 1997, 2006, 2012 and 2024. The article is the artefact a code
consultant forwards to a colleague. It does two jobs at the same time:

1. It proves the product without a trial and without a demo call.
2. It ranks for the long-tail question the product answers, and no competitor
   answers well.

Do not write a second article until this one has run for 60 days. One good
article that gets forwarded beats six that do not.

## Why this shape

A screenshot of a search box proves nothing. A reader who works with the code
can check a provision's text against a source they trust. When the four texts
sit side by side and the amendment history explains each change, the reader
learns three things at once: the corpus is real, the dates are right, and
nobody else has this.

The 1997 edition carries the argument. Its text left e-Laws before the
consolidation era, so a reader cannot get it from a free source. Every other
part of the article is context for that one fact.

## Choose the provision

The provision must meet all of these conditions:

- It changed in a way a practitioner cares about, in at least two of the four
  editions. A provision with one change tells a thin story.
- It is inside the free tier (OBC 2006) for at least one edition, so every
  link in the article opens for a logged-out reader.
- Its 1997 text differs from its 2006 text. This is the whole point.
- It reads in under about 300 words per edition. A mega-table does not fit in
  an article.

Candidate subjects, in the order to check them:

- Fire separations and rated assemblies.
- Stair, ramp and handrail geometry.
- Sprinkler requirements for a residential occupancy.
- Barrier-free design (large, well-known changes over the period).
- Guard height.

Use the `/insights/` page to check whether visitors already search for one of
these. A subject people ask for beats a subject we like.

## Structure

1. **The question.** One paragraph. A permit was issued in 1999. Which text
   applies? Name the real cost of getting this wrong.
2. **The four texts.** One block per edition, each with its in-force dates and
   a link to the provision permalink. Use the product's own rendering.
3. **What changed, and which regulation changed it.** Cite the amending
   regulation for each change. This is the part no other source gives.
4. **How to check this yourself.** Link to the Sources page and the
   verification-rail guide. Invite the reader to disagree.
5. **One call to action.** Search your own date. Not "sign up".

## Rules for the text

- Every figure comes from the database. Do not write a number by hand.
- Do not claim e-Laws shows only today's text. See
  `project_landing_page_rules` in the memory notes.
- Use "provision", not "section", as the generic term.
- Show the 1997 page scan where one exists. A scan of the paper edition is
  evidence in a way reset text is not.

## Where it lives

A public page on the site, not a third-party blog. The links, the ranking and
the sitemap entry must all belong to us. Add the page to
`STATIC_PAGE_NAMES` in `core/sitemaps.py` when it ships.

## Done when

- The article is public and appears in `/sitemap-pages.xml`.
- Every provision link in the article opens for a logged-out reader, or opens
  the locked-edition teaser on purpose and the text says so.
- The article is sent to at least 20 people by direct email (see the outreach
  plan), not only published.

## Related

- `tasks/landing-page.md` — the copy rules this article must obey.
- `core/insights.py` — the query list that tells you which subject to pick.
