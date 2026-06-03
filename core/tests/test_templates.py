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
                    "division": "B",
                    "code_display_name": "National Building Code 2025",
                },
                {
                    "id": "3.1.1.2",
                    "title": "Closures",
                    "score": 0.75,
                    "code": "NBC_2025",
                    "division": "B",
                    "code_display_name": "National Building Code 2025",
                },
            ],
        },
    )

    # Accordion key is scoped by division so same code+id in different
    # divisions can't collide.
    assert 'activeResult: "NBC_2025_3.1.1.1_B"' in html


def test_accordion_keys_distinguish_same_id_across_divisions():
    """Two provisions with identical code+id in different divisions must get
    distinct accordion keys, or selecting one opens both."""
    html = render_to_string(
        "partials/search_results_partial.html",
        {
            "success": True,
            "meta": {"applicable_codes": ["NBC_2025"]},
            "results": [
                {"id": "3.1.1.1", "title": "A-side", "score": 0.9,
                 "code": "NBC_2025", "division": "A",
                 "code_display_name": "National Building Code 2025"},
                {"id": "3.1.1.1", "title": "B-side", "score": 0.8,
                 "code": "NBC_2025", "division": "B",
                 "code_display_name": "National Building Code 2025"},
            ],
        },
    )
    assert "NBC_2025_3.1.1.1_A" in html
    assert "NBC_2025_3.1.1.1_B" in html
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
                        "pair_key": "map:1",
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
    assert "showPrevious" in html  # mobile stacked accordion toggle
    assert "In force" in html
    assert "(previous)" in html
    # Desktop focus-compare wiring: the list column collapses and the center
    # column spans both tracks while `comparePrevious` is set.
    assert "comparePrevious: false" in html  # root accordion state
    assert 'x-show="!comparePrevious"' in html  # results list collapses
    assert "grid-column: 1 / span 2" in html  # center spans list+center width


def test_transition_compare_renders_per_version_band_and_provenance():
    """Regression: a transition card has two in-force windows, so its in-force
    band + provenance must render *per version* — not once from the composite
    (which carries no ``version``/``band``, leaving both blank). Guards the
    bug where only the primary version's editor's note showed."""

    class MockBaseReg:
        pk = None  # falsy → plain text, no url reversal
        reg_id = "350/06"

    class MockVersion:
        pk = 5
        version = 0
        effective_date = date(2012, 1, 1)
        ineffective_date = date(2014, 1, 1)

    class MockVersionNew:
        pk = 6
        version = 0
        effective_date = date(2014, 1, 1)
        ineffective_date = None

    def _version_dict(*, code, edition_name, is_primary, version_obj, eff_label):
        return {
            "id": "1.4.1.2.",
            "title": "Defined Terms",
            "code": code,
            "code_edition": code,
            "code_display_name": edition_name,
            "division": "A",
            "html_content": f"<p>{eff_label} body</p>",
            "version": version_obj,
            "band": None,  # geometry absent is fine; the From/Until dates come from .version
            "base_regulation": MockBaseReg(),
            "amendment_chain": [version_obj],
            "next_version": None,
            "clause": None,
            "copy_text": f"{edition_name} ref",
            "transition_context": {"is_primary": is_primary},
        }

    card = {
        "id": "1.4.1.2.",
        "title": "Defined Terms",
        "code": "OBC_2012",
        "code_display_name": "Ontario Building Code 2012",
        "result_type": "transition_compare",
        "transition_context": {"is_primary": True, "pair_key": "overlap:1.4.1.2.:A"},
        "has_renderable_content": True,
        "versions": [
            _version_dict(code="OBC_2006", edition_name="Ontario Building Code 2006",
                          is_primary=False, version_obj=MockVersion(), eff_label="old"),
            _version_dict(code="OBC_2012", edition_name="Ontario Building Code 2012",
                          is_primary=True, version_obj=MockVersionNew(), eff_label="new"),
        ],
    }

    # ── Mobile / stacked (metadata_in_rail unset): band + provenance inline ──
    html = render_to_string(
        "partials/_result_expanded.html",
        {"result": card, "query_date": "2013-06-01"},
    )
    # In-force band renders per version — both From dates present, not blank.
    assert "1 January 2012" in html  # old version's effective date
    assert "1 January 2014" in html  # new version's effective date (and old's "until")
    # Provenance rail renders per version (two boxes), base reg surfaced.
    assert html.count("Provenance") == 2
    assert "350/06" in html
    # The in-force band is a container (@container) and drops the rail + duration
    # below @xl, so the two narrow compare panes get a compact, equal-width band
    # instead of wrapping asymmetrically (the "fatter band" bug).
    assert "@container" in html
    assert "hidden shrink-0 @xl:block" in html  # Dur. cell gated on container width
    # Body owns its diff/expand x-data (shared_expand=False). Guards the bug where
    # shared_expand=True left showDiff undefined and Alpine hid both content divs
    # at runtime, so neither version showed its text.
    assert "showDiff: true" in html
    assert "old body" in html and "new body" in html

    # ── Master-detail (metadata_in_rail=True): chain/metadata moves to the rail ──
    middle = render_to_string(
        "partials/_result_expanded.html",
        {"result": card, "query_date": "2013-06-01", "metadata_in_rail": True},
    )
    rail = render_to_string("partials/_result_rail.html", {"result": card})
    # Middle keeps the in-force band + bodies, but NOT the provenance rail/justification.
    assert "1 January 2012" in middle and "old body" in middle and "new body" in middle
    assert "Provenance" not in middle
    assert "Why this result" not in middle
    # Desktop is a side-by-side focus-compare driven by the root `comparePrevious`:
    # a toggle button, the previous pane gated on that state, and an inline grid
    # container that splits the (widened) center into two panes.
    assert "Compare with previous version" in middle
    assert 'x-show="comparePrevious"' in middle
    assert "display:grid; grid-template-columns:1fr 1fr" in middle
    # The right rail carries one provenance box per version plus the justification;
    # the previous version's chain is gated on the same compare state.
    assert rail.count("Provenance") == 2
    assert "350/06" in rail
    assert "Why this result" in rail
    assert 'x-show="comparePrevious"' in rail


def test_amendment_chain_collapses_only_in_paired_ui():
    """The amendment chain collapses behind a toggle in the paired-versions UI
    (collapsible_chain) so two stacked chains stay readable, but standard results
    keep it open. The count label excludes the base entry (forloop.first)."""

    class _Reg:
        pk = None  # falsy → plain text, no url reversal
        reg_id = "100/12"

    class _Clause:
        pk = 2
        regulation = _Reg()
        clause_id = "1."

    class _Entry:
        def __init__(self, version, pk):
            self.version = version
            self.pk = pk
            self.effective_date = date(2013, 1, 1)
            self.last_contributing_clause = _Clause()

    base = _Entry(0, 10)
    amended = _Entry(1, 11)
    result = {
        "id": "1.4.1.2.",
        "division": "A",
        "code_edition": "OBC_2012",
        "base_regulation": type("R", (), {"pk": None, "reg_id": "350/06"})(),
        "version": amended,
        "amendment_chain": [base, amended],
        "next_version": None,
    }

    open_rail = render_to_string("partials/_provenance_rail.html", {"result": result})
    collapsed = render_to_string(
        "partials/_provenance_rail.html", {"result": result, "collapsible_chain": True}
    )
    assert "chainOpen" not in open_rail  # standard result: chain always open
    assert "chainOpen" in collapsed  # paired UI: chain collapsible
    assert "Amendment chain (1)" in collapsed  # count excludes the base entry


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
                # Division-less edition (OBC 1997): cross-links must reverse the
                # no-division permalink route, not be suppressed.
                "division": "",
                "code_edition": "OBC_1997",
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
    # The base-version cross-link routes through the no-division permalink.
    assert "/provision/OBC_1997/1.1.3.2./v0/" in html


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


def test_revoked_version_renders_tombstone_warning():
    """The document block surfaces the revoked warning iff version.revoked."""
    from types import SimpleNamespace

    revoked_html = render_to_string(
        "partials/_result_document_block.html",
        {"result": {"version": SimpleNamespace(revoked=True), "clause": None}},
    )
    assert "has been revoked" in revoked_html


def test_non_revoked_version_omits_tombstone_warning():
    from types import SimpleNamespace

    live_html = render_to_string(
        "partials/_result_document_block.html",
        {"result": {"version": SimpleNamespace(revoked=False), "clause": None}},
    )
    assert "has been revoked" not in live_html
