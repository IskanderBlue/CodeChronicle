from datetime import date
from pathlib import Path

import pytest

from config.transitions import get_active_transitions, load_transitions


def test_load_transitions_returns_records_with_required_fields():
    records = load_transitions()

    assert records
    assert set(records[0]).issuperset(
        {
            "old_edition",
            "new_edition",
            "overlap_start",
            "overlap_end",
            "transition_type",
            "applicability_text",
            "citation_text",
        }
    )


def test_load_transitions_rejects_missing_required_field(tmp_path: Path):
    temp_path = tmp_path / "transitions.json"
    temp_path.write_text(
        '[{"old_edition":"A","new_edition":"B","overlap_start":"2025-01-01","overlap_end":"2025-02-01","transition_type":"grace_period","applicability_text":"x"}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_transitions(temp_path)


def test_initial_transition_fixture_contains_known_records():
    records = load_transitions()

    assert len(records) >= 11
    assert any(record["new_edition"] == "BCBC_2024" for record in records)
    assert any(record["new_edition"] == "QCC_2020" for record in records)
    assert any(record["new_edition"] == "QECB_2020" for record in records)
    assert any(record["new_edition"] == "QPC_2020" for record in records)
    assert any(record["new_edition"] == "QSC_2020" for record in records)
    assert any(record["new_edition"] == "OBC_2012_v07" for record in records)
    assert any(record["new_edition"] == "OBC_2012_v20" for record in records)
    assert any(record["new_edition"] == "OBC_2012_v25" for record in records)


def test_get_active_transitions_returns_overlapping_new_edition_records():
    active = get_active_transitions(["BCBC_2024", "NBC_2025"], date(2024, 6, 1))

    assert len(active) == 1
    assert active[0]["new_edition"] == "BCBC_2024"


def test_get_active_transitions_returns_obc_2012_during_overlap():
    active = get_active_transitions(["OBC_2012_v20"], date(2020, 3, 15))

    assert len(active) == 1
    assert active[0]["new_edition"] == "OBC_2012_v20"
    assert active[0]["old_edition"] == "OBC_2012_v19"
    assert active[0]["transition_type"] == "in_stream_project"


def test_get_active_transitions_excludes_obc_2012_outside_overlap():
    active = get_active_transitions(["OBC_2012_v20"], date(2020, 8, 1))

    assert len(active) == 0


def test_provision_scoped_transition_loads_with_optional_fields():
    records = load_transitions()

    provision_records = [r for r in records if r.get("scope") == "provisions"]
    assert len(provision_records) >= 1
    record = provision_records[0]
    assert record["scope"] == "provisions"
    assert isinstance(record["provisions"], list)
    assert len(record["provisions"]) >= 2
    for prov in record["provisions"]:
        assert "new_section_id" in prov
        assert "old_provision_ref" in prov
        assert "as_read_on" in prov


def test_load_transitions_rejects_provisions_scope_without_provisions_array(tmp_path: Path):
    temp_path = tmp_path / "transitions.json"
    temp_path.write_text(
        '[{"old_edition":"A","new_edition":"B","overlap_start":"2025-01-01",'
        '"overlap_end":"2025-02-01","transition_type":"grace_period",'
        '"applicability_text":"x","citation_text":"y","scope":"provisions"}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-empty 'provisions' list"):
        load_transitions(temp_path)


def test_load_transitions_accepts_whole_code_scope_without_provisions(tmp_path: Path):
    temp_path = tmp_path / "transitions.json"
    temp_path.write_text(
        '[{"old_edition":"A","new_edition":"B","overlap_start":"2025-01-01",'
        '"overlap_end":"2025-02-01","transition_type":"grace_period",'
        '"applicability_text":"x","citation_text":"y","scope":"whole_code"}]',
        encoding="utf-8",
    )

    records = load_transitions(temp_path)
    assert len(records) == 1
    assert records[0]["scope"] == "whole_code"
