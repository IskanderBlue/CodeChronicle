from api.search import orchestration


def test_execute_search_returns_primary_results_only_outside_overlap_window(monkeypatch):
    monkeypatch.setattr(
        orchestration, "get_applicable_codes", lambda province, search_date: ["BCBC_2024"]
    )
    monkeypatch.setattr(
        orchestration, "get_active_transitions", lambda applicable_codes, search_date: []
    )
    monkeypatch.setattr(orchestration, "get_map_codes", lambda code_name: ["BCBC"])
    monkeypatch.setattr(
        orchestration,
        "_search_code_maps",
        lambda **kwargs: [
            {"id": "B-3.2.9.", "title": "Fire Separations", "code_edition": kwargs["code_name"]}
        ],
    )

    response = orchestration.execute_search(
        {"date": "2026-01-01", "keywords": ["fire"], "province": "BC"}
    )

    assert all("transition_context" not in result for result in response["results"])


def test_execute_search_adds_overlap_results_inside_transition_window(monkeypatch):
    monkeypatch.setattr(
        orchestration, "get_applicable_codes", lambda province, search_date: ["BCBC_2024"]
    )
    monkeypatch.setattr(
        orchestration,
        "get_active_transitions",
        lambda applicable_codes, search_date: [
            {
                "old_edition": "BCBC_2018",
                "new_edition": "BCBC_2024",
                "overlap_start": "2024-03-08",
                "overlap_end": "2025-03-09",
                "transition_type": "grace_period",
                "applicability_text": "Applies during overlap.",
                "citation_text": "Transition regulation",
            }
        ],
    )
    monkeypatch.setattr(orchestration, "get_map_codes", lambda code_name: [code_name])

    def fake_search_code_maps(**kwargs):
        return [
            {
                "id": "B-3.2.9.",
                "title": "Fire Separations",
                "code_edition": kwargs["code_name"],
                "source_date": "2024-06-01",
            }
        ]

    monkeypatch.setattr(orchestration, "_search_code_maps", fake_search_code_maps)

    response = orchestration.execute_search(
        {"date": "2024-06-01", "keywords": ["fire"], "province": "BC"}
    )

    matched = [result for result in response["results"] if result["id"] == "B-3.2.9."]
    assert len(matched) == 2
    assert {result["code_edition"] for result in matched} == {"BCBC_2024", "BCBC_2018"}


def test_overlap_results_include_transition_context_fields(monkeypatch):
    monkeypatch.setattr(
        orchestration, "get_applicable_codes", lambda province, search_date: ["BCBC_2024"]
    )
    monkeypatch.setattr(
        orchestration,
        "get_active_transitions",
        lambda applicable_codes, search_date: [
            {
                "old_edition": "BCBC_2018",
                "new_edition": "BCBC_2024",
                "overlap_start": "2024-03-08",
                "overlap_end": "2025-03-09",
                "transition_type": "grace_period",
                "applicability_text": "Applies during overlap.",
                "citation_text": "Transition regulation",
            }
        ],
    )
    monkeypatch.setattr(orchestration, "get_map_codes", lambda code_name: [code_name])
    monkeypatch.setattr(
        orchestration,
        "_search_code_maps",
        lambda **kwargs: [
            {
                "id": "B-3.2.9.",
                "title": "Fire Separations",
                "code_edition": kwargs["code_name"],
                "source_date": "2024-06-01",
            }
        ],
    )

    response = orchestration.execute_search(
        {"date": "2024-06-01", "keywords": ["fire"], "province": "BC"}
    )

    matched = [result for result in response["results"] if result["id"] == "B-3.2.9."]
    ctx = matched[0]["transition_context"]
    assert ctx["transition_type"] == "grace_period"
    assert "citation_text" in ctx
    assert "applicability_text" in ctx
