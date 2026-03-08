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


def test_initial_transition_fixture_contains_five_known_records():
    records = load_transitions()

    assert len(records) >= 5
    assert any(record["new_edition"] == "BCBC_2024" for record in records)
    assert any(record["new_edition"] == "QCC_Building_2020" for record in records)
    assert any(record["new_edition"] == "QECB_2020" for record in records)
    assert any(record["new_edition"] == "QPC_2020" for record in records)
    assert any(record["new_edition"] == "QSC_2020" for record in records)


def test_get_active_transitions_returns_overlapping_new_edition_records():
    active = get_active_transitions(["BCBC_2024", "NBC_2025"], date(2024, 6, 1))

    assert len(active) == 1
    assert active[0]["new_edition"] == "BCBC_2024"
