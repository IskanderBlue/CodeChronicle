# Decide the fate of the BYOD PDF viewer (post-provenance-cleanup)

**Status: OPEN — product/licensing decision needed before any code change.**
Raised 2026-06-02 during the provenance cleanup (`tasks/complete/provenance/5-cleanup.md`).

## The question

Does CodeChronicle keep the **bring-your-own-PDF** viewer for editions we
can't host (OBC 2024, national codes), or is every edition — including
commercial ones — meant to be served as **hosted page images** on
`CodeEditionProvisionVersion`?

The provenance design (`tasks/complete/provenance/00-overview.md`) asserts
*"No BYOD. We host the documents ourselves… page images on versions. No
in-browser compositing."*  But that assumes we are legally allowed to host
each edition.  OBC 2024 and the national codes are **commercial** documents;
if we can't redistribute them, BYOD (the user supplies their own purchased
PDF, we align/annotate it client-side) is the only lawful path — not legacy
cruft.

## What exists today (the BYOD subsystem — currently dormant, NOT dead)

- `static/js/pdf-viewer.mjs` — PDF.js-based viewer + per-user PDF→edition
  mapping stored client-side.
- Imported live by `templates/search.html:7` and `templates/settings.html:8`
  (settings has a "your uploaded PDFs" management UI).
- `search.html` `data-pdf-block` (~360–442): viewer mount, file picker,
  dropzone, filename-mismatch guard, cache controls.
- pdf.js CDN CSS at `search.html:5`.

It is **dormant**, not active: every entry condition keys on
`viewerResult.pdf_filename` / `.source_url` / `.page` / `.initial_page_top` /
`.final_page_bottom`, and the only currently-loaded edition (OBC 2012) is
e-Laws/hosted, so none of those are ever set.  Nothing breaks today.

## What the provenance cleanup removed (the plumbing that fed it)

Commit `95a6af6` (per `5-cleanup.md`) dropped the server-side fields/helpers
that populated the BYOD path for publisher-PDF editions:

- `CodeEdition` fields: `pdf_files`, `download_url`, `source_url`, `map_codes`.
- `config/code_metadata` helpers: `get_pdf_filename`, `get_download_url`,
  `get_source_url`, `get_pdf_expectations`.
- `core/views/search.py` provision-context keys: `pdf_filename`,
  `pdf_download_url`, `source_url`.
- `config/metadata.json` (carried the per-edition `pdf_files` manifest).

So even if we keep BYOD, the backend no longer tells the frontend *which*
PDF/page an edition maps to.

## Two outcomes

1. **BYOD is obsolete** (design as written): publisher editions are also
   ingested as hosted page images.  → Remove `pdf-viewer.mjs`, the pdf.js CDN
   CSS, the `data-pdf-block` + `source_url` branches in `search.html`, and the
   PDF-mapping UI in `settings.html`.  (~several hundred lines + a static
   module.)
2. **BYOD is the mechanism for un-hostable editions** (likely for OBC 2024 /
   national codes): the cleanup removed needed plumbing.  → Restore a
   provenance-shaped equivalent: derive `pdf_filename` / `page` / page-bounds
   for a version from the new models (or a small per-edition PDF manifest) and
   re-wire `viewer_section_content` / the provision context to emit them when
   an edition is publisher-PDF rather than hosted.

## Do NOT

- Do not delete the viewer or the settings UI until outcome 1 is chosen.
- Do not re-add the dropped `CodeEdition` columns blindly under outcome 2 —
  prefer a manifest keyed to the provenance schema (the columns were genuinely
  the wrong home; see `5-cleanup.md`).

## Definition of done

A recorded decision (1 or 2), and the live surface made internally
consistent with it — no dormant subsystem keyed on fields the backend will
never send.
