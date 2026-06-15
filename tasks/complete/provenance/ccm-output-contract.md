# CCM Output Contract

What CodeChronicle expects from CodeChronicleMapping's pipeline output.
This is the interface between the two repos.

## Output: One JSON per Edition

CCM produces one consolidated JSON file per code edition. Example:
`OBC_1997.json`. This file contains everything CodeChronicle needs to
populate its provenance models for that edition.

## Top-Level Schema

```json
{
  "code": "OBC",
  "edition": "1997",
  "effective_date": "1998-04-06",
  "ineffective_date": "2006-12-31",
  "amendment_chain_complete": true,
  "bbox_format": "xywh_fraction_topleft",

  "regulations": [ ... ],
  "provisions": [ ... ],
  "provision_mappings": [ ... ],
  "provision_discontinuations": [ ... ],
  "mapping_coverage": [ ... ]
}
```

No `base_regulation` or `revoked_by` at the top level — these are
identified from the regulations array by `role: "base"` and by the next
edition's base regulation respectively.

### `bbox_format`

Coordinate system for **every** bbox in the file —
`versions[].page_images[]`, `versions[].tables[].images[]`, and
`regulations[].clauses[].bbox` alike. Current and only supported value:

- `"xywh_fraction_topleft"` — each bbox is `{x, y, w, h}` where `x, y` is
  the **top-left corner** and `w, h` the size, all as **fractions (0–1)
  of the rendered image**, top-left origin (y grows downward). A box's
  CSS position is its value × 100% directly — no page size, no y-flip.

The frontend treats a missing `bbox_format` as this value (today only
the editions that actually carry non-empty bboxes declare it).

## `regulations[]`

All regulations for this edition (base + amendments), ordered by
effective date then filing date.

```json
{
  "reg_id": "403/97",
  "role": "base",
  "amends": null,
  "filed_date": "1997-11-03",
  "effective_date": "1998-04-06",
  "source_pdf": "ont_reg_1997_v3.pdf",
  "source_pages": [1, 400],
  "clauses": []
}
```

```json
{
  "reg_id": "22/98",
  "role": "amendment",
  "amends": "403/97",
  "filed_date": "1998-01-27",
  "effective_date": "1998-04-06",
  "source_pdf": "ont_reg_1998_v1.pdf",
  "source_pages": [29, 51],
  "clauses": [
    {
      "clause_id": "1.(1)",
      "parent_clause": "1",
      "action": "revoke_and_substitute",
      "target_level": "article",
      "target_id": "1.1.3.2.",
      "target_division": "B",
      "clause_text": "The definitions of 'Alternative measure'...",
      "strike_text": null,
      "sub_text": null,
      "page": 29,
      "bbox": {"x": 0.36, "y": 0.21, "w": 0.32, "h": 0.05}
    }
  ]
}
```

### `clauses[].action` values

| Value | Meaning |
|-------|---------|
| `revoke_and_substitute` | Replace target entirely with payload |
| `amend_add` | Add content to/after target |
| `amend_strike_sub` | Find and replace text in target |
| `revoke` | Remove target |
| `renumber` | Re-id target (pairs with a `provision_mappings[]` entry) |

### `clauses[].target_level` values

| Value | Meaning |
|-------|---------|
| `article` | Article (e.g., 1.1.3.2.) |
| `sentence` | Sentence within an article (e.g., 9.10.18.6.(1)) |
| `clause` | Clause within a sentence (e.g., 3.2.2.9.(1)(a)) |
| `subclause` | Subclause (e.g., 2.1.1.2.(1)(a)(ii)) |
| `subsection` | Subsection (e.g., 9.33.2.) |
| `section` | Section (e.g., 2.11.) |
| `part` | Part (e.g., 2) |
| `table` | Table (e.g., Table-2.5.1.1.) |

`table` is a valid target level for clauses because gazette directives
target tables directly. The clause resolves to the parent provision for
versioning — CodeChronicle handles this during ingestion.

### `clauses[].target_division` (optional)

The division the target provision lives in, as a **bare letter** — `"A"`,
`"B"`, or `"C"` for OBC 2006+/NBC — matching the `provisions[].division`
format exactly. The same bare `target_id` (e.g. `1.1.3.2.`) can exist in
more than one division, so this is what pins the clause to the correct
provision without CodeChronicle having to recover it heuristically from the
through-model link at read time.

Empty string (the default) means **no single target division**: either a
division-less edition (OBC 1997) or a meta-amendment whose target is itself
a clause rather than a divisioned provision. Back-compatible — pre-existing
JSONs without the key ingest as `""`.

```json
{
  "clause_id": "1.(1)",
  "target_level": "article",
  "target_id": "1.1.3.2.",
  "target_division": "B"
}
```

### `clauses[].clause_text`

The directive text from the gazette, verbatim. E.g.:

> "The definitions of 'Alternative measure', 'Private sewage disposal
> system' and 'Sewage system' in Article 1.1.3.2. of the Regulation are
> revoked and the following substituted"

### `clauses[].target_reg` (optional)

Regulation slug (e.g. `"360/13"`) when the clause targets another
regulation's clauses rather than a base-code provision
(**meta-amendment**). Empty string (the default) means the target is a
base-code provision — this keeps the field fully back-compatible with
pre-impl-26 JSONs.

```json
{
  "clause_id": "165",
  "target_reg": "360/13",
  "target_id": "5",
  "target_level": "section"
}
```

Meta-amendment clauses currently ship as **pointer-only** entries —
`action`, `clause_text`, `strike_text`, and `sub_text` are absent.
Full text-mutation fields arrive in impl-27. Consumers must tolerate
clauses without `action`.

### `clauses[].amended_by` (optional)

Back-pointers on a **target regulation's** clauses listing the
meta-amending clauses that touched them. Populated automatically from
forward-pointer clauses — callers don't emit this themselves.

```json
{
  "clause_id": "5",
  "amended_by": [
    {
      "reg_id": "191/14",
      "clause_id": "165",
      "action": "revoke",
      "effective_date": "2015-01-01"
    }
  ]
}
```

Until impl-27 lands, `amended_by` entries may appear on **stub
clauses** that carry only `clause_id` + `amended_by` (no `action`,
no `target_*` of their own). Merge with the full clause entry when
both are present; otherwise render as a back-pointer-only row.

### `clauses[].page`, `clauses[].bbox`

Locate the clause on its gazette source page. The regulation detail view
shows the full page (`documents/{source_pdf}/{page}.webp`) with an
overlay marking where the clause sits.

- `page`: 1-based page number in `source_pdf`.
- `bbox`: `{x, y, w, h}` of the clause **body region** on that page, in
  the same `bbox_format` fraction system as the image bboxes (top-left
  origin, all 0–1; overlay position is value × 100% directly).

CodeChronicle stores the clause `bbox` verbatim in a `RegulationClause`
JSONField, so the encoding flows straight through — the regulation detail
view renders the amber overlay from these fractions. (No `id_bbox`: an
earlier draft proposed one but CCM does not emit it, matching the
image-bbox decision to use `bboxes[0]` as the anchor.)

## `provisions[]`

All provisions in the edition with their complete version chain.

Provision bboxes encompass the provision text plus any associated tables.

```json
{
  "provision_id": "1.1.3.2.",
  "level": "article",
  "division": "A",
  "parent_id": "1.1.3.",
  "appendix_of_id": null,

  "versions": [
    {
      "version": 0,
      "clauses": [],
      "effective_date": "1998-04-06",
      "ineffective_date": "1998-04-06",
      "transition_provision_ref": null,

      "title": "Definitions",
      "html": "<p>In this Code,</p><p>...</p>",
      "page_images": [
        {"image": "documents/obc_1997_v2.pdf/42.webp", "bboxes": [{"x": 0.065, "y": 0.75, "w": 0.43, "h": 0.025}]}
      ],
      "keyword_counts": {"fire": 3, "safety": 1},

      "tables": []
    },
    {
      "version": 1,
      "clauses": [
        {"regulation": "22/98", "clause_id": "1.(1)"}
      ],
      "effective_date": "1998-04-06",
      "ineffective_date": null,
      "transition_provision_ref": null,

      "title": "Definitions",
      "html": "<p>In this Code,</p><p>...amended...</p>",
      "page_images": [],
      "keyword_counts": {"fire": 3, "safety": 1, "sewage": 2},
      "notes": [
        {"kind": "elaws-note", "text": "Note: On March 31, 2023, ... is revoked. (See: O. Reg. 434/22, s. 1 (2))"},
        {"kind": "elaws-html-substitution", "text": "html replaced with e-Laws snapshot value (effective 1998-04-06); text-equivalent fingerprint match."}
      ],

      "tables": []
    }
  ]
}
```

Note v0's `ineffective_date` equalling its `effective_date` — a
zero-width window. Emitted whenever the first amendment on a
provision falls on the same date as the base edition's effective
date (common: day-zero amendments filed simultaneously with the
base regulation). Preserves the "as-filed" snapshot without
claiming it was ever in force. Consumers that only want in-force
windows can filter `v.ineffective_date == v.effective_date`.

### `versions[].notes` (optional)

Editorial annotations and provenance notes that accumulated on the
source — pointers, not regulation text. Each entry is a tagged object
`{"kind": <NoteKind>, "text": str}` with an optional `"scope"` qualifier
(e.g. `"definition 'building'"`); the list is omitted or `[]` when a
version has none. **CCM owns the `kind` taxonomy** — it tags every note
with a fine-grained `NoteKind` at its emission site (CCM impl-139), not
by string-sniffing. CodeChronicle stores the list verbatim and maps
`kind` → display tier. Consumers MUST route by `kind`, never by parsing
the `text`.

CCM emits **16 consumer-facing kinds** (its three Path-A-internal kinds —
`elaws-future-amendment`, `italics-drift`, `presentation-drift` — never
reach the consolidated edition). CodeChronicle (`core/provision_notes.py`)
maps them as:

| `kind` | meaning | CC display tier |
| --- | --- | --- |
| `elaws-note` | reader-facing e-Laws Pnote annotation (e.g. a scheduled revocation) | annotation (serif band) |
| `editor` | manual curator's editor's note | annotation (serif band) |
| `elaws-editorial-correction-accepted` | curator-accepted snapshot↔filing correction | annotation (serif band) |
| `unapplied-directive` | a strike/amend directive the applicator could **not** apply — text may be incomplete | integrity caveat (*may be incomplete*) |
| `revoke-target-missing` | a revoke whose target was absent from the prior version (structural anomaly) | integrity caveat (*structural anomaly*) |
| `elaws-html-substitution` | field replaced with the snapshot value (fingerprint match) | sourcing badge |
| `elaws-html-substitution-forced` | field deferred to the snapshot (Path B could not compute) | sourcing badge |
| `elaws-defer-difficult-directive` | formula/equation/image directive deferred to the snapshot | sourcing badge |
| `payload-heading-correction` | subsection-wrapper id normalised from source | record (collapsed) |
| `elaws-table-header-merge` | e-Laws merged-column-header table layout | record (collapsed) |
| `strike-text-override` | body strike matched via manual override | record (collapsed) |
| `strike-text-override-title` | title strike matched via manual override | record (collapsed) |
| `strike-case-insensitive` | strike matched case-insensitively | record (collapsed) |
| `amend-add-anchor-override` | amend-add anchor matched via manual override | record (collapsed) |

Two further consumer-facing kinds are **not** rendered — CodeChronicle
handles them at the load boundary:

| `kind` | CC handling |
| --- | --- |
| `snapshot-divergence` | **Rejected at ingest.** A ready edition must carry no unreviewed snapshot divergences; CC raises so the producer resolves/gates them upstream. |
| `pdf-rejoin` | **Dropped at ingest.** Base-extraction noise (line-end hyphenation rejoined); not worth surfacing or storing. |

> Upstream follow-up: because `snapshot-divergence` and `pdf-rejoin` are
> never consumer-rendered, the *effective* consumer-facing set is 14. The
> clean fix is CCM gating both at assembly (as it already internalised
> italics/presentation-drift); CC's raise/drop is the backstop.

An unrecognised future `kind` is rendered in the forensic `record` tier
rather than dropped. The bare-string form (`"elaws-note: …"`) is the
legacy pre-classification shape and is **rejected** at ingest.

### Appendix provision example

```json
{
  "provision_id": "A-1.1.3.2.(1)",
  "level": "sentence",
  "division": "A",
  "parent_id": "A-1.1.3.2.",
  "appendix_of_id": "1.1.3.2.",

  "versions": [
    {
      "version": 0,
      "clauses": [],
      "effective_date": "1998-04-06",
      "ineffective_date": null,
      "transition_provision_ref": null,

      "title": "",
      "html": "<p>The OBC applies to both site-built and...</p>",
      "page_images": [
        {"image": "documents/obc_1997_appendix.pdf/12.webp", "bboxes": [{"x": 0.065, "y": 0.62, "w": 0.43, "h": 0.025}]}
      ],
      "keyword_counts": {},

      "tables": []
    }
  ]
}
```

**`appendix_of_id`**: The `provision_id` of the body provision this note
annotates. CodeChronicle resolves this to a `CodeEditionProvision` FK
during ingestion. Body provision and appendix provision must be in the
same edition.

Appendix provisions have their own version chains — they can be
independently amended. `parent_id` is the structural parent in the
appendix tree (e.g., `A-1.1.3.2.` for sentence `A-1.1.3.2.(1)`),
while `appendix_of_id` links across to the body tree.

### `provisions[].level` values

| Value | Meaning |
|-------|---------|
| `division` | Division |
| `part` | Part |
| `section` | Section |
| `subsection` | Subsection |
| `article` | Article |
| `sentence` | Sentence (appendix provisions, e.g. `A-1.1.1.1.(2)`) |
| `clause` | Clause (appendix provisions, e.g. `A-3.2.2.9.(1)(a)`) |

No `table` level — tables are content within provisions. `sentence` and
`clause` levels are used by appendix provisions only — body provisions
collapse sub-article IDs into the parent article.

### Version-level `action` is not stored

Versions do not carry a version-level `action` field. Where a kind-
of-change label is needed, it is **derived** from the version's
contributing clauses:

| Semantic | Derivation |
|----------|------------|
| "original" | `version == 0 AND clauses == []` |
| "added"    | `version == 0 AND any clause has `action == "amend_add"` whose `directives[]` creates this provision id` |
| "revoked"  | Any contributing clause has `action == "revoke"` |
| "renumbered" (new id) | A `provision_mappings[]` entry points its `introduced_by.version` at this version |
| Other kinds (revoke_and_substitute, amend_strike_sub, amend_add content-only) | Inspect contributing clauses' actions directly |

Fine-grained amendment intent lives on `RegulationClause.action`,
which is where it belongs — per clause, not per version (a single
version can aggregate clauses of different kinds; see below).

### `versions[].clauses[]`

The list of gazette clauses that contributed to this version, in
application order. Each entry references a clause on a regulation
elsewhere in `regulations[]`.

```json
"clauses": [
  {"regulation": "22/98", "clause_id": "18"},
  {"regulation": "122/98", "clause_id": "2.(1)"},
  {"regulation": "122/98", "clause_id": "2.(2)"}
]
```

- `version == 0` base originals emit `clauses: []`.
- `version == 0` amend-add-created provisions emit the single
  creating clause.
- Every other version emits one entry per clause that applied
  during this version's window.
- Application order is `(regulation.filed_date, clause_id)` — the
  order in which the applicator actually processed them.

CodeChronicle resolves each `(regulation, clause_id)` tuple to a
`RegulationClause` FK during ingestion and stores the list as an
M2M relation on `CodeEditionProvisionVersion`.

### `versions[].effective_date` / `ineffective_date`

**One `ProvisionVersion` per `(provision_id, effective_date)` pair.**
If ten clauses — from any number of regulations — act on one
provision on one date, they collapse into a single version carrying
all ten clause refs in `clauses[]`. Version numbers are a strict
ascending sequence per provision: v0, v1, v2, …  No version-number
collisions, no same-date duplicates.

- `effective_date`: when this version comes into force.
- `ineffective_date`: when this version ceases to be in force. Null
  if this is the current version and the edition is still in force.
- `ineffective_date == effective_date` — a zero-width window — is
  legal and carries the "as-filed but superseded same day" case.
  Typical for v0 of a provision whose first amendment shares the
  base regulation's effective date.
- During a transition period, the old version's `ineffective_date`
  is extended to the overlap end. Both versions have overlapping
  date ranges.

### `versions[].transition_provision_ref`

When this version creates a transition period (the previous version
continues to apply for some permits), this is a record pinning the
exact version of the Division C / Part 12 provision that defines the
transition terms:

```json
{
  "provision_id": "4.1.2.1.",
  "division": "C",
  "version": 0
}
```

- `provision_id`: bare provision id (no division prefix).
- `division`: division string ("" for division-less editions like
  OBC 1997).
- `version`: version index of the transition article in force at the
  linking version's `effective_date`.  CCM commits to this on the
  producer side (impl-57) so consumers don't have to make the
  judgment call.

CodeChronicle dereferences this triple directly to a
`CodeEditionProvisionVersion` row at ingest time and stores the FK on
the linking version.  Hard error if the triple doesn't resolve — the
new shape exists to remove ambiguity, so a missing referent is a real
bug, not a soft case.

Null when no transition applies.

> **Migration note (impl-57, 2026-05-04):** This field was previously
> named `transition_provision_id` and carried a bare provision id
> string.  CCM no longer emits the legacy field; CC's ingestor raises
> on encountering it (re-emit from CCM if you have an old JSON).

### `versions[].page_images`

List of objects, each referencing a full page image plus a bbox defining
the provision's region on that page. Provisions that span columns or
pages have multiple entries in reading order.

```json
"page_images": [
  {
    "image": "documents/obc_1997_v3.pdf/143.webp",
    "bboxes": [
      {"x": 0.065, "y": 0.50, "w": 0.43, "h": 0.025},
      {"x": 0.52, "y": 0.04, "w": 0.45, "h": 0.40}
    ]
  }
]
```

- `image`: S3 path to the full page image (shared across provisions on
  the same page).
- `bboxes`: list of `{x, y, w, h}` regions on that page in **reading
  order**, in the `bbox_format` fraction system (top-left origin, all
  0–1; see the `bbox_format` section). `bboxes[0]` is the **start
  anchor** — the provision's first/identifier line; the frontend opens
  the focused view scrolled so `bboxes[0].y` sits at the top, putting
  the start at the top. Later entries are subsequent column/region
  blocks (a provision that flows across columns starts bottom-left,
  continues top-right). "View full page" overlays every bbox as a
  highlight (`left:x·100% top:y·100% width:w·100% height:h·100%`) on the
  uncropped page. CodeChronicle stores `page_images` verbatim, so the
  encoding flows straight through with no loader/model change.

> There is no separate `id_bbox`. CCM previously planned one (the
> printed identifier line, so the page could open on the number rather
> than the body); it was dropped because `bboxes[0]` already marks the
> start. For most provisions `bboxes[0]` is exactly the thin identifier
> line; the focused scroll therefore lands on it directly with no
> caption estimate.

Multiple entries in `page_images` handle provisions spanning pages.
Each entry is one page; bboxes within that entry are column regions.

Empty list when no page images exist (HTML-only amended provisions).

### `versions[].tables[]`

Tables belonging to this provision at this version.

```json
{
  "table_id": "Table-3.1.4.7.",
  "caption": "Fire Resistance Ratings",
  "images": [
    {"image": "documents/obc_1997_v2.pdf/143.webp", "bboxes": [{"x": 0.065, "y": 0.13, "w": 0.92, "h": 0.83}]},
    {"image": "documents/obc_1997_v2.pdf/144.webp", "bboxes": [{"x": 0.065, "y": 0.04, "w": 0.92, "h": 0.75}]}
  ],
  "html": "",
  "notes": "Note (1): For buildings of...",
  "order": 0
}
```

- `images`: list of `{image, bboxes}` objects. Same format as
  `page_images` — full page image path + `{x, y, w, h}` fraction bboxes
  (`bbox_format`) for the table region, `bboxes[0]` the start anchor
  (the caption / first row), the frontend scrolling so `bboxes[0].y`
  sits at the top. For base tables these are source document pages; for
  amended tables the `image` path points to the pre-composited image
  (bbox covers the full composited image).
  May be an empty list when `html` is populated and no authoritative
  image form is available for this version. Like `page_images`, the
  encoding is stored verbatim — no `id_bbox` (dropped; `bboxes[0]` is
  the anchor).
- `html`: Structured table markup (e.g. `<table>...</table>`) sourced
  from e-Laws when a point-in-time HTML form exists for this version.
  Empty string when unavailable — the renderer falls back to `images`.
  Typically populated for base v0 of e-Laws-sourced editions and the
  latest consolidated version; historical amended versions usually
  stay image-only because e-Laws only publishes current consolidations.
- `notes`: Table notes as text. Notes that were amended have the
  amended text here. When `html` is populated, notes may already be
  embedded in the markup — in that case emit `notes: ""` to avoid
  double-rendering.
- `order`: Display order when a provision has multiple tables.

When a table is amended but its parent provision's text is unchanged,
the parent still gets a new version (with the same `html`) because the
table content changed.

## `provision_mappings[]`

Provision identity mappings — both intra-edition renumbers driven by
gazette directives and cross-edition identity carries. A single unified
array; the two cases are distinguished by whether the old/new editions
match, not by a separate payload shape.

Optional — only present when mapping data exists.

### Intra-edition renumber (introduced by a gazette clause)

```json
{
  "old_provision_id": "9.10.18.6.",
  "old_division": "",
  "old_edition": "1997",
  "new_provision_id": "9.10.18.7.",
  "new_division": "",
  "new_edition": "1997",
  "mapping_type": "renumbered",
  "introduced_by": {
    "provision_id": "9.10.18.7.",
    "division": "",
    "version": 1
  },
  "notes": ""
}
```

`introduced_by` is the **new-id version** that first materialises the
renumber (the version whose `action` is `"renumbered"`). Triple-resolved
by CodeChronicle through the version lookup built from `provisions[]`,
then attached as `ProvisionMapping.introduced_by_version`. This lets the
UI render the gazette clause text (`introduced_by_version.clause.clause_text`)
as the transition narrative for intra-edition pairs.

OBC 1997 has no Division A/B/C structure, so `division` is an empty
string in the example above. For Division-bearing editions (OBC 2006+,
NBC), populate `division` with the top-level Division name.

### Cross-edition identity carry

```json
{
  "old_provision_id": "9.10.18.6.",
  "old_division": "",
  "old_edition": "1997",
  "new_provision_id": "9.10.18.6.",
  "new_division": "B",
  "new_edition": "2006",
  "mapping_type": "renumbered",
  "introduced_by": null,
  "notes": "Renumbered when Division B introduced"
}
```

Cross-edition pairs have no introducing gazette clause (the new edition
is a wholesale re-enactment), so `introduced_by` is null. The UI falls
back to the new version's `transition_provision_ref` (a Division C /
Part 12 entry on the receiving edition) for the transition narrative.

> **Typing issue (2026-06-11).** The 2026-06 payloads emit a *total*
> cross-edition mapping and type identity carries `renumbered` — including
> 2,915 2006→2012 rows whose id **and** division are unchanged. A row
> whose endpoints share the number is a continuation, not a renumber;
> CodeChronicle words such rows "continues as … (same number)" regardless
> of `mapping_type`. Producer fix wanted: either emit only rows where
> identity actually changed, or keep total emission and type carries
> distinctly (e.g. `carried`).

### `mapping_type` values

| Value | Meaning |
|-------|---------|
| `renumbered` | Same content, different id (most common) |
| `split` | One provision becomes several |
| `merged` | Several provisions become one |
| `replaced` | Substantively replaced across the identity boundary |

### Resolution

CodeChronicle resolves `old_edition` + `old_provision_id` +
`old_division` and `new_edition` + `new_provision_id` + `new_division` to
`CodeEditionProvision` FKs during ingestion. `introduced_by` is resolved
via the `(provision_id, division, version)` triple to a
`CodeEditionProvisionVersion` FK on the new-id side.

### `new_provision_id: "not_processed"` sentinel rows (deprecated form)

Some 2006→2012 payloads carry pseudo-mapping rows with
`new_provision_id: "not_processed"` (`new_division: "SB-12"` or
`"SB-10"`) meaning the old provision's content was delegated to a
document outside the corpus (OBC 2006 Part 12 → Supplementary Standards
SB-12/SB-10). CodeChronicle accepts these — they are **never** ingested
as mapping rows; the loader converts them to disposition records with
`status: "not_processed"`, capturing `new_division` as the disposition's
`target_reference` (on these rows the field names the target *document*,
never a real division) — but the preferred emission is a
`provision_discontinuations[]` entry with that status. A pseudo-row in a
mapping array is shape abuse; one record type per meaning.

## `provision_discontinuations[]`

Per-provision disposition overrides for a covered transition. Optional —
only present when such records exist.

On a covered transition, *absence* of a mapping row already reads "no
successor" — CCM emits a total mapping, so every carried-forward
provision has a row (see `mapping_coverage`). These records say what
plain absence can't: a `discontinued` tombstone is an authoritative
verdict with provenance, valuable where a reader might assume continuity
(e.g. 2006 C `1.3.5.4.`, an edition-specific transition article whose
number is reused by an unrelated provision in 2012), and `not_processed`
marks content whose fate lies outside the corpus.

```json
{
  "old_provision_id": "1.3.5.4.",
  "old_division": "C",
  "old_edition": "2006",
  "new_edition": "2012",
  "status": "discontinued",
  "source": "cross-edition-verified",
  "reasoning": "Edition-specific transition article; not carried forward."
}
```

| `status` | Meaning | CC rendering |
|----------|---------|--------------|
| `discontinued` | Content ends at this transition | "Discontinued — no <edition> successor" |
| `not_processed` | Content's fate is outside the corpus (e.g. delegated to SB-12) | Alone: "Content moved to SB-12, not yet covered" when `target_reference` is known, else the generic not-yet-covered marker (deliberately **no** dedicated state). Alongside mapping rows: an extra out-of-corpus leg row after the links (see below) |

- `status` defaults to `"discontinued"` when omitted; unknown values are
  warn-skipped.
- `target_reference` (optional, for `not_processed`): where the content
  went — a document or provision reference outside the corpus (e.g.
  `"SB-10"`, or finer like `"SB-12 1.2.3.4."` if CCM can name it).
  Stored verbatim and named in the user-facing markers; omit when
  unknown. (Sentinel rows feed the same field from `new_division`.)
- `source` / `reasoning` are optional free-text provenance, stored
  verbatim.
- Resolution: `old_edition` + `old_provision_id` + `old_division` →
  `CodeEditionProvision` FK; `new_edition` → `CodeEdition` FK. Unique per
  (provision, new edition); warn-skip on unresolved references.

**Coexistence with mapping rows.** A `not_processed` disposition
alongside mapping rows toward the same new edition is **not** a
contradiction — it is one verdict with multiple legs, one of them
outside the corpus. Live instance: 2006 B `12.3.4.6.` split into 2012 B
`12.3.1.4.` (mapping row) *and* SB-10-delegated content (`not_processed`
sentinel). CodeChronicle renders the linked row(s) plus an
out-of-corpus leg marker ("Some content moved to SB-10, not yet
covered", from `target_reference`) so both successors show. The mirror-image case exists for
merges — a provision partly assembled from content outside the corpus —
but no emission shape expresses the backward leg today (dispositions
key on the *old* provision); define one with CCM if such a verdict ever
arises.

**Row + tombstone is a contradiction (producer requirement).** A
provision must not carry both a mapping row and a `discontinued`
tombstone toward the same new edition — a successor and "no successor"
genuinely conflict. CodeChronicle resolves it deterministically
(mapping rows outrank), but the double emission is a producer bug. One
live instance in the 2026-06 payloads, reported 2026-06-10: 1997
`9.23.9.6.` has BOTH a `renumbered` mapping row (→ 2006 `9.23.9.7.`)
and a discontinuation tombstone.

## `mapping_coverage[]`

Explicit declaration that a transition's provision mapping is **fully
represented** by this payload — including the legitimate case of zero
rows (nothing changed identity). Optional today; required once CCM emits
it (see below).

```json
"mapping_coverage": [
  {"old_edition": "2006", "new_edition": "2012"}
]
```

Why explicit rather than inferred from row existence: inference conflates
"not mapped yet" with "mapped, zero changes", and a partial or failed
load would silently read as covered. The declaration is what licenses
CodeChronicle's lineage resolver to treat the *absence* of a mapping row,
tombstone, and sentinel as a positive "no successor" assertion and call
the provision **discontinued** (CCM emits a total mapping, so every
carried-forward provision has a row). Without coverage, the same
situation honestly renders "transition not yet mapped".

- Ingested into `EditionTransition`; both editions must already be
  loaded (a declaration naming an unloaded edition is warn-skipped, so
  emit it from the *newer* edition's payload).
- Reload semantics: reloading an edition wipes coverage rows touching it
  (its mapping rows die with the provisions CASCADE, and a stale
  coverage claim over deleted rows would mint false "discontinued"
  verdicts). The payload re-declares whatever the load still covers.

> **Status (2026-06-11):** CCM does not emit `mapping_coverage` yet —
> the two dev-DB rows (1997→2006, 2006→2012) are inserted manually after
> every reload as a stopgap. Coordinate emission with CCM; this is the
> remaining contract gap for provision lineage.

## Image Pre-Rendering

CCM is responsible for producing all images referenced in `page_images`
and `tables[].images`. Image management (upload to S3) is handled by
CodeChronicle's deploy/ingest pipeline.

### Image specs

- Format: WebP
- Quality: 85
- Resolution: varies by content. Full gazette pages ~1600px wide.
  Tables and figures sized to their content.

### What CCM renders

| Content | Source | Output path |
|---------|--------|-------------|
| Full page images | Any PDF | `documents/{pdf_name}/{page}.webp` |
| Amended table composites | Base + amendment PDF | `amended/{code}/{edition}/{table_id}/{version}/{num}.webp` |

Full page images are shared — the same image is referenced by every
provision/table/clause on that page, each with its own bbox. No
duplication of page images.

Bboxes are provided per provision and per table in the JSON, as
`{x, y, w, h}` image fractions (`bbox_format`). The frontend opens the
focused view scrolled so `bboxes[0]` (the start anchor) sits at the top,
with a "View full page" toggle that highlights every bbox on the
uncropped image. No `id_bbox`: `bboxes[0]` is the start anchor.

### Gazette page images

Regulation browsing in CodeChronicle shows gazette pages for each clause.
These are source document pages referenced by `RegulationClause.page` +
the regulation's `source_pdf`:

```
documents/{source_pdf}/{page}.webp
```

CodeChronicle constructs the path from the regulation's `source_pdf` and
the clause's `page` number.

## What CodeChronicle Does NOT Expect

- Raw PDF files (CodeChronicle serves images, not PDFs)
- Map JSON files (the map abstraction is gone)
- `transitions.json`-style transition data (transitions are version overlaps)
- Separate amendment JSON files (everything consolidated per edition)
- OCR text for tables (tables are images)
- Editions with incomplete amendment chains
