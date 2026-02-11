from api.formatters import format_search_results


def test_format_search_results_uses_pdf_filename_and_html_content(monkeypatch):
    monkeypatch.setattr("api.formatters.get_pdf_filename", lambda _code, _map: "NBC2025p1.pdf")
    monkeypatch.setattr("api.formatters.get_source_url", lambda _code: None)
    monkeypatch.setattr("api.formatters.get_code_display_name", lambda _prefix: "National Building Code")
    monkeypatch.setattr("api.formatters.get_amendments_for_section", lambda _sid, _code: [])

    formatted = format_search_results(
        [
            {
                "id": "3.1.1.1",
                "title": "Fire Safety",
                "code_edition": "NBC_2025",
                "map_code": "NBC",
                "page": 7,
                "score": 0.9,
                "html_content": "<p>Sample section HTML.</p>",
            }
        ]
    )

    assert len(formatted) == 1
    first = formatted[0]
    assert first["pdf_filename"] == "NBC2025p1.pdf"
    assert first["html_content"] == "<p>Sample section HTML.</p>"
    assert "text" not in first
    assert "pdf_url" not in first


def test_format_search_results_sorts_by_score(monkeypatch):
    monkeypatch.setattr("api.formatters.get_pdf_filename", lambda _code, _map: "file.pdf")
    monkeypatch.setattr("api.formatters.get_source_url", lambda _code: None)
    monkeypatch.setattr("api.formatters.get_code_display_name", lambda _prefix: "Code")
    monkeypatch.setattr("api.formatters.get_amendments_for_section", lambda _sid, _code: [])

    formatted = format_search_results(
        [
            {"id": "low", "code_edition": "OBC_2024", "map_code": "OBC_Vol1", "score": 0.2},
            {"id": "high", "code_edition": "OBC_2024", "map_code": "OBC_Vol1", "score": 0.8},
        ]
    )

    assert [item["id"] for item in formatted] == ["high", "low"]


def test_format_search_results_omits_pdf_filename_when_not_configured(monkeypatch):
    monkeypatch.setattr("api.formatters.get_pdf_filename", lambda _code, _map: None)
    monkeypatch.setattr("api.formatters.get_source_url", lambda _code: "https://example.com")
    monkeypatch.setattr("api.formatters.get_code_display_name", lambda _prefix: "Ontario Building Code")
    monkeypatch.setattr("api.formatters.get_amendments_for_section", lambda _sid, _code: [])

    formatted = format_search_results(
        [
            {
                "id": "x",
                "code_edition": "OBC_2006_v01",
                "map_code": "OBC_2006_v01",
                "score": 0.1,
            }
        ]
    )

    assert formatted[0]["pdf_filename"] == ""
