from django.template.loader import render_to_string


def test_search_results_partial_renders_local_pdf_mapping_ui():
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
                    "code_display_name": "National Building Code 2025",
                    "page": 7,
                    "page_end": 7,
                    "initial_page_top": 640.0,
                    "final_page_bottom": 88.0,
                    "pdf_filename": "NBC2025p1.pdf",
                    "html_content": "<p>Preview fallback</p>",
                    "amendments": [],
                }
            ],
        },
    )

    assert 'data-pdf-container data-pdf-expected-filename="NBC2025p1.pdf"' in html
    assert "data-results-accordion" in html
    assert 'data-pdf-page="7"' in html
    assert 'data-pdf-page-end="7"' in html
    assert 'data-pdf-initial-page-top="640.0"' in html
    assert 'data-pdf-final-page-bottom="88.0"' in html
    assert "data-pdf-file-input" in html
    assert "data-pdf-dropzone" in html
    assert "data-pdf-override-mapping" in html
    assert "data-pdf-fallback" in html
    assert "data-pdf-bbox" not in html
    assert "data-result-justification" in html
    assert 'action="/viewer/"' in html


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
                    "code_display_name": "National Building Code 2025",
                    "page": 7,
                    "page_end": 7,
                    "amendments": [],
                },
                {
                    "id": "3.1.1.2",
                    "title": "Closures",
                    "score": 0.75,
                    "code_display_name": "National Building Code 2025",
                    "page": 8,
                    "page_end": 8,
                    "amendments": [],
                },
            ],
        },
    )

    assert 'activeResult: "3.1.1.1"' in html
    assert html.count('@click="activeResult = ') == 2


def test_grouped_result_renders_parent_header_and_children():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "B-3.2.9",
                    "title": "Parent Section",
                    "score": 0.96,
                    "code_display_name": "National Building Code 2025",
                    "group_type": "parent_children",
                    "child_match_count": 5,
                    "child_total_count": 5,
                    "top_scoring_child_id": "B-3.2.9.2",
                    "active_child": {"id": "B-3.2.9.2", "title": "Closures"},
                    "children": [
                        {
                            "id": "B-3.2.9.1",
                            "title": "General",
                            "page": 120,
                            "page_end": 120,
                            "is_match": True,
                            "is_top_scoring": False,
                        },
                        {
                            "id": "B-3.2.9.2",
                            "title": "Closures",
                            "page": 121,
                            "page_end": 121,
                            "is_match": True,
                            "is_top_scoring": True,
                        },
                    ],
                    "amendments": [],
                }
            ],
        },
    )

    assert "B-3.2.9" in html
    assert "B-3.2.9.1" in html
    assert "B-3.2.9.2" in html
    assert "Matching children" in html


def test_grouped_result_marks_top_scoring_child():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "B-3.2.9",
                    "title": "Parent Section",
                    "score": 0.96,
                    "code_display_name": "National Building Code 2025",
                    "group_type": "parent_children",
                    "child_match_count": 2,
                    "child_total_count": 2,
                    "top_scoring_child_id": "B-3.2.9.2",
                    "active_child": {"id": "B-3.2.9.2", "title": "Closures"},
                    "children": [
                        {
                            "id": "B-3.2.9.1",
                            "title": "General",
                            "page": 120,
                            "page_end": 120,
                            "is_match": True,
                            "is_top_scoring": False,
                        },
                        {
                            "id": "B-3.2.9.2",
                            "title": "Closures",
                            "page": 121,
                            "page_end": 121,
                            "is_match": True,
                            "is_top_scoring": True,
                        },
                    ],
                    "amendments": [],
                }
            ],
        },
    )

    assert 'data-top-scoring-child="B-3.2.9.2"' in html
    assert "Top match" in html


def test_mixed_grouped_and_standalone_results_render_together():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {
                    "id": "B-3.2.9",
                    "title": "Parent Section",
                    "score": 0.96,
                    "code_display_name": "National Building Code 2025",
                    "group_type": "parent_children",
                    "child_match_count": 2,
                    "child_total_count": 2,
                    "top_scoring_child_id": "B-3.2.9.2",
                    "active_child": {"id": "B-3.2.9.2", "title": "Closures"},
                    "children": [
                        {
                            "id": "B-3.2.9.1",
                            "title": "General",
                            "page": 120,
                            "page_end": 120,
                            "is_match": True,
                            "is_top_scoring": False,
                        },
                        {
                            "id": "B-3.2.9.2",
                            "title": "Closures",
                            "page": 121,
                            "page_end": 121,
                            "is_match": True,
                            "is_top_scoring": True,
                        },
                    ],
                    "amendments": [],
                },
                {
                    "id": "Table-9.10.3.1.-A",
                    "title": "Standalone Table",
                    "score": 0.8,
                    "code_display_name": "National Building Code 2025",
                    "page": 130,
                    "page_end": 131,
                    "amendments": [],
                },
            ],
        },
    )

    assert "B-3.2.9" in html
    assert "Table-9.10.3.1.-A" in html


def test_transition_compare_card_renders_banner_fields():
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["BCBC_2024"]},
            "results": [
                {
                    "id": "B-3.2.9.",
                    "title": "Fire Separations",
                    "score": 1.0,
                    "code_display_name": "British Columbia Building Code 2024",
                    "result_type": "transition_compare",
                    "transition_context": {
                        "query_date": "2024-06-01",
                        "new_version_effective_date": "2024-03-08",
                        "old_version_last_date": "2025-03-09",
                        "transition_type": "grace_period",
                        "transition_type_display": "grace period",
                        "applicability_text": "Applies during overlap.",
                        "citation_text": "Transition regulation",
                    },
                    "versions": [
                        {
                            "id": "B-3.2.9.",
                            "title": "Fire Separations",
                            "code_display_name": "British Columbia Building Code 2024",
                            "page": 120,
                            "page_end": 122,
                            "transition_context": {"is_primary": True},
                            "amendments": [],
                        },
                        {
                            "id": "B-3.2.9.",
                            "title": "Fire Separations",
                            "code_display_name": "British Columbia Building Code 2018",
                            "page": 98,
                            "page_end": 101,
                            "transition_context": {"is_primary": False},
                            "amendments": [],
                        },
                    ],
                    "amendments": [],
                }
            ],
        },
    )

    assert "grace period" in html.lower()
    assert "Queried date" in html
    assert "Citation" in html


def test_viewer_mode_template_renders_query_context_and_navigation():
    html = render_to_string(
        "viewer_mode.html",
        {
            "result": {
                "id": "B-3.2.9.",
                "title": "Fire Separations",
                "code": "BCBC_2018",
                "code_display_name": "British Columbia Building Code 2018",
                "page": 98,
                "page_end": 101,
                "initial_page_top": 640.0,
                "final_page_bottom": 88.0,
                "pdf_filename": "BCBC2018.pdf",
                "pdf_download_url": "",
                "source_url": "",
                "amendments": [],
                "html_content": None,
                "notes_html": None,
            },
            "query_date": "2024-06-01",
            "query_code": "BCBC_2024",
            "current_code": "BCBC_2018",
            "previous_version": {
                "id": "B-3.2.9.",
                "code": "BCBC_2012",
                "code_display_name": "British Columbia Building Code 2012",
            },
            "next_version": {
                "id": "B-3.2.9.",
                "code": "BCBC_2024",
                "code_display_name": "British Columbia Building Code 2024",
            },
        },
    )

    assert "Viewer mode" in html
    assert "Queried date:" in html
    assert "Query-matching edition:" in html
    assert "Browse context edition" in html
    assert "Previous edition" in html
    assert "Next edition" in html
    assert 'data-pdf-page="98"' in html
