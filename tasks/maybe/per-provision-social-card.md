# A generated social card per provision

**In `maybe/`: the case for this is not made.** Decided 2026-08-03, when
`a-social-preview-cards.md` closed. Do not pick this up because it is written
down. Pick it up only if the trigger below happens.

## Why it is not worth doing as first imagined

The first version of this idea was a card showing the provision number, the
heading and the in-force window. Every one of those three facts is already in
the unfurl, because `core/seo.py` puts them in `og:title` and
`og:description`:

```
og:title  1.1.1.1. Application — OBC 2006 (in force 31 December 2006 to
          1 January 2014)
```

So the picture restates the sentence above it. That is not persuasion. The
shared site card costs nothing and does the branding job better, because one
recognisable image beats a thousand near-identical ones.

## The only version worth building

The image must show what text cannot. Two candidates, either alone:

- **A lineage strip.** The provision's versions as segments across a date
  axis, with the shared version marked. "This text changed four times and you
  are looking at the second" reads in one glance, and no `og:title` can say
  it. The drawing is close to the edition bands the site card already draws.
- **The provision text itself**, set in the code's own typography. A picture
  of the thing is proof. A description of the thing is a claim.

## The trigger

Somebody forwards these links often enough that the identical picture is a
visible problem, or a specific campaign needs the lineage to land without a
click. Neither is true today.

## What it would cost

- **Pillow on the server.** It is a dev dependency today and the server never
  imports it. A render endpoint puts image drawing in every gunicorn worker on
  the e2-micro.
- **A public unauthenticated endpoint**, therefore a cache and a limit.
  Without both, anyone can request thousands of URLs and it is a CPU tap.
- **A second copy of the gating rule.** `core/views/regulation.py` owns
  "locked, so serve the generic card". A second caller is a second place to
  get it wrong.
- **A drawing refactor.** `core/management/commands/make_social_card.py` owns
  the palette, the vendored faces and the fitting helpers. Two card drawings
  will not stay in step, so lift the primitives out and let both callers share
  them.

## The cheaper shape

**Pre-generate the free-tier cards during `load_edition`**, into `static/`.
This keeps Pillow off the server and needs no endpoint, at the price of a few
thousand hashed files in the manifest. Free-tier scope is OBC 2006 only, so
the set is bounded. Prefer this to a render endpoint if the trigger ever
fires.

## Watch out for

- **`load_edition` replaces every provision and version pk on reload.** Key
  anything cached on the URL parts, never on a pk.
- **The provision heading is not the page's promise.** A locked provision
  keeps the generic edition card, for the reason the locked-page rule gives.
