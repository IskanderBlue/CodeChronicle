# Missing e-Laws inline assets (broken images on live pages)

**Prefix:** `a-` — high priority, actionable now.

**Status 2026-08-02: the images are fixed for readers.** CCM commit `526a5ec0`
fetched the missing bytes. This repository now reads the version-scoped
manifest, and the 130 new assets are published. Of the 141 paths the stored
HTML names, **140 return 200** against `https://www.codechronicle.ca/`.

One item is open, and it is content rather than images: the two provisions that
carry the ontario.ca footer still carry it, because production holds the old
text. A production reload replaces it. See "Open" below.

The producer work was in **CodeChronicleMapping**. Nothing in CodeChronicle
could fix it before, because the bytes did not exist in any CCM output. They
do now.

## The gap (the state before the fix)

Stored version HTML referenced 141 distinct asset paths. **115 of them returned
404**, measured 2026-08-02 against `https://www.codechronicle.ca/` after the R2
asset publish. The other 26 served correctly, so this was not a hosting fault.

The published bucket was complete: every one of the 532 keys that the structured
fields name (`page_images`, `tables[].images`, `RegulationAsset.path`) returned
200. The 115 misses were references that live **only inside the HTML body**, and
`RegulationAsset` never registered them. That is why the manifest reported no
mismatch: the manifest did not know about them.

**CCM measured the same gap against its own build** and reports 130 misses (26
in OBC 2006, 104 in OBC 2012, 0 in OBC 1997). The count is higher than 115
because it counts what the build emits, not what this database holds.

The manifest hole is larger than the 404s. CCM's `regulations[].assets[]`
declared 45 entries while the same three editions named 157 images in their
HTML. So most of the 26 references that *did* serve were also unregistered.
They worked by luck: the current-consolidation mirror happened to hold them.

## Why the paths differ

CCM downloaded the assets of the **current** consolidation. The stored HTML
comes from the **versioned** e-Laws pages, and e-Laws names the asset directory
differently on those pages:

| Where | Directory |
|---|---|
| CCM has | `laws/images/en/R12332_e_files/image001.gif` |
| The HTML asks for | `laws/images/en/120332_eV005_files/image001.gif` |

The file name matches. The directory does not. So the bytes for the versioned
pages were never fetched.

The shape of the 115 misses:

| Count | Shape |
|---|---|
| 89 | `laws/images/en/<version-dir>/<file>` |
| 25 | `laws/images/en/<file>` |
| 1 | `laws/assets/scripts/ontario-header.js` |

**Correction: the first two rows are one phenomenon, not two.** e-Laws names an
asset per consolidation version in both editions. OBC 2012 puts the version in
the *directory* (`120332_eV020_files/image001.gif`). OBC 2006 puts the version
in the *filename* (`elaws_regs_060350_ev003-14.gif`) and uses a flat directory.
The same figure has a different path in every version.

That is why CCM keys the new manifest to the **provision version** rather than
to the regulation. A regulation-scoped list can hold the paths, but it cannot
say which version needs which.

The last row is an e-Laws page script. It is not content. CCM no longer emits
it; see "The second cause" below.

## Reader impact (the state before the fix)

| Edition | Versions with an inline image | Versions with a broken one |
|---|---|---|
| OBC 1997 | 2 | 0 |
| OBC 2006 | 17 | **17** |
| OBC 2012 | 47 | 44 |

All 17 OBC 2006 versions are free-tier, so an anonymous reader saw them. One
example: `/provision/OBC_2006/C/1.4.1.1./v0/` showed three broken images. All
61 render now.

## The second cause — ontario.ca chrome inside a provision

The script reference was one symptom of a larger defect. CCM's body scan for
the **last** provision of a document found no following heading, so it ran to
the end of the file and absorbed the site chrome that trails the regulation.

Two provisions carried it, and this repository stored and served both:
OBC 2012 `4.4.1.1./C` and OBC 2006 `4.3.1.1./C`.

The chrome block is about 2.5 KB. OBC 2012 `4.4.1.1./C` measured 3090 bytes
before the fix and 540 bytes after it. OBC 2006 `4.3.1.1./C` now measures 292
bytes, and its whole text is one sentence: "(1) This Regulation comes into
force on December 31, 2006."

The removed content is the ontario.ca footer, the Accessibility / Privacy /
Contact / Terms links, the King's Printer copyright, a French-language switch
that links to `/lois/reglement/r12332`, a back-to-top button with its MUI SVG
icons, the `ontario-header.js` tag, and an unbalanced `</body></html>`.

A reader therefore saw another site's footer inside a Building Code provision,
with outbound links, on a page this application rendered. CCM now bounds the
scan at the regulation content root. **A reload replaces this text**, so expect
a content diff on these two provisions.

## What to do

### Done in CCM (commit `526a5ec0`)

1. ~~Fetch the assets of each **versioned** e-Laws page.~~ Done. CCM derives
   the fetch set from the HTML each version ships, then fetches what the local
   mirror lacks (`mirror-images --from-edition <edition.json>`). It keeps every
   path verbatim. The mirror grew from 96 files to 226. All three editions now
   report 0 missing references.
2. ~~Drop the `laws/assets/scripts/` reference during extraction.~~ Done, by
   fixing the content boundary rather than by filtering the tag. See "The
   second cause" above.
3. **Producer half of the manifest.** Done. CCM emits
   `provisions[].versions[].assets[]` — 186 entries across the three editions,
   against 45 before. Each entry carries `path`, `original_url`, `sha256`,
   `bytes` and `content_type`: the same five keys as
   `regulations[].assets[]`, so one loader reads both.

   CCM derives the array from the emitted HTML at its write boundary, and
   refuses to write an edition that names bytes nobody mirrored. An asset the
   HTML names therefore cannot be absent from the manifest.

   Spec: `CodeChronicleMapping/docs/cc-provenance-contract.md`, section
   "`provisions[].versions[].assets[]`".

### Done in this repository (2026-08-02)

4. ~~Read the new manifest in `load_edition.py`.~~ Done. A new model
   `ProvisionVersionAsset` stores `provisions[].versions[].assets[]`
   (migration `0049`). Both asset models now share the abstract
   `AssetManifestEntry`, because the contract gives the two scopes the same
   five keys and one loader reads both (`_asset_fields`).

   `sync_images` builds its verification manifest from **both** scopes. That
   is the point of the model: the regulation scope describes the source
   filings, so a body-only reference was checked by nothing. The three
   editions register 186 version assets against 45 filing assets.
5. ~~Reload the editions, then run `manage.py sync_images --backend r2`.~~
   Done. 142 objects copied, 933 skipped, 185 verified, 0 mismatched, 0
   registered-and-absent.
6. ~~Re-run the check with `.tmp/verify_html_refs.py`.~~ Done: 140 of 141
   paths return 200, against 26 before.

### Open

7. **Reload the editions on production.** The one remaining 404 is
   `/laws/assets/scripts/ontario-header.js`, which no image publish can fix:
   production still stores the old provision text that names it. The same
   reload removes the ontario.ca footer from OBC 2012 `4.4.1.1./C` and OBC
   2006 `4.3.1.1./C`.

   Two cautions. Apply migration `0049` first. Reload oldest to newest, because
   a reload wipes every cross-edition row that touches the edition
   (`project_edition_reload_cascade`).

   Then re-run both checks. `verify_assets.py` now reads
   `provision_version_assets`, so it needs the migration.

## How to check it

Two checks, because the structured keys and the HTML references are two
different sets and only one of them has a manifest:

* `verify_assets.py` — every key the structured fields name. Passed on
  2026-08-02: 532/532 return 200.
* `verify_html_refs.py` — every path the version HTML names. Failed on
  2026-08-02 with 26 of 141; after the publish, 140 of 141.

Both scripts read the production key list from the database and fetch through
`www.codechronicle.ca`, so they test the Cloudflare route, the Worker, the R2
binding and the object together. Both are throwaway copies in `.tmp/`. Promote
`verify_html_refs.py` to a management command if this recurs.

## Related

`tasks/complete/provenance/inline-html-image-assets.md` — the card that built
the inline-asset pipeline. It assumed one asset directory per regulation.

## Producer-side verification (CCM, 2026-08-02)

| Edition | Asset references in shipped HTML | Missing before | Missing after |
|---|---|---|---|
| OBC 1997 | 1 | 0 | 0 |
| OBC 2006 | 29 | 26 | 0 |
| OBC 2012 | 127 | 104 | 0 |

CCM re-derived both e-Laws bases, rebuilt all three editions, and fetched 130
assets with no HTTP error. Path A / Path B parity is unchanged: OBC 2006 shows
3365 agree and 0 disagree; OBC 2012 shows 4063 agree and 0 disagree. The full
CCM test suite passes (3561 tests).
