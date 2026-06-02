"""Display-tier grouping for ``CodeEditionProvisionVersion.notes``.

The producer (CCM) emits each version note already classified as
``{"kind": <NoteKind>, "text": str[, "scope": str]}`` — CCM owns the ``kind``
taxonomy because it owns the note-emission sites, tagging each note at
construction (CCM impl-139).  CodeChronicle's job is purely presentational:
map each producer ``kind`` to a display *tier* and render it.

CCM ships **16 consumer-facing kinds** (the Path-A-internal kinds
``elaws-future-amendment`` / ``italics-drift`` / ``presentation-drift`` never
reach us).  Of those 16, two get special handling at the load boundary rather
than a display tier:

``snapshot-divergence``
    "The displayed e-Laws snapshot diverges from the filed text and hasn't been
    reviewed."  A *ready* edition must contain none of these, so we **raise** on
    load rather than render a caveat — the producer should resolve or gate them
    before shipping (a CCM follow-up gates this at assembly; this is the
    backstop).
``pdf-rejoin``
    A base-extraction artifact (line-end hyphenation rejoined).  Not worth
    surfacing *or* storing, so it is **dropped** at load.

Display tiers
-------------
``annotation``  reader-facing note (e-Laws Pnote, editor's note, accepted
                e-Laws correction) — prominent serif band.
``integrity``   the consolidated text may be wrong/incomplete (an unapplied
                directive, or a revoke whose target was absent) — prominent
                red caveat box; caption varies per kind.
``record``      forensic provenance (heading normalisation, gazette↔source
                strike reconciliation, anchor overrides) — default-collapsed.
``sourcing``    bulk "text taken from the e-Laws snapshot" — one badge.
"""

from __future__ import annotations

from typing import TypedDict


class GroupedNotes(TypedDict):
    """Notes fanned into display tiers for ``_version_notes.html``."""

    annotation: list[dict[str, str]]
    integrity: list[dict[str, str]]
    record: list[dict[str, str]]
    sourced: bool
    has_any: bool


# Kinds handled at the load boundary, not by a display tier.
#: A *ready* edition must carry none of these — raise loudly on load.
ANOMALY_KINDS: frozenset[str] = frozenset({"snapshot-divergence"})
#: Base-extraction noise — silently dropped (not stored, not shown).
DROP_KINDS: frozenset[str] = frozenset({"pdf-rejoin"})


# Producer ``kind`` (CCM ``contract/enums.NoteKind``) → display tier.  An
# unknown kind (a new producer kind not yet mapped here) defaults to the
# forensic ``record`` tier, so the note still surfaces rather than vanishing.
_KIND_TIER: dict[str, str] = {
    # reader-facing annotations
    "elaws-note": "annotation",
    "editor": "annotation",
    "elaws-editorial-correction-accepted": "annotation",
    # correctness caveats
    "unapplied-directive": "integrity",
    "revoke-target-missing": "integrity",
    # text sourced from the e-Laws snapshot (collapsed to one badge)
    "elaws-html-substitution": "sourcing",
    "elaws-html-substitution-forced": "sourcing",
    "elaws-defer-difficult-directive": "sourcing",
    # forensic provenance
    "payload-heading-correction": "record",
    "elaws-table-header-merge": "record",
    "strike-text-override": "record",
    "strike-text-override-title": "record",
    "strike-case-insensitive": "record",
    "amend-add-anchor-override": "record",
}

# Short label for the annotation labels and record-notes disclosure chips.
_KIND_LABEL: dict[str, str] = {
    "elaws-note": "Note",
    "editor": "Editor's note",
    "elaws-editorial-correction-accepted": "e-Laws correction",
    "unapplied-directive": "Unapplied amendment",
    "revoke-target-missing": "Revoke target missing",
    "elaws-html-substitution": "Sourcing",
    "elaws-html-substitution-forced": "Sourcing (deferred)",
    "elaws-defer-difficult-directive": "Sourcing (deferred)",
    "payload-heading-correction": "Heading normalised",
    "elaws-table-header-merge": "Table layout",
    "strike-text-override": "Strike override",
    "strike-text-override-title": "Strike override (title)",
    "strike-case-insensitive": "Strike (case-insensitive)",
    "amend-add-anchor-override": "Anchor override",
}

# The integrity tier holds two semantically different warnings, so its red-box
# caption is driven per kind rather than hardcoded in the template.
_INTEGRITY_CAPTION: dict[str, str] = {
    "unapplied-directive": "Record integrity · may be incomplete",
    "revoke-target-missing": "Record integrity · structural anomaly",
}
_DEFAULT_INTEGRITY_CAPTION = "Record integrity · review note"


def normalize_loaded_notes(raw: object) -> list[dict[str, str]]:
    """Validate the producer ``notes`` list at the load boundary.

    The contract is that CCM ships ``[{"kind", "text"[, "scope"]}]`` (tagged at
    construction).  This:

    * fails loudly on a legacy ``list[str]`` artifact or a dict missing
      ``kind``/``text`` (so stale data can't be stored as un-buckettable junk);
    * **raises** on an :data:`ANOMALY_KINDS` note — a ready edition must not
      contain one;
    * **drops** :data:`DROP_KINDS` noise and blank ``text``;
    * preserves an optional ``scope`` qualifier verbatim.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"version notes must be a list, got {type(raw).__name__}")
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or "kind" not in item or "text" not in item:
            raise ValueError(
                "version note is not the tagged {kind, text} contract shape: "
                f"{item!r}. Re-assemble the edition with current CCM (which "
                "tags notes at construction)."
            )
        kind = str(item["kind"])
        text = str(item["text"]).strip()
        if kind in ANOMALY_KINDS:
            raise ValueError(
                f"version note has anomaly kind {kind!r}: {text!r}. A ready "
                "edition must contain no unreviewed snapshot divergences; "
                "resolve or gate it on the CCM side before loading."
            )
        if kind in DROP_KINDS:
            continue
        if not text:
            continue
        note: dict[str, str] = {"kind": kind, "text": text}
        scope = str(item.get("scope", "")).strip()
        if scope:
            note["scope"] = scope
        out.append(note)
    return out


def group_notes(notes: list[dict[str, str]] | None) -> GroupedNotes:
    """Bucket producer-tagged notes into the tiers ``_version_notes.html`` renders.

    Returns ``annotation`` / ``integrity`` / ``record`` lists (each item
    carrying ``kind``, ``text``, a display ``label``, an optional ``scope``,
    and — for integrity — a per-kind ``caption``), a ``sourced`` flag (the bulk
    e-Laws-snapshot notes collapse to one badge), and ``has_any`` so the
    template can skip the whole block in one test.
    """
    annotation: list[dict[str, str]] = []
    integrity: list[dict[str, str]] = []
    record: list[dict[str, str]] = []
    sourced = False
    for note in notes or []:
        kind = note.get("kind", "")
        tier = _KIND_TIER.get(kind, "record")
        item: dict[str, str] = {
            "kind": kind,
            "text": note.get("text", ""),
            "label": _KIND_LABEL.get(kind, "Note"),
        }
        if note.get("scope"):
            item["scope"] = note["scope"]
        if tier == "annotation":
            annotation.append(item)
        elif tier == "integrity":
            item["caption"] = _INTEGRITY_CAPTION.get(kind, _DEFAULT_INTEGRITY_CAPTION)
            integrity.append(item)
        elif tier == "sourcing":
            sourced = True
        else:
            record.append(item)
    return {
        "annotation": annotation,
        "integrity": integrity,
        "record": record,
        "sourced": sourced,
        "has_any": bool(annotation or integrity or record or sourced),
    }
