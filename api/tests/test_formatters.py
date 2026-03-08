from api import formatters


def test_format_search_results_emits_span_fields_without_bbox(monkeypatch):
    monkeypatch.setattr(
        formatters, "get_pdf_filename", lambda code_edition, map_code: "NBC2025p1.pdf"
    )
    monkeypatch.setattr(
        formatters, "get_download_url", lambda code_edition: "https://example.com/nbc.pdf"
    )
    monkeypatch.setattr(formatters, "get_source_url", lambda code_edition: "")
    monkeypatch.setattr(
        formatters, "_build_code_display_name", lambda code_edition: "National Building Code 2025"
    )
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results: {})

    formatted = formatters.format_search_results(
        [
            {
                "id": "B-3.2.9.",
                "title": "Fire Separations",
                "code_edition": "NBC_2025",
                "map_code": "NBC",
                "page": 120,
                "page_end": 122,
                "initial_page_top": 640.0,
                "final_page_bottom": 88.0,
                "score": 1.0,
            }
        ]
    )

    item = formatted[0]
    assert item["page"] == 120
    assert item["page_end"] == 122
    assert item["initial_page_top"] == 640.0
    assert item["final_page_bottom"] == 88.0
    assert "bbox" not in item


def test_group_results_collapses_when_more_than_80_percent_of_direct_children_match():
    formatted_results = [
        {
            "id": "B-3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.91,
            "page": 10,
            "page_end": 10,
        },
        {
            "id": "B-3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.96,
            "page": 11,
            "page_end": 11,
        },
        {
            "id": "B-3.2.9.3",
            "title": "Child 3",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.89,
            "page": 12,
            "page_end": 12,
        },
        {
            "id": "B-3.2.9.4",
            "title": "Child 4",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.88,
            "page": 13,
            "page_end": 13,
        },
        {
            "id": "B-3.2.9.5",
            "title": "Child 5",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.87,
            "page": 14,
            "page_end": 14,
        },
    ]
    hierarchy = {
        ("NBC_2025", "NBC", "B-3.2.9"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": f"B-3.2.9.{i}", "title": f"Child {i}", "page": 9 + i, "page_end": 9 + i}
                for i in range(1, 6)
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert len(grouped_results) == 1
    assert grouped_results[0]["group_type"] == "parent_children"
    assert grouped_results[0]["parent_id"] == "B-3.2.9"
    assert len(grouped_results[0]["children"]) == 5
    assert grouped_results[0]["top_scoring_child_id"] == "B-3.2.9.2"


def test_group_results_does_not_group_at_or_below_80_percent():
    formatted_results = [
        {
            "id": "B-3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.91,
        },
        {
            "id": "B-3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.88,
        },
        {
            "id": "B-3.2.9.3",
            "title": "Child 3",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.84,
        },
    ]
    hierarchy = {
        ("NBC_2025", "NBC", "B-3.2.9"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": f"B-3.2.9.{i}", "title": f"Child {i}", "page": i, "page_end": i}
                for i in range(1, 5)
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert all(item.get("group_type") != "parent_children" for item in grouped_results)
    assert len(grouped_results) == 3


def test_group_results_uses_children_not_pages():
    formatted_results = [
        {
            "id": "B-3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.91,
            "page": 10,
            "page_end": 12,
        },
        {
            "id": "B-3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "B-3.2.9",
            "score": 0.88,
            "page": 13,
            "page_end": 13,
        },
    ]
    hierarchy = {
        ("NBC_2025", "NBC", "B-3.2.9"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": "B-3.2.9.1", "title": "Child 1", "page": 10, "page_end": 12},
                {"node_id": "B-3.2.9.2", "title": "Child 2", "page": 13, "page_end": 13},
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert grouped_results[0]["child_match_count"] == 2
    assert grouped_results[0]["child_total_count"] == 2


def test_group_results_keeps_single_child_match_standalone():
    formatted_results = [
        {
            "id": "Table-9.10.3.1.-A",
            "title": "Standalone Table",
            "code": "NBC_2025",
            "map_code": "NBC",
            "parent_id": "Table-9.10.3.1",
            "score": 0.91,
        }
    ]
    hierarchy = {
        ("NBC_2025", "NBC", "Table-9.10.3.1"): {
            "parent_title": "Standalone Parent",
            "children": [
                {
                    "node_id": "Table-9.10.3.1.-A",
                    "title": "Standalone Table",
                    "page": 18,
                    "page_end": 18,
                },
                {
                    "node_id": "Table-9.10.3.1.-B",
                    "title": "Context Table",
                    "page": 19,
                    "page_end": 19,
                },
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert len(grouped_results) == 1
    assert grouped_results[0].get("group_type") is None
    assert grouped_results[0]["id"] == "Table-9.10.3.1.-A"


def test_formatter_merges_transition_pair_into_single_compare_result(monkeypatch):
    monkeypatch.setattr(
        formatters,
        "get_pdf_filename",
        lambda code_edition, map_code: f"{code_edition}-{map_code}.pdf",
    )
    monkeypatch.setattr(formatters, "get_download_url", lambda code_edition: "")
    monkeypatch.setattr(formatters, "get_source_url", lambda code_edition: "")
    monkeypatch.setattr(formatters, "_build_code_display_name", lambda code_edition: code_edition)
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results: {})

    formatted_results = formatters.format_search_results(
        [
            {
                "id": "B-3.2.9.",
                "title": "Fire Separations",
                "code_edition": "BCBC_2024",
                "map_code": "BCBC2024",
                "page": 120,
                "page_end": 122,
                "score": 1.0,
                "transition_context": {
                    "old_edition": "BCBC_2018",
                    "new_edition": "BCBC_2024",
                    "query_date": "2024-06-01",
                    "new_version_effective_date": "2024-03-08",
                    "old_version_last_date": "2025-03-09",
                    "transition_type": "grace_period",
                    "transition_type_display": "grace period",
                    "applicability_text": "Applies during overlap.",
                    "citation_text": "Transition regulation",
                    "is_primary": True,
                },
            },
            {
                "id": "B-3.2.9.",
                "title": "Fire Separations",
                "code_edition": "BCBC_2018",
                "map_code": "BCBC2018",
                "page": 98,
                "page_end": 101,
                "score": 0.94,
                "transition_context": {
                    "old_edition": "BCBC_2018",
                    "new_edition": "BCBC_2024",
                    "query_date": "2024-06-01",
                    "new_version_effective_date": "2024-03-08",
                    "old_version_last_date": "2025-03-09",
                    "transition_type": "grace_period",
                    "transition_type_display": "grace period",
                    "applicability_text": "Applies during overlap.",
                    "citation_text": "Transition regulation",
                    "is_primary": False,
                },
            },
        ]
    )

    assert len(formatted_results) == 1
    assert formatted_results[0]["result_type"] == "transition_compare"
    assert len(formatted_results[0]["versions"]) == 2
