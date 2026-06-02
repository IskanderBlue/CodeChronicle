"""Unit tests for the note display-tier grouping (``core.provision_notes``).

Classification (string prefix → kind) now lives in CCM; CodeChronicle only
validates the loaded ``{kind, text}`` shape and maps kinds to display tiers.
"""

import pytest

from core.provision_notes import group_notes, normalize_loaded_notes


class TestNormalizeLoadedNotes:
    def test_passes_through_tagged_notes_dropping_blank_text(self) -> None:
        raw = [
            {"kind": "annotation", "text": "a legal note"},
            {"kind": "sourcing", "text": "  "},  # blank → dropped
        ]
        assert normalize_loaded_notes(raw) == [
            {"kind": "annotation", "text": "a legal note"},
        ]

    def test_none_and_empty(self) -> None:
        assert normalize_loaded_notes(None) == []
        assert normalize_loaded_notes([]) == []

    def test_legacy_string_shape_raises(self) -> None:
        # A pre-classification artifact (list[str]) must fail loudly, not be
        # silently stored as un-buckettable strings.
        with pytest.raises(ValueError, match="tagged"):
            normalize_loaded_notes(["elaws-note: legacy string"])

    def test_dict_missing_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="tagged"):
            normalize_loaded_notes([{"kind": "annotation"}])

    def test_non_list_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            normalize_loaded_notes("elaws-note: x")


class TestGroupNotes:
    def test_buckets_by_tier(self) -> None:
        notes = [
            {"kind": "annotation", "text": "a legal note"},
            {"kind": "unapplied", "text": "could not apply"},
            {"kind": "editorial", "text": "trailing dot added"},
            {"kind": "reconciliation", "text": "reconciled"},
            {"kind": "presentation", "text": "italics drift"},
            {"kind": "sourcing", "text": "snapshot used"},
            {"kind": "sourcing", "text": "snapshot used again"},
        ]
        g = group_notes(notes)
        assert len(g["annotation"]) == 1
        assert len(g["integrity"]) == 1
        assert len(g["record"]) == 3  # editorial + reconciliation + presentation
        assert g["sourced"] is True  # collapsed, not counted
        assert g["has_any"] is True

    def test_record_items_carry_display_labels(self) -> None:
        g = group_notes([
            {"kind": "editorial", "text": "x"},
            {"kind": "reconciliation", "text": "y"},
            {"kind": "presentation", "text": "z"},
        ])
        labels = {item["label"] for item in g["record"]}
        assert labels == {"Editorial", "Source reconciliation", "Presentation"}

    def test_unknown_kind_defaults_to_record(self) -> None:
        # A future CCM kind not yet mapped still surfaces (forensic tier).
        g = group_notes([{"kind": "brand-new-kind", "text": "x"}])
        assert len(g["record"]) == 1
        assert g["record"][0]["label"] == "Note"

    def test_empty_has_nothing(self) -> None:
        g = group_notes([])
        assert g["has_any"] is False
        assert g["sourced"] is False

    def test_sourcing_only_still_has_any(self) -> None:
        g = group_notes([{"kind": "sourcing", "text": "snapshot used"}])
        assert g["sourced"] is True
        assert g["has_any"] is True
        assert g["annotation"] == [] and g["record"] == []
