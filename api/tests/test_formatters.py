from api import formatters


def test_format_search_results_emits_span_fields_without_bbox(monkeypatch):
    monkeypatch.setattr(
        formatters, "_build_code_display_name", lambda code_edition: "National Building Code 2025"
    )
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results: {})

    formatted = formatters.format_search_results(
        [
            {
                "id": "3.2.9.",
                "title": "Fire Separations",
                "code_edition": "NBC_2025",
                "page": 120,
                "page_end": 122,
                "initial_page_top": 640.0,
                "final_page_bottom": 88.0,
                "score": 1.0,
                "division": "B",
            }
        ]
    )

    item = formatted[0]
    assert item["page"] is None  # _format_single_result no longer copies page fields
    assert "bbox" not in item


def test_group_results_collapses_when_more_than_80_percent_of_direct_children_match():
    formatted_results = [
        {
            "id": "3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.91,
            "page": 10,
            "page_end": 10,
        },
        {
            "id": "3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.96,
            "page": 11,
            "page_end": 11,
        },
        {
            "id": "3.2.9.3",
            "title": "Child 3",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.89,
            "page": 12,
            "page_end": 12,
        },
        {
            "id": "3.2.9.4",
            "title": "Child 4",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.88,
            "page": 13,
            "page_end": 13,
        },
        {
            "id": "3.2.9.5",
            "title": "Child 5",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.87,
            "page": 14,
            "page_end": 14,
        },
    ]
    hierarchy = {
        ("NBC_2025", "3.2.9", "B"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": f"3.2.9.{i}", "title": f"Child {i}", "page": 9 + i, "page_end": 9 + i}
                for i in range(1, 6)
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert len(grouped_results) == 1
    assert grouped_results[0]["group_type"] == "parent_children"
    assert grouped_results[0]["parent_id"] == "3.2.9"
    assert len(grouped_results[0]["children"]) == 5
    assert grouped_results[0]["top_scoring_child_id"] == "3.2.9.2"


def test_group_results_does_not_group_at_or_below_80_percent():
    formatted_results = [
        {
            "id": "3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.91,
        },
        {
            "id": "3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.88,
        },
        {
            "id": "3.2.9.3",
            "title": "Child 3",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.84,
        },
    ]
    hierarchy = {
        ("NBC_2025", "3.2.9", "B"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": f"3.2.9.{i}", "title": f"Child {i}", "page": i, "page_end": i}
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
            "id": "3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.91,
            "page": 10,
            "page_end": 12,
        },
        {
            "id": "3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.88,
            "page": 13,
            "page_end": 13,
        },
    ]
    hierarchy = {
        ("NBC_2025", "3.2.9", "B"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": "3.2.9.1", "title": "Child 1", "page": 10, "page_end": 12},
                {"node_id": "3.2.9.2", "title": "Child 2", "page": 13, "page_end": 13},
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
            "parent_id": "Table-9.10.3.1",
            "division": "",
            "score": 0.91,
        }
    ]
    hierarchy = {
        ("NBC_2025", "Table-9.10.3.1", ""): {
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
    monkeypatch.setattr(formatters, "_build_code_display_name", lambda code_edition: code_edition)
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results: {})

    formatted_results = formatters.format_search_results(
        [
            {
                "id": "3.2.9.",
                "title": "Fire Separations",
                "code_edition": "BCBC_2024",
                "page": 120,
                "page_end": 122,
                "score": 1.0,
                "division": "B",
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
                "id": "3.2.9.",
                "title": "Fire Separations",
                "code_edition": "BCBC_2018",
                "page": 98,
                "page_end": 101,
                "score": 0.94,
                "division": "B",
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
    assert formatted_results[0]["code"], "merged transition-compare must have a code field"
    assert len(formatted_results[0]["versions"]) == 2
    # R1: old edition first, new edition second
    assert formatted_results[0]["versions"][0]["code"] == "BCBC_2018"
    assert formatted_results[0]["versions"][1]["code"] == "BCBC_2024"


def test_diff_html_content_marks_unchanged_and_changed():
    old_html = "<p>The fire safety requirements apply to all buildings.</p>"
    new_html = "<p>The fire safety standards apply to most buildings.</p>"
    old_diff, new_diff = formatters._diff_html_content(old_html, new_html)
    assert old_diff is not None
    assert new_diff is not None
    # Both panes: unchanged text is lowlighted
    assert 'class="diff-old-unchanged"' in old_diff
    assert 'class="diff-new-unchanged"' in new_diff
    # Changed text appears unwrapped (no highlight class)
    assert "requirements" in old_diff
    assert "standards" in new_diff
    assert "diff-old-changed" not in old_diff
    assert "diff-new-changed" not in new_diff


def test_diff_html_content_preserves_html_tags():
    old_html = "<p><strong>Fire</strong> safety requirements apply.</p>"
    new_html = "<p><strong>Fire</strong> safety standards apply.</p>"
    old_diff, new_diff = formatters._diff_html_content(old_html, new_html)
    assert old_diff is not None
    assert new_diff is not None
    # Original HTML tags should be preserved in the diff output
    assert "<p>" in old_diff
    assert "<strong>" in old_diff
    assert "</strong>" in old_diff
    assert "</p>" in old_diff
    assert "<p>" in new_diff
    assert "<strong>" in new_diff


def test_diff_html_content_preserves_original_whitespace():
    # "Act, 1997," should NOT get a space before the comma
    old_html = "<p>the Fire Protection and Prevention Act, 1997,</p>"
    new_html = "<p>the Fire Protection and Prevention Act, 1997,</p>"
    old_diff, new_diff = formatters._diff_html_content(old_html, new_html)
    assert "1997 ," not in old_diff  # no spurious space before comma
    assert "1997," in old_diff
    # "onlydwelling" should stay unseparated if that's the original
    old_html2 = "<p>onlydwelling units</p>"
    new_html2 = "<p>onlydwelling units</p>"
    old_diff2, _ = formatters._diff_html_content(old_html2, new_html2)
    assert "onlydwelling" in old_diff2  # no space inserted


def test_diff_html_content_returns_none_when_input_empty():
    assert formatters._diff_html_content(None, "<p>text</p>") == (None, None)
    assert formatters._diff_html_content("<p>text</p>", None) == (None, None)
    assert formatters._diff_html_content("", "<p>text</p>") == (None, None)
    assert formatters._diff_html_content(None, None) == (None, None)


def test_has_renderable_content_false_when_no_content():
    result = formatters.merge_transition_compare_results(
        [
            {
                "id": "3.1",
                "code": "OBC_2024",
                "score": 0.9,
                "transition_context": {
                    "old_edition": "OBC_2012",
                    "new_edition": "OBC_2024",
                    "is_primary": True,
                },
            },
            {
                "id": "3.1",
                "code": "OBC_2012",
                "score": 0.8,
                "transition_context": {
                    "old_edition": "OBC_2012",
                    "new_edition": "OBC_2024",
                    "is_primary": False,
                },
            },
        ]
    )
    merged = [r for r in result if r.get("result_type") == "transition_compare"]
    assert len(merged) == 1
    assert merged[0]["has_renderable_content"] is False


def test_has_renderable_content_true_when_one_version_has_content():
    result = formatters.merge_transition_compare_results(
        [
            {
                "id": "3.1",
                "code": "OBC_2024",
                "score": 0.9,
                "html_content": "<p>Some text</p>",
                "transition_context": {
                    "old_edition": "OBC_2012",
                    "new_edition": "OBC_2024",
                    "is_primary": True,
                },
            },
            {
                "id": "3.1",
                "code": "OBC_2012",
                "score": 0.8,
                "transition_context": {
                    "old_edition": "OBC_2012",
                    "new_edition": "OBC_2024",
                    "is_primary": False,
                },
            },
        ]
    )
    merged = [r for r in result if r.get("result_type") == "transition_compare"]
    assert len(merged) == 1
    assert merged[0]["has_renderable_content"] is True


def test_transition_context_passes_through_formatting(monkeypatch):
    monkeypatch.setattr(
        formatters, "_build_code_display_name",
        lambda code_edition: "Ontario Building Code 2012 v09",
    )
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results: {})

    transition_context = {
        "is_primary": True,
        "transition_text": "Transition regulation text",
        "other_edition": "OBC_2012_v08",
    }

    formatted = formatters.format_search_results(
        [
            {
                "id": "8.6.2.2",
                "title": "Fire Safety",
                "code_edition": "OBC_2012_v09",
                "score": 0.95,
                "transition_context": transition_context,
            }
        ]
    )

    assert len(formatted) == 1
    item = formatted[0]
    assert item["transition_context"] is not None
    assert item["transition_context"]["is_primary"] is True
    assert item["transition_context"]["other_edition"] == "OBC_2012_v08"
    assert item["transition_context"]["transition_text"] == "Transition regulation text"


def test_nest_child_results_under_parent():
    results = [
        {"id": "3.2", "parent_id": None, "score": 0.9, "code": "OBC_2024", "title": "Parent",
         "division": "B"},
        {"id": "3.2.1", "parent_id": "3.2", "score": 0.85, "code": "OBC_2024", "title": "Child A",
         "division": "B"},
        {"id": "3.2.2", "parent_id": "3.2", "score": 0.80, "code": "OBC_2024", "title": "Child B",
         "division": "B"},
    ]
    nested = formatters._nest_child_results(results)
    assert len(nested) == 1
    parent = nested[0]
    assert parent["id"] == "3.2"
    assert parent["group_type"] == "parent_children"
    assert len(parent["children"]) == 2
    assert parent["children"][0]["id"] == "3.2.1"
    assert parent["children"][1]["id"] == "3.2.2"
    assert all(c["is_match"] for c in parent["children"])
    assert parent["top_scoring_child_id"] == "3.2.1"
    assert parent["child_match_count"] == 2
    assert parent["child_total_count"] == 2


def test_nest_child_results_cross_edition_no_collision():
    """Same section IDs across editions must not collide or drop results."""
    results = [
        # OBC parent + children
        {"id": "3.2", "parent_id": None, "score": 0.9, "code": "OBC_2024",
         "division": "B", "title": "OBC Parent"},
        {"id": "3.2.1", "parent_id": "3.2", "score": 0.85, "code": "OBC_2024",
         "division": "B", "title": "OBC Child A"},
        {"id": "3.2.2", "parent_id": "3.2", "score": 0.80, "code": "OBC_2024",
         "division": "B", "title": "OBC Child B"},
        # NBC parent + children with identical node IDs
        {"id": "3.2", "parent_id": None, "score": 0.7, "code": "NBC_2020",
         "division": "B", "title": "NBC Parent"},
        {"id": "3.2.1", "parent_id": "3.2", "score": 0.65, "code": "NBC_2020",
         "division": "B", "title": "NBC Child A"},
        {"id": "3.2.2", "parent_id": "3.2", "score": 0.60, "code": "NBC_2020",
         "division": "B", "title": "NBC Child B"},
    ]
    nested = formatters._nest_child_results(results)
    # Both editions should produce their own grouped parent card
    assert len(nested) == 2
    obc = [r for r in nested if r.get("code") == "OBC_2024"][0]
    nbc = [r for r in nested if r.get("code") == "NBC_2020"][0]
    assert obc["group_type"] == "parent_children"
    assert nbc["group_type"] == "parent_children"
    assert len(obc["children"]) == 2
    assert len(nbc["children"]) == 2
    # Children titles should be edition-specific (not overwritten)
    assert obc["children"][0]["title"].startswith("OBC")
    assert nbc["children"][0]["title"].startswith("NBC")
