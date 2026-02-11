# PDF Local-File Strategy

## Problem Summary (Current State)

Current PDF rendering relies on a server endpoint (`/pdf/...`) that tries to read files from `request.user.pdf_directory`. That works only if the path is valid on the server host. It fails for client-local paths like `C:\Users\...` in production.

Key references:
- `core/views.py:233` `serve_pdf(...)` resolves and reads files using `request.user.pdf_directory`.
- `core/views.py:256` and `core/views.py:266` show server-side directory/file checks.
- `api/formatters.py:43` emits `pdf_url` values pointing at `/pdf/{code_edition}/{map_code}/`.
- `templates/search.html:11` and `templates/search.html:40` load those URLs via `pdf.js`.
- `templates/partials/search_results_partial.html:72` and `templates/partials/search_results_partial.html:78` contain fallback HTML/text blocks used when PDF render fails.

Why this is a mismatch:
- Browser JS cannot directly open arbitrary client filesystem paths from server-returned strings.
- Therefore, storing `pdf_directory` server-side does not satisfy the client-local PDF requirement.

## Updated Plan

1. Define target behavior
- PDF rendering is client-side only.
- Each result card supports explicit user file mapping (picker/drag-drop).
- If selected filename does not match expected `pdf_filename`, show warning and allow override.
- When a file is mapped in one card, other visible cards referencing the same expected PDF refresh immediately.
- No dependency on `pdf_directory` for rendering.

2. Build client-side mapping and rendering (single path for all browsers)
- Add per-card upload/drop UI.
- Maintain a client registry keyed by expected `pdf_filename`.
- Render with `pdf.js` from local file bytes (`ArrayBuffer`), not `/pdf/...`.
- Dispatch a global client event (for example `pdf-mapped`) when mapping changes, and re-run render for matching visible cards.

3. Add persistence
- Persist file mappings and cached blobs in browser storage (IndexedDB + OPFS where available).
- On page load, restore mappings and auto-render matching cards.
- Add simple storage controls: show usage estimate and clear cached PDFs.

4. Keep UX simple
- No browser-specific UX branches in product behavior.
- Use one simple flow: user selects/drops file in-card when needed.
- Keep copy concise: local-only use, not uploaded.

5. Test thoroughly before cutover
- Unit tests for mapping logic, mismatch override, and event-based refresh.
- Integration tests for “map once, all matching visible cards refresh”.
- Manual browser verification (Chrome + Firefox): select file, render, refresh, reload, clear cache, bad file.
- Verify fallback behavior when PDF missing/unmapped remains correct.

6. Single cutover after test signoff
- Remove server `/pdf/...` rendering dependency from active flow.
- Remove `pdf_directory` usage from search formatting and settings UI.
- Remove `User.pdf_directory` model field and related migration/state only after tests pass.
- Update docs to describe the local-file mapping workflow.

## Acceptance Criteria

- User can map a PDF in one card and all currently visible matching cards update without another upload.
- Filename mismatch warning appears, but user can proceed.
- PDF preview no longer depends on server filesystem paths.
- Fallback HTML/text still displays correctly when no local file mapping exists.
- `pdf_directory` is removed only after test completion and signoff.
