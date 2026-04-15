from django.template.loader import render_to_string


def test_search_results_partial_renders_html_content():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "3.1.1.1",
                    "title": "Fire Safety",
                    "score": 0.93,
                    "code": "NBC_2025",
                    "code_display_name": "National Building Code 2025",
                    "html_content": "<p>Fire safety requirements</p>",
                    "page_images": [],
                    "tables": [],
                }
            ],
        },
    )

    assert "data-results-accordion" in html
    assert "Fire safety requirements" in html
    assert "data-result-justification" in html


def test_search_results_partial_initializes_first_result_as_open_accordion_item():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "3.1.1.1",
                    "title": "Fire Safety",
                    "score": 0.93,
                    "code": "NBC_2025",
                    "code_display_name": "National Building Code 2025",
                },
                {
                    "id": "3.1.1.2",
                    "title": "Closures",
                    "score": 0.75,
                    "code": "NBC_2025",
                    "code_display_name": "National Building Code 2025",
                },
            ],
        },
    )

    assert 'activeResult: "NBC_2025_3.1.1.1"' in html
    assert html.count('@click="activeResult = ') == 2


def test_grouped_result_renders_parent_header_and_children():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "3.2.9",
                    "division": "B",
                    "title": "Parent Section",
                    "score": 0.96,
                    "code_display_name": "National Building Code 2025",
                    "group_type": "parent_children",
                    "child_match_count": 5,
                    "child_total_count": 5,
                    "top_scoring_child_id": "3.2.9.2",
                    "active_child": {"id": "3.2.9.2", "title": "Closures"},
                    "children": [
                        {
                            "id": "3.2.9.1",
                            "title": "General",
                            "is_match": True,
                            "is_top_scoring": False,
                        },
                        {
                            "id": "3.2.9.2",
                            "title": "Closures",
                            "is_match": True,
                            "is_top_scoring": True,
                        },
                    ],
                }
            ],
        },
    )

    assert "3.2.9" in html
    assert "3.2.9.1" in html
    assert "3.2.9.2" in html
    assert "Matching children" in html


def test_grouped_result_marks_top_scoring_child():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "3.2.9",
                    "division": "B",
                    "title": "Parent Section",
                    "score": 0.96,
                    "code_display_name": "National Building Code 2025",
                    "group_type": "parent_children",
                    "child_match_count": 2,
                    "child_total_count": 2,
                    "top_scoring_child_id": "3.2.9.2",
                    "active_child": {"id": "3.2.9.2", "title": "Closures"},
                    "children": [
                        {
                            "id": "3.2.9.1",
                            "title": "General",
                            "is_match": True,
                            "is_top_scoring": False,
                        },
                        {
                            "id": "3.2.9.2",
                            "title": "Closures",
                            "is_match": True,
                            "is_top_scoring": True,
                        },
                    ],
                }
            ],
        },
    )

    assert 'data-top-scoring-child="3.2.9.2"' in html
    assert "Top match" in html


def test_mixed_grouped_and_standalone_results_render_together():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "3.2.9",
                    "division": "B",
                    "title": "Parent Section",
                    "score": 0.96,
                    "code_display_name": "National Building Code 2025",
                    "group_type": "parent_children",
                    "child_match_count": 2,
                    "child_total_count": 2,
                    "top_scoring_child_id": "3.2.9.2",
                    "active_child": {"id": "3.2.9.2", "title": "Closures"},
                    "children": [
                        {
                            "id": "3.2.9.1",
                            "title": "General",
                            "is_match": True,
                            "is_top_scoring": False,
                        },
                        {
                            "id": "3.2.9.2",
                            "title": "Closures",
                            "is_match": True,
                            "is_top_scoring": True,
                        },
                    ],
                },
                {
                    "id": "Table-9.10.3.1.-A",
                    "title": "Standalone Table",
                    "score": 0.8,
                    "code_display_name": "National Building Code 2025",
                },
            ],
        },
    )

    assert "3.2.9" in html
    assert "Table-9.10.3.1.-A" in html


def test_transition_compare_card_renders_transition_text():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["BCBC_2024"]},
            "results": [
                {
                    "id": "3.2.9.",
                    "division": "B",
                    "title": "Fire Separations",
                    "score": 1.0,
                    "code": "BCBC_2024",
                    "code_display_name": "British Columbia Building Code 2024",
                    "result_type": "transition_compare",
                    "transition_context": {
                        "is_primary": True,
                        "transition_text": "<p>The code as it read on 2023-12-31 applies...</p>",
                        "other_edition": "BCBC_2018",
                    },
                    "versions": [
                        {
                            "id": "3.2.9.",
                            "title": "Fire Separations",
                            "code": "BCBC_2024",
                            "code_display_name": "British Columbia Building Code 2024",
                            "html_content": "<p>New version text</p>",
                            "transition_context": {"is_primary": True},
                        },
                        {
                            "id": "3.2.9.",
                            "title": "Fire Separations",
                            "code": "BCBC_2018",
                            "code_display_name": "British Columbia Building Code 2018",
                            "html_content": "<p>Old version text</p>",
                            "transition_context": {"is_primary": False},
                        },
                    ],
                    "has_renderable_content": True,
                }
            ],
        },
    )

    assert "Transition provision" in html
    assert "as it read on 2023-12-31" in html
    assert "showPrevious" in html  # stacked accordion toggle
    assert "In force" in html
    assert "(previous)" in html


def test_provenance_banner_shows_amendment_info():
    """When a result has a clause, the provenance banner shows amendment details."""
    from datetime import date

    class MockRegulation:
        reg_id = "22/98"
        effective_date = date(1998, 4, 6)

    class MockClause:
        regulation = MockRegulation()
        clause_id = "1.(1)"

    class MockBaseReg:
        reg_id = "403/97"

    class MockVersion:
        effective_date = date(1998, 4, 6)

    html = render_to_string(
        "partials/_provenance_banner.html",
        {
            "result": {
                "clause": MockClause(),
                "is_base": False,
                "version": MockVersion(),
                "base_regulation": MockBaseReg(),
                "code_display_name": "Ontario Building Code 1997",
                "division": "Division A",
                "id": "1.1.3.2.",
                "title": "Definitions",
            },
        },
    )

    assert "22/98" in html
    assert "1.(1)" in html
    assert "Amended" in html
    assert "In force" in html
    assert "403/97" in html


def test_provenance_banner_shows_base_regulation():
    """Base provisions show in-force date and 'Original' label."""
    from datetime import date

    class MockBaseReg:
        reg_id = "403/97"

    class MockVersion:
        effective_date = date(1998, 4, 6)

    html = render_to_string(
        "partials/_provenance_banner.html",
        {
            "result": {
                "clause": None,
                "is_base": True,
                "version": MockVersion(),
                "base_regulation": MockBaseReg(),
                "code_display_name": "Ontario Building Code 1997",
                "division": "Division B",
                "id": "3.1.4.7.",
                "title": "Fire Separations",
            },
        },
    )

    assert "In force" in html
    assert "1998-04-06" in html
    assert "403/97" in html
    assert "Original" in html
    assert "base regulation" in html
