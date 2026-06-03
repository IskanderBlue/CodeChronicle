# transition_provision: rename + reshape from string id to record

**Status: DONE (2026-05-05).**  CCM-side impl-57 landed across five
commits on `automation/codechroniclemapping-pdf-remap` (819b6c8 step 1,
431eb5e step 2, 5b0957e step 3, ef65672 step 4, 660c959 close-out).
CC ingestor follow-up landed on this branch (`cepv`):

- `core/management/commands/load_edition.py` —
  `_resolve_transition_provisions` rewritten to read
  `transition_provision_ref` (the new record shape) and dereference
  `(provision_id, division, version)` directly via `version_lookup`.
  Hard-raises if the referent is missing or if the legacy
  `transition_provision_id` field is encountered.
- `tasks/provenance/ccm-output-contract.md` — field listing,
  examples, and prose updated to the new shape.
- The local-only `.tmp/test_edition.json` fixture (gitignored) is
  hand-maintained; anyone running `core/tests/test_load_edition.py`
  needs to migrate their copy by replacing every
  `"transition_provision_id": null` with `"transition_provision_ref": null`.
- Consumer code (`api/search/orchestration.py`) needed no change: it
  already dereferences `version.transition_provision.html`, and the
  model FK was already pinned to `CodeEditionProvisionVersion`.  Once
  the ingestor stores the correctly-pinned version, consumers get
  the in-force-at-link-date transition language for free.

Original card body (filed 2026-05-04 from CCM-side `impl-57`)
preserved below.

## Summary

`ProvisionVersion.transition_provision_id: str | None` becomes
`ProvisionVersion.transition_provision_ref: TransitionProvisionRef | None`,
where `TransitionProvisionRef` carries the full identity:

```python
@dataclass
class TransitionProvisionRef:
    provision_id: str
    division: str       # "" for division-less editions; never None
    version: int
```

## Why

The current bare-string FK is underspecified along two dimensions:

1. **Division.**  In OBC 2012+ the same bare provision id can exist
   in multiple divisions (e.g. `1.2.2.1.` exists in Div A, B, **and**
   C).  No structural invariant pins the division of a transition
   provision relative to the linking provision (a Div B amended
   provision FKs to a Div C transition article, in the OBC 2012
   case).  The bare string is genuinely ambiguous.
2. **Version.**  The transition provision itself can be amended.  A
   bare id doesn't tell a consumer **which version** of the
   transition language to render.

Reading 1 (legally most defensible — version of the transition
provision in force at the linking version's `effective_date`) is the
correct policy; the new shape lets the producer commit to it instead
of delegating to the consumer silently.

See the CCM-side card for the full rationale and the producer-side
fixes (fail-loudly resolver, transition-rule schema additions,
five-step implementation order).

## What changes on the CC side

### Schema

`ccm-output-contract.md` field listing on `ProvisionVersion`:

| before | after |
|---|---|
| `transition_provision_id: string \| null` | `transition_provision_ref: { provision_id: string, division: string, version: integer } \| null` |

### Ingestor

The Django ingestor (`tasks/provenance/2-ingestion.md` covers the
existing pipeline) needs:

1. Read the new `transition_provision_ref` field.  Treat absence of
   the old `transition_provision_id` field as the migration signal
   (every CCM-emitted edition either has both during a coexistence
   window or only the new one once CCM lands the rename).
2. Resolve `(provision_id, division, version)` to a
   `CodeEditionProvisionVersion` row at ingest time.  Failure to
   resolve is a hard error — the new shape is supposed to remove all
   ambiguity, so a missing referent is a real bug, not a soft case.
3. Persist as a FK to that specific
   `CodeEditionProvisionVersion`, replacing whatever the current
   `transition_provision_id` storage is.

### Display

`tasks/provenance/4-display.md` covers the consumer-side rendering.
The change there is mechanical: the dereference target is now a
specific version, not a "current version of the named provision."
The "which transition language applied?" question now has a single
authoritative answer per linking version.

## Coordination with CCM

CCM-side is sequenced so the CCM build always passes (see CCM-side
impl-57 "Implementation order").  CC ingestor only needs to land
**before the next deployment that ingests an edition rebuilt under
the new shape**.

A coexistence window is fine: if CCM lands the rename and CC hasn't
caught up, the next edition rebuild emits the new field and the
ingestor either (a) is updated by then or (b) refuses to ingest until
it is.  No need to keep the old field name in CCM during the window —
just bump the contract version on
`ccm-output-contract.md` so the ingestor can detect a mismatch and
fail loudly rather than silently dropping the field.

## Out of scope

- The old `transition_provision_id` column in any existing CC tables.
  Either alter-and-rename or drop-and-recreate at deploy time, but
  that's a deploy concern, not a contract concern.
- The CCM-side fail-loudly resolver and producer-schema additions —
  those are tracked in CCM impl-57.  This card is purely the
  consumer-side reaction.
