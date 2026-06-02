from datetime import date

import pytest
from django.template import Context, Template
from django.template.loader import render_to_string

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
)

ELAWS_SAMPLE = (
    '<p class="Psection-e">2.2.1.1. Objectives</p>'
    '<p class="subsection-e"><b>(1)</b> The <i>objectives</i> of this Code '
    'shall be those set out in <i>Table 2.2.1.1.</i></p>'
    '<p class="equation-e">'
    '<img src="/laws/images/en/R19088_e_files/image007.gif" '
    'alt="Image of equation"/></p>'
)


@pytest.fixture
def elaws_version(db):
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012,
        effective_date=date(2012, 1, 1),
    )
    provision = CodeEditionProvision.objects.create(
        edition=edition,
        provision_id="2.2.1.1.",
        level=CodeEditionProvision.Level.ARTICLE,
        division="Division A",
    )
    return CodeEditionProvisionVersion.objects.create(
        provision=provision,
        version=0,
        effective_date=date(2012, 1, 1),
        title="Objectives",
        html=ELAWS_SAMPLE,
    )


@pytest.mark.django_db
def test_version_html_renders_verbatim(elaws_version):
    """``version.html`` reaches the rendered output unchanged.

    Regression guard against accidental sanitisation/rewriting of
    trusted e-Laws markup.  If this test ever fails, look for a new
    template filter, Bleach call, or HTML-mutating function.  See
    feedback_no_html_sanitisation.md.
    """
    template = Template("{{ version.html|safe }}")
    rendered = template.render(Context({"version": elaws_version}))
    assert rendered == ELAWS_SAMPLE


@pytest.mark.django_db
def test_provision_content_partial_preserves_html(elaws_version):
    """The provenance/_provision_content.html partial renders
    ``version.html`` verbatim alongside its surrounding markup."""
    template = Template(
        "{% include 'provenance/_provision_content.html' with version=version %}"
    )
    rendered = template.render(Context({"version": elaws_version}))
    # Distinctive class names and tags must survive.
    assert 'class="Psection-e"' in rendered
    assert 'class="equation-e"' in rendered
    assert '/laws/images/en/R19088_e_files/image007.gif' in rendered
    # And no attribute reordering / quote rewriting.
    assert ELAWS_SAMPLE in rendered


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
    # Each result has a collapse handler (expanded header → null); the expand
    # handlers (collapsed → key) are distinct strings. One collapse per result.
    assert html.count('@click="activeResult = null"') == 2


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
                    "parent_result": {
                        "id": "3.2.9", "title": "Parent Section", "division": "B",
                        "code_edition": "NBC_2025", "is_structural": True,
                    },
                    "children": [
                        {
                            "id": "3.2.9.1",
                            "title": "General",
                            "is_match": True,
                            "is_top_scoring": False,
                            "result": {"id": "3.2.9.1", "html_content": "<p>GENERAL BODY</p>"},
                        },
                        {
                            "id": "3.2.9.2",
                            "title": "Closures",
                            "is_match": True,
                            "is_top_scoring": True,
                            "result": {"id": "3.2.9.2", "html_content": "<p>CLOSURES BODY</p>"},
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
    # Children accordion (each child carries its own result body), the per-child
    # accordion state, and the absorbed parent provision all render.
    assert "GENERAL BODY" in html
    assert "CLOSURES BODY" in html
    assert "activeChild" in html
    assert "Parent provision" in html


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
                            "result": {"id": "3.2.9.1"},
                        },
                        {
                            "id": "3.2.9.2",
                            "title": "Closures",
                            "is_match": True,
                            "is_top_scoring": True,
                            "result": {"id": "3.2.9.2"},
                        },
                    ],
                }
            ],
        },
    )

    # The top-scoring child is the default-open accordion item and wears the
    # "Top match" chip.
    assert "activeChild: '3.2.9.2'" in html
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
    """An amended provision's banner shows the in-force band plus the amendment
    chain: the amending clause (from the chain entry's last_contributing_clause)
    and the base regulation."""
    from datetime import date

    class MockRegulation:
        pk = None  # falsy → template renders plain text, no url reversal
        reg_id = "22/98"
        effective_date = date(1998, 4, 6)

    class MockClause:
        pk = 1
        regulation = MockRegulation()
        clause_id = "1.(1)"

    class MockBaseReg:
        pk = None
        reg_id = "403/97"

    class MockBaseEntry:
        pk = 10
        version = 0
        effective_date = date(1997, 11, 20)
        last_contributing_clause = None  # base entry has no amending clause

    class MockAmendedEntry:
        pk = 11
        version = 1
        effective_date = date(1998, 4, 6)
        last_contributing_clause = MockClause()

    class MockVersion:
        pk = 11  # matches the amended chain entry → highlighted as current
        effective_date = date(1998, 4, 6)
        ineffective_date = None

    html = render_to_string(
        "partials/_provenance_banner.html",
        {
            "result": {
                "clause": MockClause(),
                "is_base": False,
                "version": MockVersion(),
                "base_regulation": MockBaseReg(),
                "amendment_chain": [MockBaseEntry(), MockAmendedEntry()],
                "next_version": None,
                "division": "",  # falsy → skip per-version permalink cross-links
                "code_display_name": "Ontario Building Code 1997",
                "id": "1.1.3.2.",
                "title": "Definitions",
            },
        },
    )

    assert "22/98" in html
    assert "1.(1)" in html
    assert "amended" in html  # band label: "In force · amended"
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
    # IN FORCE band renders the effective date in the design's serif
    # "j F Y" form (not ISO); see api.band / _provenance_banner.html.
    assert "6 April 1998" in html
    assert "403/97" in html
    assert "Original" in html
    assert "base regulation" in html
