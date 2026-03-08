"""Transition metadata helpers for overlap-aware edition handling."""

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

TRANSITIONS_PATH = Path(__file__).with_name("transitions.json")
REQUIRED_FIELDS = {
    "old_edition",
    "new_edition",
    "overlap_start",
    "overlap_end",
    "transition_type",
    "applicability_text",
    "citation_text",
}


def load_transitions(path: Path | None = None) -> List[Dict[str, Any]]:
    source_path = path or TRANSITIONS_PATH
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Transition metadata must be a list of records.")

    validated: List[Dict[str, Any]] = []
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise ValueError(f"Transition record at index {index} must be an object.")
        missing = sorted(REQUIRED_FIELDS - set(record))
        if missing:
            raise ValueError(
                f"Transition record at index {index} is missing required fields: {', '.join(missing)}"
            )
        validated.append(record)
    return validated


def get_active_transitions(applicable_codes: List[str], search_date: date) -> List[Dict[str, Any]]:
    active: List[Dict[str, Any]] = []
    for record in load_transitions():
        if record["new_edition"] not in applicable_codes:
            continue
        overlap_start = date.fromisoformat(str(record["overlap_start"]))
        overlap_end = date.fromisoformat(str(record["overlap_end"]))
        if overlap_start <= search_date <= overlap_end:
            active.append(record)
    return active
