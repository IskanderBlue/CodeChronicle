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

## Design — URL-mirrored layout (no `<img src>` rewrite)

CCM mirrors each referenced image to its on-disk build artifact at the
**URL path verbatim**:

```
data/outputs/
├── OBC_2012.json
└── laws/
    └── images/
        └── en/
            └── R19088_e_files/
                ├── image007.gif
                └── image008.gif
```

Because `<img src>` in the source filing already says
`/laws/images/en/R19088_e_files/image007.gif` (root-relative URL), and
CC mounts the asset bucket at host root with the same prefix, the
references resolve directly.  **No rewrite of `<img src>` is needed**
on either side — the HTML coming out of CCM's parser is the final form.

## Proposed contract addition

### `regulations[].assets`

A regulation-level asset registry, keyed by stable relative path:

```json
"regulations": [
  {
    "reg_id": "88/19",
    "role": "amendment",
    ...,
    "assets": [
      {
        "path": "laws/images/en/R19088_e_files/image007.gif",
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

- `path`: stable relative path that matches the URL path component of
  the corresponding `<img src>` (sans leading slash) AND the on-disk
  location under the build artifact root.  CC serves at this same path,
  prefixed by host root, so the inline `src` references resolve.
- `original_url`: source URL (for provenance / refetch).  Documentary,
  not load-bearing once the bytes are mirrored.
- `sha256`: full hash of the bytes for verification on ingestion.
- `bytes`, `content_type`: standard metadata.

Regulation-level (not version-level) because the same image can be
referenced by multiple versions of the same provision (e.g. the figure
captured at `amend_add` time is still inline in subsequent
`amend_strike_sub` versions that don't replace it).  A regulation's
`assets[]` is the closure of every image its body HTML references.

The on-disk image tree under `data/outputs/laws/images/...` is
**shared across editions and regulations** — same URL, same file.
Cross-edition dedup is automatic by URL.  Each edition's `assets[]`
arrays just point at the shared pool.

### `versions[].html`

Already accepts arbitrary inline HTML.  Extension is informal: `<img
src="…">` attributes carry the original e-Laws root-relative URL
(``/laws/images/...``).  CC's renderer should allow `<img>` through
any HTML sanitizer applied to this field.

## CCM responsibilities (out of scope for CC)

CCM owns:
- Fetching images at extraction time (`https://www.ontario.ca{src}`).
- Rate-limited, idempotent, content-addressed local mirroring at
  `data/outputs/<URL-path>` (e.g. `data/outputs/laws/images/...`).
- Emitting the `regulations[].assets[]` array per amendment regulation.
- **Not** rewriting `<img src>` — the HTML's `src` attribute already
  matches the served path.

## CC responsibilities

CC owns:
- Accepting and validating the `regulations[].assets[]` schema in the
  edition loader.
- Copying asset bytes from the build artifact tree into CC's static
  asset bucket (S3 or equivalent), preserving the relative path
  (`laws/images/en/R19088_e_files/image007.gif`).
- Serving them at host root with the prefix the `<img src>` expects
  (`/laws/...`).  Either the bucket sits under that prefix on the
  serving origin, or a `<base href>` declares the asset host.
- Allowlisting `<img>` (and the `/laws/images/` src prefix) through
  any HTML sanitization applied to `versions[].html`.

## Test cases

Once landed:
1. Loader accepts a fixture edition with `regulations[].assets`
   populated and inline `<img>` references in `versions[].html`.
2. Validation: every `<img src>` in `versions[].html` whose URL path
   matches a known prefix (`/laws/images/`) resolves to a
   `regulations[].assets[]` entry on some regulation in the edition.
3. Validation: rejects asset entries whose `sha256` doesn't match the
   bytes of the file at `path` in the build artifact.
4. Display: rendered version body shows the image inline, not as a
   broken link or stripped element.
5. Display: a host serving the asset bucket at `/laws/...` resolves
   inline `<img src="/laws/images/...">` without any in-app rewrite.

## Open questions

1. **Cross-host serving.**  If CC serves the main app from
   `app.codechronicle.ca` and the asset bucket from a different host
   (CDN), the root-relative `<img src="/laws/...">` would resolve
   against the app host rather than the asset host.  Two fixes:
   (a) serve the asset bucket from the app host under `/laws/...`,
   (b) inject `<base href="https://assets.codechronicle.ca/">` into
   the rendered version page.  Defer until CC's deployment topology
   is set.
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
