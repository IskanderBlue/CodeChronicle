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
