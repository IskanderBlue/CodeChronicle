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


def test_provision_scoped_transition_does_not_search_old_edition(monkeypatch):
    """A transition with scope='provisions' should NOT trigger old-edition searching."""
    search_calls = []

    monkeypatch.setattr(
        orchestration, "get_applicable_codes", lambda province, search_date: ["OBC_2012_v09"]
    )
    monkeypatch.setattr(
        orchestration,
        "get_active_transitions",
        lambda applicable_codes, search_date: [
            {
                "old_edition": "OBC_2012_v08",
                "new_edition": "OBC_2012_v09",
                "overlap_start": "2017-01-01",
                "overlap_end": "2017-07-01",
                "transition_type": "in_stream_project",
                "applicability_text": "Certain provisions apply.",
                "citation_text": "O. Reg. 332/12, s. 4.1.3",
                "scope": "provisions",
                "provisions": [
                    {
                        "new_section_id": "B-8.6.2.2.",
                        "old_provision_ref": "Sentence 8.6.2.2.(5)",
                        "as_read_on": "2016-12-31",
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(orchestration, "get_map_codes", lambda code_name: [code_name])

    def fake_search_code_maps(**kwargs):
        search_calls.append(kwargs["code_name"])
        return [
            {
                "id": "8.6.2.2",
                "title": "Fire Safety",
                "code_edition": kwargs["code_name"],
                "source_date": "2017-03-15",
            }
        ]

    monkeypatch.setattr(orchestration, "_search_code_maps", fake_search_code_maps)

    response = orchestration.execute_search(
        {"date": "2017-03-15", "keywords": ["fire"], "province": "ON"}
    )

    # Only the new edition should be searched, NOT the old edition
    assert search_calls == ["OBC_2012_v09"]
    assert len(response["results"]) == 1
    assert response["results"][0]["code_edition"] == "OBC_2012_v09"


def test_whole_code_transition_still_creates_compare_pairs(monkeypatch):
    """Regression: whole_code transitions still get old-edition search and pairing."""
    search_calls = []

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
        search_calls.append(kwargs["code_name"])
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

    # Both editions should be searched
    assert "BCBC_2024" in search_calls
    assert "BCBC_2018" in search_calls
    # Transition pairing should be applied
    paired = [r for r in response["results"] if r.get("transition_context")]
    assert len(paired) == 2
