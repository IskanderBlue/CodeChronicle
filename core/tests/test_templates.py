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
