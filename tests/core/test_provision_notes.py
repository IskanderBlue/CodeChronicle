"""Unit tests for the note display-tier grouping (``core.provision_notes``).

Classification (emission site → kind) lives in CCM (impl-139); CodeChronicle
only validates the loaded ``{kind, text[, scope]}`` shape, gates anomaly/noise
kinds at load, and maps the remaining kinds to display tiers.
"""

import pytest

from core.provision_notes import group_notes, normalize_loaded_notes


class TestNormalizeLoadedNotes:
    def test_passes_through_tagged_notes_dropping_blank_text(self) -> None:
        raw = [
            {"kind": "elaws-note", "text": "a legal note"},
            {"kind": "elaws-html-substitution", "text": "  "},  # blank → dropped
        ]
        assert normalize_loaded_notes(raw) == [
            {"kind": "elaws-note", "text": "a legal note"},
        ]

    def test_preserves_optional_scope(self) -> None:
        raw = [{"kind": "elaws-editorial-correction-accepted", "text": "x", "scope": "definition 'building'"}]
        assert normalize_loaded_notes(raw) == [
            {"kind": "elaws-editorial-correction-accepted", "text": "x", "scope": "definition 'building'"},
        ]

    def test_none_and_empty(self) -> None:
        assert normalize_loaded_notes(None) == []
        assert normalize_loaded_notes([]) == []

    def test_anomaly_kind_raises(self) -> None:
        # A ready edition must carry no unreviewed snapshot divergences.
        with pytest.raises(ValueError, match="anomaly kind"):
            normalize_loaded_notes([{"kind": "snapshot-divergence", "text": "diverges at 4.1.3.1.(1)"}])

    def test_drop_kind_silently_dropped(self) -> None:
        # pdf-rejoin is base-extraction noise: not stored, not shown.
        raw = [
            {"kind": "pdf-rejoin", "text": "rejoined hyphenation"},
            {"kind": "elaws-note", "text": "keep me"},
        ]
        assert normalize_loaded_notes(raw) == [{"kind": "elaws-note", "text": "keep me"}]

    def test_legacy_string_shape_raises(self) -> None:
        # A pre-classification artifact (list[str]) must fail loudly, not be
        # silently stored as un-buckettable strings.
        with pytest.raises(ValueError, match="tagged"):
            normalize_loaded_notes(["elaws-note: legacy string"])

    def test_dict_missing_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="tagged"):
            normalize_loaded_notes([{"kind": "elaws-note"}])

    def test_non_list_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            normalize_loaded_notes("elaws-note: x")


class TestGroupNotes:
    def test_buckets_by_tier(self) -> None:
        notes = [
            {"kind": "elaws-note", "text": "a legal note"},
            {"kind": "editor", "text": "curator note"},
            {"kind": "unapplied-directive", "text": "could not apply"},
            {"kind": "revoke-target-missing", "text": "target absent"},
            {"kind": "strike-text-override", "text": "reconciled"},
            {"kind": "elaws-table-header-merge", "text": "merged header"},
            {"kind": "elaws-html-substitution", "text": "snapshot used"},
            {"kind": "elaws-defer-difficult-directive", "text": "formula deferred"},
        ]
        g = group_notes(notes)
        assert len(g["annotation"]) == 2  # elaws-note + editor
        assert len(g["integrity"]) == 2  # unapplied-directive + revoke-target-missing
        assert len(g["record"]) == 2  # strike-text-override + table-header-merge
        assert g["sourced"] is True  # two sourcing kinds collapse to one badge
        assert g["has_any"] is True

    def test_integrity_caption_varies_per_kind(self) -> None:
        g = group_notes([
            {"kind": "unapplied-directive", "text": "x"},
            {"kind": "revoke-target-missing", "text": "y"},
        ])
        captions = {item["caption"] for item in g["integrity"]}
        assert captions == {
            "Record integrity · may be incomplete",
            "Record integrity · structural anomaly",
        }

    def test_record_items_carry_display_labels(self) -> None:
        g = group_notes([
            {"kind": "payload-heading-correction", "text": "x"},
            {"kind": "strike-text-override-title", "text": "y"},
            {"kind": "amend-add-anchor-override", "text": "z"},
        ])
        labels = {item["label"] for item in g["record"]}
        assert labels == {"Heading normalised", "Strike override (title)", "Anchor override"}

    def test_scope_carried_into_grouped_item(self) -> None:
        g = group_notes([{"kind": "elaws-note", "text": "x", "scope": "definition 'building'"}])
        assert g["annotation"][0]["scope"] == "definition 'building'"

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
        g = group_notes([{"kind": "elaws-html-substitution", "text": "snapshot used"}])
        assert g["sourced"] is True
        assert g["has_any"] is True
        assert g["annotation"] == [] and g["record"] == []
