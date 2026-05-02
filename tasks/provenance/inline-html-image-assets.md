# Contract extension — inline-image assets embedded in version HTML

**Status: PROPOSED.**  Driven by CCM's amendment-pipeline work
(triage-50, image-equation drop investigation, 2026-05-01/02).
CCM-side card: `CodeChronicleMapping/tasks/amendment-pipeline/impl-53-image-mirroring-and-inline-html.md`.

## Motivation

Post-2017 Ontario source filings (88/19, 139/17, 191/14, etc.) inline
equations and scanned figures as `<img>` tags embedded in the body of
`amend_add` and `amend_strike_sub` directives.  Example from O. Reg.
88/19 cl. 110 → `4.1.6.5.`:

```html
<p class="equation-e">
  <img src="/laws/images/en/R19088_e_files/image007.gif"
       alt="Image of equation: x subscript d = 5((C subscript b)(S subscript s)/gamma)..."/>
</p>
```

These belong **inline in the body html**, not as separate page-images.
The current contract has slots for full-page images (`versions[].page_images`)
and table-region images (`versions[].tables[].images`) but no slot for
images referenced from inside `versions[].html`.

CCM's pipeline currently drops these tags during payload extraction,
silently omitting equations and figures from new provisions added by
post-2017 amendments.  Fixing the drop on the CCM side requires CC to
accept inline `<img>` references and a manifest of the assets they
point to.

## Proposed contract addition

### `regulations[].assets`

A regulation-level asset registry, keyed by stable relative path:

```json
"regulations": [
  {
    "reg_id": "88/19",
    "role": "amend",
    ...,
    "assets": [
      {
        "path": "images/88-19/abc12345_image007.gif",
        "original_url": "https://www.ontario.ca/laws/images/en/R19088_e_files/image007.gif",
        "sha256": "abc12345...",
        "bytes": 4231,
        "content_type": "image/gif"
      },
      ...
    ]
  }
]
```

- `path`: stable, sha-prefixed relative path used as the `src` attribute
  of every `<img>` tag in `versions[].html` that references this asset.
  Sha-prefix makes the path content-addressed: identical bytes
  collapse to one record across regs/editions if CC wants.
- `original_url`: source URL (for provenance / refetch).
- `sha256`: full hash of the bytes for verification.
- `bytes`, `content_type`: standard metadata.

Regulation-level (not version-level) because the same image can be
referenced by multiple versions of the same provision (e.g. the figure
captured at `amend_add` time is still inline in subsequent
`amend_strike_sub` versions that don't replace it).

### `versions[].html`

Already accepts arbitrary inline HTML.  Extension is informal: the
`<img src="…">` attribute now points at the relative `path` from
`regulations[].assets`, not at an external URL.  CC's renderer should
allow `<img>` through any HTML sanitizer applied to this field.

## CCM responsibilities (out of scope for CC)

CCM owns:
- Fetching images at extraction time (`https://www.ontario.ca{src}`).
- Hashing, dedup, and stable path generation.
- Writing assets into the build artifact at `images/<reg-slug>/<sha-prefix>_<name>`.
- Emitting the `regulations[].assets` array.
- Rewriting `<img src>` in `versions[].html` to the relative `path`.

## CC responsibilities

CC owns:
- Accepting and validating the `regulations[].assets` schema in the
  edition loader.
- Copying asset bytes from the build artifact into CC's static asset
  bucket (S3 or equivalent) at ingestion time.
- Serving them at the same relative `path` so the inline `<img>`
  references in `versions[].html` resolve.
- Allowlisting `<img>` through any HTML sanitization applied to
  `versions[].html`.

## Test cases

Once landed:
1. Loader accepts a fixture edition with `regulations[].assets`
   populated and inline `<img>` references in `versions[].html`.
2. Validation: rejects an edition where a `<img src>` in
   `versions[].html` doesn't resolve to a `regulations[].assets`
   entry.
3. Validation: rejects asset entries whose `sha256` doesn't match the
   bytes of the file at `path` in the build artifact.
4. Display: rendered version body shows the image inline, not as a
   broken link or stripped element.

## Open questions

1. **Asset path scoping** — regulation-level (`images/<reg-slug>/…`)
   vs sha-only (`images/<sha-prefix>.<ext>`)?  Sha-only makes dedup
   trivial across regs but loses provenance hints in the path.
   Suggest: regulation-level path, with cross-reg dedup tracked via
   `sha256` field rather than path collision.
2. **Refetch policy** — if the upstream URL 404s in 5 years, the
   build artifact still has the bytes; CC's bucket still has them.
   The `original_url` is documentary, not load-bearing.  Confirm CC
   has no logic that re-fetches from `original_url`.
3. **Crown copyright** — Ontario eLaws content is Crown copyright
   with permission to reproduce.  Image assets fall under the same
   licence.  No additional licence work needed, but flagging for the
   CC team's awareness.

## Coordination

- CCM impl card lands first with the build-artifact asset emission;
  CC schema extension lands in parallel and is a no-op until the
  first edition with `assets` populated arrives.
- Schema bump should be backwards compatible — old editions without
  `regulations[].assets` keep loading.
