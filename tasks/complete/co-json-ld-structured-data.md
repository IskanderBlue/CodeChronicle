# JSON-LD structured data on provision and regulation pages

**Status: DONE, 2026-08-08.** The validators ran, found three defects, and all
three are fixed, deployed and confirmed on production. See **What the
validators found** for each one, and **What is left** for the post-deploy
check that closed the card.

It was `po-` first, gated on a push to prod, because the remaining work runs
an external validator against deployed URLs and a validator cannot read a
working tree. That gate lifted on 2026-08-07, when both page kinds began
emitting the block on production. It then ran as `co-`, low-priority ops, for
one day.

**One judgement is archived unanswered**, at the end of **What is left**: the
regulation node's `url` names a pk that `load_edition` changes on every
reload, so a crawler can hold a link a later reload breaks. The page's own
subject survives, because the block's `url` is the canonical provision URL,
and `sameAs` already carries the durable ontario.ca link. So this is a quality
question about one nested node and not a defect in what shipped.

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

The block names the base regulation and stops there. It does **not** name the
amending regulations that produced the version. That is a limit of the
vocabulary, not of the data — see **What the validators found**.

`sameAs` comes from `Regulation.source_url`, which CCM ships. On the loaded
corpus that is the `r06350` form rather than the `060350` form above. Both
resolve; CCM is the source of truth and the block must not rewrite it.

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
- **Name the base regulation with `legislationConsolidates`, and nothing
  else.** Not `isBasedOn`: that is a generic `CreativeWork` property with no
  legal meaning. `legislationConsolidates` is an **edition-level** fact, so it
  survives the base-enactment data gap and is present even on a v0 with no
  contributing clause. Never substitute one instrument for another when the
  data is missing. A guessed citation is a false one.
- **Do not try to name the amending regulations here.** schema.org defines no
  inverse of `legislationChanges`, and the block carried an invented
  `legislationChangedBy` until 2026-08-08. The reasoning is in **What the
  validators found**; read it before you reach for `@reverse`.
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
- **`legislationChanges` is the only place the product states the amendment
  edge to a machine.** The instrument names what it changes, from
  `Regulation.amends`. Absent on a base regulation, which amends nothing.
  There is no inverse in the vocabulary, so the provision page cannot carry
  this fact and this page must.

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
  `TestRegulationJsonLd`. Both halves of the force rule are
  asserted, because free scope today holds one superseded edition, so an
  inverted computation would still pass on every page a crawler sees.
- `core/models.py` — `Regulation.citation`, added 2026-08-08. The "O. Reg."
  prefix is what makes the number a citation, so it belongs to the model and
  not to each surface that prints one. It is also the one place to widen when
  a second jurisdiction lands.

## What the validators found

Run on 2026-08-08 against production, with the **Schema Markup Validator**
(`validator.schema.org`) as the gate. The validator has a JSON endpoint that
takes either a `url` or an `html` parameter, which is how the candidate fixes
below were tested before any of them shipped. It rate-limits hard; leave 20
seconds between calls.

The **Rich Results Test** reports "No items detected" for `Legislation`,
because Google draws no rich result for the type. That is the expected answer
and not a failure. Do not unpick working code over it.

**Four page shapes, not five.** A validator fetches anonymously, so it sees
what an anonymous reader sees. OBC 1997 is outside `FREE_TIER_CODE_NAMES`, so
a 1997 provision answers **403** with no block — which is the "never emit for
a locked page" rule working, and is the reason the division-less shape cannot
be validated from outside while 1997 stays gated. Validate it by rendering the
block in a shell as a Pro user, or wait until the free scope changes.

| Page | Result |
|---|---|
| Provision, mid-chain version | 1 error |
| Provision, final version | 1 error |
| Provision, v0 with no amender | clean |
| Base regulation | clean |
| Amending regulation | clean |

### Defect 1 — `legislationChangedBy` is not a schema.org property

`INVALID_PREDICATE`, on exactly the two pages that carried it.
`schemaorg-current-https.jsonld` confirms it: ELI's `changed_by` was never
adopted. **Every** change relation schema.org defines — `legislationChanges`,
`legislationAmends`, `legislationCorrects`, `legislationRepeals`,
`legislationConsolidates` — runs from the *instrument* to the text it acts on.
The vocabulary has a direction, and an instrument is always the actor.

So the edge cannot be stated from a provision. Three ways to state it anyway
were tested, and each was rejected for a reason worth keeping:

- **`@reverse` with `legislationChanges`** validates clean, and re-roots the
  graph: the amending regulation becomes the root node and the provision, with
  its `temporalCoverage`, becomes a nested target. A provision page whose root
  node is a different document has given away the one thing it exists to
  state.
- **A two-root `@graph`** was the next candidate. It was not settled, because
  the validator began refusing the client. Any triple whose object is the
  provision makes the provision an object, so it likely re-roots the same way.
  If you pick this card up, that is the open question.
- **A vaguer property** such as `citation` is not wrong, but it does not say
  the regulation *produced* this text, so it buys a triple and spends the
  meaning.

**Fixed by dropping the property.** The block now names the base regulation
and stops. Nothing is lost that the site does not say elsewhere: each amending
regulation's own page carries `legislationChanges`, and the provision page
still lists the chain in its markup. What is dropped is a triple no consumer
could read.

### Defect 2 — the citation was the bare number

`legislationIdentifier` read `350/06`, and the provision's read `Article
1.4.1.2. of Division A of 350/06`. Neither is a citation, which is the one
rule this property has. The validator does not catch it — it checks the shape,
not the sense — so it was found by reading the deployed block against this
card.

The suite could not catch it either, and that is the part to remember: the
fixture stored `reg_id="O. Reg. 350/06"`, so the assertion compared the block
against a fixture that had already done the block's job. CCM ships the bare
number. **A fixture richer than the payload asserts nothing.**

**Fixed** by `Regulation.citation`, one computed property on the model — no
column, no migration — used by `__str__` and by both blocks. `__str__` cannot
serve as the citation itself, because it appends the role: `O. Reg. 350/06
(amendment)` reads correctly in an admin list and corrupts an exhibit. The
fixture now holds the bare number CCM ships.

### Defect 3 — the loader deleted the code's display name

Found by the same reading. `isPartOf.name` says `OBC 2006` where it means
`Ontario Building Code 2006`, because `Code.display_name` is empty for the one
code the product serves.

The cause was in `load_edition`, which wrote `data.get("display_name", "")`
into the `Code` row on every reload. CCM ships no such key, so that was not a
default but an overwrite, spent on a row seeded elsewhere. Every code we do
**not** serve kept its name, because nothing reloads them. `is_national` had
the identical defect, and would have silently un-flagged a national code.

**Fixed** two ways. The loader now sets only what the payload carries — the
rule the next lines of that function already stated for `first_edition_date`.
And `config/code_metadata.py` now owns the names as `DISPLAY_NAMES`, which the
loader applies, so the value has a home in version control rather than in
whatever seeded the row last. The names are a presentation choice, not a
mapping result, which is why they are not asked of CCM: CCM writes one file
per edition, and a code-system fact would repeat in every one of them.

## What is left — nothing. The smoke check passed on 2026-08-08.

The three fixes deployed on 2026-08-08 (workflow run `31250653510`), and the
block a provision page serves now reads:

| | |
|---|---|
| `legislationChangedBy` | **absent** — Defect 1 fixed |
| `legislationIdentifier` | `Article 1.4.1.2. of Division A of O. Reg. 350/06` — Defect 2 fixed |
| `isPartOf.name` | `Ontario Building Code 2006` — Defect 3 fixed |
| `legislationConsolidates` | `O. Reg. 350/06` |
| `temporalCoverage` | absent, and correctly so — v6 is `NotInForce` and governed no day |

The block shape had already validated through the `html` parameter with zero
errors, so this confirmed the deploy and not the design.

**Defect 3 needed no edition reload.** `get_code_display_name` reads the
`DISPLAY_NAMES` map when the stored row is empty, and prod's row is empty, so
the deploy alone changed the page titles from "OBC 2006" to "Ontario Building
Code 2006". A later reload only makes the stored row agree with what the pages
already show. This was expected to wait for the reload; it did not.

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
- `config/code_metadata.py` — `DISPLAY_NAMES`, and the two readers of it.
