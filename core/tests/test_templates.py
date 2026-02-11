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
                    "pdf_filename": "NBC2025p1.pdf",
                    "html_content": "<p>Preview fallback</p>",
                    "amendments": [],
                }
            ],
        },
    )

    assert 'data-pdf-container data-pdf-expected-filename="NBC2025p1.pdf"' in html
    assert "data-pdf-file-input" in html
    assert "data-pdf-dropzone" in html
    assert "data-pdf-override-mapping" in html
    assert "data-pdf-fallback" in html
