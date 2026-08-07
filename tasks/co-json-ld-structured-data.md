# JSON-LD structured data on provision and regulation pages

**Prefix:** `co-` — low priority ops. The card was `po-`, gated on a push to
prod, because the remaining work runs an external validator against deployed
URLs and a validator cannot read a working tree. **The gate lifted on
2026-08-07:** both page kinds now emit the block on production.

**Status:** the code is built and tested, for both page kinds. Running the
external validators is the remaining step. See **What is left** at the end.

## What this is, and is not

It **adds** an invisible `<script type="application/ld+json">` block to the
page head. It changes nothing a reader sees. The provenance rail, the
amendment chain and the page images stay exactly as they are.

Google does **not** currently draw a rich result for the `Legislation` type.
This does not make our listing look different. It makes our pages easier to
understand, which is a slower and less certain benefit. Say so honestly when
you judge whether it worked.

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

## Two page kinds, and which one carries the value

A regulation **is** a piece of legislation, so the type describes a regulation
page more exactly than it describes a provision page. The provision page
carries the value all the same:

- There are about three thousand provision URLs and thirty-eight regulation
  URLs. The provision pages are the pages that rank, and the pages readers
  paste to each other.
- A regulation has one date. A provision has a **window**, and the window is
  the product. `temporalCoverage` says nothing new about a regulation.

So the provision block came first. The regulation block is a small
correctness companion: a provision's block names its base regulation in
`legislationConsolidates` and links to `/regulation/<pk>/`, and the object it
names must describe itself when a crawler follows the link. Do not expect the
regulation block to move anything on its own.

## The provision block

One per provision-version page. Values come from the same objects
`core/seo.py` already reads, so the metadata and the structured data cannot
disagree.

```json
{
  "@context": "https://schema.org",
  "@type": "Legislation",
  "name": "Fire Department Access Routes",
  "legislationIdentifier": "Article 3.2.5.7. of Division B of O. Reg. 350/06",
  "legislationJurisdiction": "https://www.wikidata.org/wiki/Q1904",
  "legislationDate": "2006-08-18",
  "legislationDateVersion": "2006-12-31",
  "legislationLegalForce": "NotInForce",
  "temporalCoverage": "2006-12-31/2008-12-31",
  "inLanguage": "en",
  "isPartOf": {
    "@type": "Legislation",
    "name": "Ontario Building Code 2006",
    "url": "https://www.codechronicle.ca/edition/3/chain/"
  },
  "legislationConsolidates": {
    "@type": "Legislation",
    "name": "O. Reg. 350/06",
    "legislationIdentifier": "O. Reg. 350/06",
    "url": "https://www.codechronicle.ca/regulation/17/",
    "sameAs": "https://www.ontario.ca/laws/regulation/060350"
  },
  "url": "https://www.codechronicle.ca/provision/OBC_2006/B/3.2.5.7./v2/"
}
```

A version that an amending regulation produced also carries
`legislationChangedBy`, as a list of the same node shape.

## The regulation block

One per regulation detail page.

```json
{
  "@context": "https://schema.org",
  "@type": "Legislation",
  "name": "O. Reg. 315/08",
  "legislationIdentifier": "O. Reg. 315/08",
  "url": "https://www.codechronicle.ca/regulation/24/",
  "legislationJurisdiction": "https://www.wikidata.org/wiki/Q1904",
  "legislationType": "Regulation",
  "legislationDate": "2008-09-10",
  "inLanguage": "en",
  "isPartOf": {
    "@type": "Legislation",
    "name": "Ontario Building Code 2006",
    "url": "https://www.codechronicle.ca/edition/3/chain/"
  },
  "legislationChanges": {
    "@type": "Legislation",
    "name": "O. Reg. 350/06",
    "legislationIdentifier": "O. Reg. 350/06",
    "url": "https://www.codechronicle.ca/regulation/17/",
    "sameAs": "https://www.ontario.ca/laws/regulation/060350"
  }
}
```

## Rules

### Both blocks

- **Build them in `core/seo.py`**, beside `provision_page_meta`, and serialize
  with `json.dumps`. Never assemble JSON in a template: one apostrophe in a
  provision heading breaks the block silently.
- **One serializer, one node builder.** `_serialize` and `_regulation_node`
  serve both blocks. Two serializers eventually differ on the escaping, and
  the escaping is the part that fails silently. Two node builders let the two
  blocks name one regulation two ways, and they link to each other.
- **Escape `<`, `>` and `&` after `json.dumps`.** `json.dumps` does not
  escape them. A heading that contains a closing script tag ends the block
  early and drops the rest of the head into the body. Django's `json_script`
  makes these three substitutions; it hard-codes `type="application/json"`,
  so copy the substitutions and not the helper.
- **`legislationDate` is when the instrument was adopted.** Read
  `Regulation.filed_date`, then `Regulation.effective_date`. Omit the
  property when neither is loaded.
- **Omit a value you cannot source.** A missing property costs less than a
  wrong one, because a machine repeats a wrong one with confidence.
- **Never emit a block for a locked edition's page.** This needs no tier
  test. Both locked paths render `locked_edition.html` with status 403, and
  `base.html` prints the block only where the view sets `jsonld`.

### The provision block

- **`url` is the canonical URL**, not the current page. Two version pages of
  one provision must name the same subject.
- **`legislationLegalForce` is computed, never assumed.** Read
  `CodeEdition.ineffective_date` as well as the version's. A few provisions
  outlive their edition and carry no end date of their own, so the version
  alone reports a 2006 text as open-ended. Take the **earlier** of the two
  ends. To get this backwards tells the world a 2006 text is current, which
  is the worst error this product can make.
- **`temporalCoverage` ends the day BEFORE `ineffective_date`.** The stored
  window is half-open (`effective <= d < ineffective`); an ISO 8601 interval
  includes both ends. To copy `ineffective_date` across claims the text
  applied on the first day it did not.
- **`temporalCoverage` omits the end when the window is open**, with the
  `2012-01-01/..` form. Do not write today's date as the end.
- **A version that never governed a day carries no `temporalCoverage`.** An
  interval is the wrong shape for an empty window.
- **`legislationDate` and `legislationDateVersion` are different dates.**
  `legislationDate` belongs to the regulation. `legislationDateVersion` is
  when this version began. To collapse the two back-dates every amendment to
  the edition.
- **Use two relations, not `isBasedOn`.** `isBasedOn` is a generic
  `CreativeWork` property with no legal meaning, and it cannot tell apart the
  two instruments behind a consolidated text:
  - `legislationConsolidates` — the edition's base regulation. This is an
    **edition-level** fact, so it survives the base-enactment data gap and is
    present even on a v0 with no contributing clause.
  - `legislationChangedBy` — the amending regulations that produced *this*
    version, from `contributing_clauses`. Absent on a v0, because nothing
    changed it.
  Never fall back from one to the other. A guessed citation is a false one.
- **`legislationIdentifier` is a citation that stands alone.** The bare
  provision number names a provision in three editions and in more than one
  division. Qualify it by level, division and instrument.

### The regulation block

- **Emit no `temporalCoverage` and no `legislationLegalForce`.** Both belong
  to a provision version. An amendment is not superseded the way a text is —
  the change it made stays made. To state a currency here invents a fact the
  data does not hold.
- **`legislationType` is `"Regulation"`, not `Regulation.role`.** schema.org
  means the kind of instrument: act, regulation, directive. Base and
  amendment are our word for the part a row plays in an edition, and both
  rows are regulations.
- **`legislationChanges` mirrors the provision block's
  `legislationChangedBy`.** There the version names what changed it; here the
  instrument names what it changes, from `Regulation.amends`. Absent on a
  base regulation, which amends nothing.

## What shipped

- `core/seo.py` — `provision_jsonld` and `regulation_jsonld`, over the shared
  `_serialize`, `_regulation_node` and `_edition_node`. Plus
  `effective_window`, `legal_force` and `temporal_coverage` as named helpers,
  and `site_origin` (which `core/context_processors.py` now shares).
- `templates/base.html` — one guarded `{% if jsonld %}` block in the head.
  Any page that sets `jsonld` gets a block; every other page gets none.
- `core/views/regulation.py` — `provision_permalink` and `regulation_detail`
  each set `jsonld`.
- `core/tests/test_seo.py` — `TestProvisionJsonLd`, `TestJsonLdOnThePage` and
  `TestRegulationJsonLd`, 26 tests. Both halves of the force rule are
  asserted, because free scope today holds one superseded edition, so an
  inverted computation would still pass on every page a crawler sees.

## What is left

Run the validators against the deployed pages:

- Use the **Schema Markup Validator** (`validator.schema.org`) as the gate.
  It validates any type.
- The **Rich Results Test** reports "No items detected" for `Legislation`,
  because Google draws no rich result for the type. That is the expected
  answer and not a failure. Do not unpick working code over it.
- Run one page of each shape: a mid-chain provision version, a final version,
  a division-less OBC 1997 provision, a base regulation, and an amending
  regulation.

> ⚠️ **Do not copy a `/regulation/<pk>/` URL out of this card.** `load_edition`
> replaces every regulation pk on each reload. The examples above were written
> when O. Reg. 350/06 was pk 17; after the reload on 2026-08-07 it is pk 351.
> Read the current pk from the site or the database before you validate.
>
> This is worth more than a note about stale examples. The block's
> `legislationConsolidates.url` names a pk URL, so a crawler that indexes it
> holds a link that a later reload breaks. The block's own `url` is the
> canonical **provision** URL, which is stable, so the subject of the page
> survives. Judge whether the regulation node should name a stable identifier
> instead — `sameAs` already carries the durable ontario.ca link.

## Related

- `core/seo.py` — same source objects; extend, do not duplicate.
- `tasks/ao-search-console-registration.md` — where you watch for the effect.
