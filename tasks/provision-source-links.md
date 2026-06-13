# Provision & amendment source links

Give every provision and amendment a link to where it can be verified online —
as close to the authoritative source as we can get. Two **orthogonal** axes; do
not conflate them.

## The two axes

1. **Regulation source** (the legal authority). Per-`Regulation`: `source_url` +
   `source_kind`. The regulation as enacted — its e-Laws regulation page, or a
   gazette scan (archive.org) for pre-e-Laws regs. Sourced **from CCM** (it
   already computes a landing URL internally); never reconstructed in Django (a
   guessed URL can be confidently wrong).

2. **e-Laws consolidation snapshot** (a formatted "as it read" view — **NOT a
   source**). e-Laws republishes the whole consolidated reg each time an
   amendment commences; each republication states the date range it covers.
   Modelled as an edition-keyed, date-range table (`ElawsConsolidation`), built
   **CC-side** from the cached consolidation pages' own banners. Resolved by a
   version's `effective_date` to "the consolidation current the day this version
   took force." Edition-level snapshot URL, not a provision deep-link.

## Status

### DONE — CC side, both axes (uncommitted in the working tree)

Axis 1 (regulation source):
- `Regulation.source_url` (URLField) + `Regulation.source_kind`
  (`SourceKind` choices: elaws / archive_gazette / ontario_ca / other).
  Migration `0034_regulation_source_kind_regulation_source_url`.
- `load_edition._load_regulations` reads `source_url`/`source_kind` defensively
  (`.get(..., "")`) — tolerant of payloads predating the fields.
- `templates/regulation/detail.html` header renders a "VIEW ON <KIND> ↗"
  `.ui-cite` link when `source_url` present; renders nothing when absent.

Axis 2 (consolidation snapshots):
- `ElawsConsolidation` model (edition FK, version, url, effective_from,
  effective_to[null=current]); manager `.resolve(edition_id, on_date)`
  (`from <= d <= to`, inclusive end, latest-start wins, None when uncovered).
  Migration `0036_elawsconsolidation`.
- `scripts/build_elaws_consolidations.py` → `data/elaws_consolidations.json`
  (66 rows: OBC 1997/2006/2012). Reads each cache page's own
  "Historical version for the period X to Y" banner (tag-stripped; the SPA
  splits the text across tags). URL + e-Laws version from the cache **filename**
  (snapshot version index ≠ e-Laws version — OBC 1997 snaps are v13–v25 vs cache
  v1–v13).
- `manage.py load_consolidations` upserts per edition (idempotent, replace).
- `api/formatters.py::_format_single_result` and
  `core/views/regulation.py::_provenance_result` attach `consolidation`,
  resolved by `version.effective_date`.
- `templates/partials/_provenance_band.html` footer strip:
  "e-Laws consolidation · as it read <date> ↗" (.ui-cite, new tab); suppressed
  for never-in-force versions and when no period covers the date.
- Tests: `core/tests/test_consolidations.py` (resolver + loader). All green;
  ruff + mypy clean.
- CCM task doc written: `<CCM>/tasks/regulation-source-fields.md`.

### DONE — CCM shipped; data loaded into dev DB (2026-06-13)

CCM now emits `source_url` + `source_kind` per `regulations[]` entry. Loaded into
local dev DB; coverage:
- OBC 1997: 21/21 (8 `archive_gazette` + 13 `elaws`), 12 consolidation rows.
- OBC 2006: 9/9 `elaws`, 20 consolidation rows.
- OBC 2012: 29/29 `elaws`, 34 consolidation rows.

Axis-1 `elaws` URLs use the as-enacted `r`-prefix landing form
(`/laws/regulation/r00205`), distinct from Axis-2's consolidation `/120332/vN`.
98 tests green (regulation views, formatters, templates, consolidations).

⚠ **OBC 1997 is `verified=False`** in the CCM build (2006/2012 are `verified=True`).
Loaded with `load_edition --allow-unverified` in dev (after confirming HOST is
localhost, not Neon prod). If CCM later marks it verified, drop the flag. Do NOT
force-load unverified into prod without a deliberate call.

### REMAINING

1. **Commit** (user drives) — code is uncommitted; the dev-DB load is not a commit.
2. **Prod load** — when ready: `load_edition` each edition against the Neon
   `DATABASE_URL`, then regenerate + `load_consolidations` (cascade wipes Axis-2
   rows). Decide explicitly whether 1997's unverified state blocks prod.
3. (Optional) extend the search/permalink provenance rail to also surface the
   per-row regulation source link (Axis 1) beside the existing `.ui-cite`
   internal links — floated in design, not yet built.

## Key decisions / gotchas

- **Never reconstruct a URL.** Absent → render nothing. A well-formed wrong URL
  is worse than no link (masthead "never faked" ethos).
- **`effective_to` is sourced per-file** from each consolidation page's own
  banner — NOT `next_version.effective_from − 1`. This is gap-preserving:
  skipped stub slots (OBC 2012 v18 → 2019-05-02..06-30, v28 → 2022-04-29..06-30)
  leave honest coverage gaps where the resolver returns None. Those stub `/vN`
  URLs **do not resolve on e-Laws** — never synthesize rows for them.
- **Resolve by `version.effective_date`**, not query_date: rides the commencement
  seam (the amendment event both creates a CCM version and triggers e-Laws to
  republish), so the snapshot first embodies that version. Also makes search and
  permalink share one resolver (permalink has no query date).
- **Base-enactment gap interaction:** original provisions have no contributing
  clause (the base reg adopts the code as a schedule), so Axis-1 source for an
  original resolves via `edition → base reg` directly, NOT the clause join.
  (Axis 2 is edition-keyed so it sidesteps this entirely.) See
  `memory/project_base_enactment_gap.md`.
- `data/elaws_consolidations.json` is a generated artifact; prod flow needs the
  CCM repo checked out beside CC to regenerate.
