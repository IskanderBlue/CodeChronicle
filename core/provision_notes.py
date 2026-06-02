"""Display-tier grouping for ``CodeEditionProvisionVersion.notes``.

The producer (CCM) emits each version note already classified as
``{"kind": <NoteKind>, "text": str}`` — CCM owns the ``kind`` taxonomy because
it owns the note-emission sites (see the CCM contract,
``tasks/provenance/ccm-output-contract.md``).  CodeChronicle's job is purely
presentational: map each producer ``kind`` to a display *tier* and render it.

Tiers
-----
``annotation``  reader-facing e-Laws consolidation note (prominent, serif).
``integrity``   an amendment the producer could NOT apply — the consolidated
                text may be incomplete; a correctness caveat.
``record``      forensic provenance (editorial, reconciliation, method,
                presentation) — default-collapsed.
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


# Producer ``kind`` (CCM ``contract/enums.NoteKind``) → display tier.  An
# unknown kind (a new producer kind not yet mapped here) defaults to the
# forensic ``record`` tier, so the note still surfaces rather than vanishing.
_KIND_TIER: dict[str, str] = {
    "annotation": "annotation",
    "unapplied": "integrity",
    "editorial": "record",
    "reconciliation": "record",
    "method": "record",
    "presentation": "record",
    "sourcing": "sourcing",
}

# Short label for the record-notes disclosure chips.
_KIND_LABEL: dict[str, str] = {
    "annotation": "Note",
    "unapplied": "Unapplied amendment",
    "editorial": "Editorial",
    "reconciliation": "Source reconciliation",
    "method": "Consolidation method",
    "presentation": "Presentation",
    "sourcing": "Sourcing",
}


def normalize_loaded_notes(raw: object) -> list[dict[str, str]]:
    """Validate the producer ``notes`` list at the load boundary.

    The contract is that CCM ships ``[{"kind", "text"}]`` (classified at its
    write boundary).  This keeps the stored data clean — dropping blank
    ``text`` — and fails loudly on a legacy ``list[str]`` artifact rather than
    silently storing un-tagged strings the renderer can't bucket.
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
                "classifies notes at write) or re-run its retag pass."
            )
        text = str(item["text"]).strip()
        if not text:
            continue
        out.append({"kind": str(item["kind"]), "text": text})
    return out


def group_notes(notes: list[dict[str, str]] | None) -> GroupedNotes:
    """Bucket producer-tagged notes into the tiers ``_version_notes.html`` renders.

    Returns ``annotation`` / ``integrity`` / ``record`` lists (each item
    carrying ``kind``, ``text`` and a display ``label``), a ``sourced`` flag
    (the bulk e-Laws-snapshot notes collapse to one badge), and ``has_any`` so
    the template can skip the whole block in one test.
    """
    annotation: list[dict[str, str]] = []
    integrity: list[dict[str, str]] = []
    record: list[dict[str, str]] = []
    sourced = False
    for note in notes or []:
        kind = note.get("kind", "method")
        tier = _KIND_TIER.get(kind, "record")
        item = {
            "kind": kind,
            "text": note.get("text", ""),
            "label": _KIND_LABEL.get(kind, "Note"),
        }
        if tier == "annotation":
            annotation.append(item)
        elif tier == "integrity":
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
