# JSON-LD structured data on provision pages

**Prefix:** `c-` — low priority, actionable now. Real value, but indirect.
Do the titles, descriptions and canonicals first; those are already done.

## What this is, and is not

It **adds** an invisible `<script type="application/ld+json">` block to the
page head. It changes nothing a reader sees. The provenance rail, the
amendment chain and the page images stay exactly as they are.

Google does **not** currently draw a rich result for the `Legislation` type.
This will not make our listing look different. It makes our pages easier to
understand, which is a slower and less certain benefit. Say so honestly when
judging whether it worked.

## Why it still earns a card

`schema.org/Legislation` exists because legal publishers have our exact
problem: many versions of one text, told apart only by date. Three properties
map onto the product's whole thesis:

- `legislationDateVersion` — which version of the text this page is.
- `legislationLegalForce` — `InForce` or `NotInForce`.
- `temporalCoverage` — the in-force window, as `start/end`.

`temporalCoverage` is the machine-readable form of the one thing we sell.
Nothing else on the page states it in a form a crawler can act on.

The second reason is answer engines. When somebody asks an assistant what the
OBC said about a subject in 1999, a page whose dates are structured is a
citable source; a page whose dates are only prose is a guess.

## The block

One per provision-version page. Values come from the same objects
`core/seo.py` already reads, so the metadata and the structured data cannot
disagree.

```json
{
  "@context": "https://schema.org",
  "@type": "Legislation",
  "name": "Fire Department Access Routes",
  "legislationIdentifier": "3.2.5.7.",
  "legislationJurisdiction": "https://www.wikidata.org/wiki/Q1904",
  "legislationDate": "2006-12-31",
  "legislationDateVersion": "2006-12-31",
  "legislationLegalForce": "NotInForce",
  "temporalCoverage": "2006-12-31/2009-01-01",
  "isPartOf": { "@type": "Legislation", "name": "Ontario Building Code 2006" },
  "isBasedOn": { "@type": "Legislation", "name": "O. Reg. 350/06" },
  "url": "https://www.codechronicle.ca/provision/OBC_2006/B/3.2.5.7./v2/"
}
```

## Rules

- **Build it in `core/seo.py`**, beside `provision_page_meta`, and serialize
  with `json.dumps`. Never assemble JSON in a template: one unescaped
  apostrophe in a provision heading breaks the block silently.
- **`url` is the canonical URL**, not the current page. Two version pages of
  one provision must name the same subject.
- **`legislationLegalForce` is computed, never assumed.** A version with no
  `ineffective_date` in a superseded edition is *not* in force. Getting this
  backwards tells the world a 2006 text is current, which is the worst error
  this product can make.
- **`temporalCoverage` omits the end when the window is open**, using the
  `2012-01-01/..` form. Do not write today's date as the end.
- **Never emit the block for a locked edition's page.** The teaser page is
  not the provision.

## Verify

- Google's Rich Results Test and the Schema.org validator both accept a
  pasted URL. Run one page of each shape: a mid-chain version, a final
  version, and a division-less OBC 1997 provision.
- A test asserting the block parses as JSON and that
  `legislationLegalForce` is `NotInForce` for a superseded edition.

## Done when

- Every free-tier provision-version page carries a valid block.
- Both validators pass on the three page shapes.
- Locked pages carry no block, with a test.

## Related

- `core/seo.py` — same source objects; extend, do not duplicate.
- `tasks/a-search-console-registration.md` — where you watch for the effect.
