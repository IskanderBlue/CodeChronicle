"""Within-edition cross-references: anchoring, inline linking, cite lists.

The load-time anchoring is the fragile half (CCM ships no position, only the
citation's text), so most of these pin the properties measured against the real
OBC payloads: surfaces nest, matches never land inside markup, and ~1% of
records name text the emitted html doesn't literally contain.
"""

from datetime import date

import pytest

from api.formatters import highlight_terms
from core.cross_refs import (
    annotate_tables,
    assign_occurrences,
    cited_by,
    cited_by_map,
    cites,
    linkify,
    locate_surfaces,
    target_on,
)
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionCrossReference,
    ProvisionCrossReferenceAlternate,
    ProvisionVersionTable,
)
from core.permalinks import provision_permalink_url

CODE_NAME = "OBC_2006"


def _record(surface: str, **kwargs) -> ProvisionCrossReference:
    """An unsaved record — enough for the pure anchoring/render functions."""
    return ProvisionCrossReference(surface_text=surface, **kwargs)


# ── Anchoring ────────────────────────────────────────────────────────────

class TestLocateSurfaces:
    def test_finds_each_occurrence_in_document_order(self) -> None:
        html = "<p>See 3.2.5. and later 3.2.5. again</p>"
        assert locate_surfaces(html, ["3.2.5."])["3.2.5."] == [(7, 13), (24, 30)]

    def test_ignores_matches_inside_markup(self) -> None:
        """A surface that also appears in an attribute must not anchor there.

        Measured: no citation in OBC 1997/2006/2012 lands inside a tag — this
        keeps that true by construction rather than by luck.
        """
        html = '<p id="3.2.5.">See 3.2.5.</p>'
        assert locate_surfaces(html, ["3.2.5."])["3.2.5."] == [(19, 25)]

    def test_longer_surface_claims_its_text_first(self) -> None:
        """The nesting case: OBC 2006 A|1.4.1.2. v5 cites both forms."""
        html = "<p>per Sentence 3.7.4.3.(5) and Sentence 3.7.4.3. generally</p>"
        found = locate_surfaces(
            html, ["Sentence 3.7.4.3.", "Sentence 3.7.4.3.(5)"]
        )
        assert len(found["Sentence 3.7.4.3.(5)"]) == 1
        # The short form has two literal occurrences but only one that the
        # long form didn't claim.
        assert len(found["Sentence 3.7.4.3."]) == 1
        (short_start, _), = found["Sentence 3.7.4.3."]
        (long_start, _), = found["Sentence 3.7.4.3.(5)"]
        assert short_start > long_start


class TestAssignOccurrences:
    def test_records_take_occurrences_in_order(self) -> None:
        html = "<p>3.2.5. then 3.2.5.</p>"
        first, second = _record("3.2.5."), _record("3.2.5.")
        assert assign_occurrences(html, [first, second]) == 0
        assert (first.occurrence, second.occurrence) == (0, 1)

    def test_unlocatable_surface_stays_unanchored(self) -> None:
        """The block-straddle case: CCM matched on normalised text.

        OBC 1997 2.1.1.7. cites "Section 9.41." where the html reads
        ``…Section</p><p>9.41.…``.  150 records corpus-wide; they must not
        raise, and must not anchor onto something else.
        """
        html = "<p>Except as provided in Section</p><p>9.41. and Part 11</p>"
        record = _record("Section 9.41.")
        assert assign_occurrences(html, [record]) == 1
        assert record.occurrence is None

    def test_surplus_record_is_left_unanchored(self) -> None:
        """More records than occurrences (18 in OBC 1997, 2 in 2012)."""
        html = "<p>Table 4.1.8.6. once</p>"
        records = [_record("Table 4.1.8.6.") for _ in range(3)]
        assert assign_occurrences(html, records) == 2
        assert [r.occurrence for r in records] == [0, None, None]


# ── Target selection ─────────────────────────────────────────────────────

class TestTargetOn:
    TARGETS = [
        {"version": 0, "effective_date": "2006-12-31", "ineffective_date": "2010-01-01"},
        {"version": 1, "effective_date": "2010-01-01", "ineffective_date": "2014-01-01"},
    ]

    @staticmethod
    def _version_on(record, on) -> int:
        target = target_on(record, on)
        assert target is not None
        return target["version"]

    def test_picks_the_slice_in_force_on_the_day(self) -> None:
        record = _record("3.2.5.", targets=self.TARGETS)
        assert self._version_on(record, date(2008, 6, 1)) == 0
        assert self._version_on(record, date(2011, 6, 1)) == 1

    def test_boundary_day_belongs_to_the_incoming_slice(self) -> None:
        """Windows are half-open, as everywhere else in the corpus."""
        record = _record("3.2.5.", targets=self.TARGETS)
        assert self._version_on(record, date(2010, 1, 1)) == 1

    def test_no_date_falls_back_to_the_last_slice(self) -> None:
        record = _record("3.2.5.", targets=self.TARGETS)
        assert self._version_on(record, None) == 1

    def test_no_targets_is_none(self) -> None:
        assert target_on(_record("3.2.5.", targets=[]), date(2008, 1, 1)) is None


# ── Rendering ────────────────────────────────────────────────────────────

@pytest.fixture
def edition(db) -> CodeEdition:
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    return CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006,
        effective_date=date(2006, 12, 31), ineffective_date=date(2014, 1, 1),
    )


def _provision(
    edition: CodeEdition, provision_id: str, division: str = "B"
) -> CodeEditionProvision:
    return CodeEditionProvision.objects.create(
        edition=edition, provision_id=provision_id, level="article", division=division,
    )


def _version(
    provision: CodeEditionProvision,
    version: int = 0,
    *,
    html: str = "",
    effective: date = date(2006, 12, 31),
    ineffective: date | None = date(2014, 1, 1),
) -> CodeEditionProvisionVersion:
    return CodeEditionProvisionVersion.objects.create(
        provision=provision, version=version, html=html,
        effective_date=effective, ineffective_date=ineffective,
    )


@pytest.mark.django_db
class TestLinkify:
    def test_single_target_links_the_surface_text(self, edition: CodeEdition) -> None:
        target = _provision(edition, "3.2.5.")
        html = "<p>as required by Subsection 3.2.5. of this Code</p>"
        record = _record(
            "Subsection 3.2.5.", to_provision=target, occurrence=0,
            targets=[{"version": 0, "effective_date": "2006-12-31",
                      "ineffective_date": "2014-01-01"}],
        )
        out = linkify(html, [record], CODE_NAME, on_date=date(2008, 1, 1))
        assert 'class="cross-ref ui-cite"' in out
        assert ">Subsection 3.2.5.</a>" in out
        assert "/OBC_2006/" in out
        # Everything outside the citation is untouched.
        assert out.startswith("<p>as required by ")
        assert out.endswith(" of this Code</p>")

    def test_dated_mode_picks_the_version_in_force(self, edition: CodeEdition) -> None:
        target = _provision(edition, "3.2.5.")
        record = _record(
            "3.2.5.", to_provision=target, occurrence=0,
            targets=[
                {"version": 0, "effective_date": "2006-12-31",
                 "ineffective_date": "2010-01-01"},
                {"version": 2, "effective_date": "2010-01-01",
                 "ineffective_date": "2014-01-01"},
            ],
        )
        early = linkify("<p>3.2.5.</p>", [record], CODE_NAME, on_date=date(2008, 1, 1))
        late = linkify("<p>3.2.5.</p>", [record], CODE_NAME, on_date=date(2012, 1, 1))
        assert early.count("<a ") == 1 and late.count("<a ") == 1
        assert early != late

    def test_fan_out_renders_a_chip_per_extra_version(
        self, edition: CodeEdition
    ) -> None:
        """The permalink page pins a version, not a day — so a referent amended
        mid-window shows every version it read as, like the hierarchy nav."""
        target = _provision(edition, "3.2.5.")
        record = _record(
            "Subsection 3.2.5.", to_provision=target, occurrence=0,
            targets=[
                {"version": 0, "effective_date": "2006-12-31",
                 "ineffective_date": "2010-01-01"},
                {"version": 1, "effective_date": "2010-01-01",
                 "ineffective_date": "2012-01-01"},
                {"version": 2, "effective_date": "2012-01-01",
                 "ineffective_date": "2014-01-01"},
            ],
        )
        out = linkify(
            "<p>see Subsection 3.2.5. here</p>", [record], CODE_NAME, fan_out=True,
        )
        assert out.count('class="cross-ref-chip ui-cite"') == 2
        assert ">v1</a>" in out and ">v2</a>" in out

    def test_no_link_record_renders_the_note_not_a_link(
        self, edition: CodeEdition
    ) -> None:
        """A curator no-link correction: the printed id was never enacted."""
        record = _record(
            "Sentence 9.9.9.9.(1)", to_provision=None, occurrence=0, targets=[],
            note="As filed, this points to a Sentence never enacted.",
        )
        out = linkify(
            "<p>per Sentence 9.9.9.9.(1) of the Code</p>", [record], CODE_NAME,
        )
        assert "<a " not in out
        assert 'class="cross-ref-nolink"' in out
        assert "never enacted" in out

    def test_unanchored_record_leaves_the_body_alone(self) -> None:
        record = _record("Section 9.41.", occurrence=None)
        html = "<p>provided in Section</p><p>9.41. and Part 11</p>"
        assert linkify(html, [record], CODE_NAME) == html

    def test_nested_citations_each_link_their_own_text(
        self, edition: CodeEdition
    ) -> None:
        target = _provision(edition, "3.7.4.3.")
        targets = [{"version": 0, "effective_date": "2006-12-31",
                    "ineffective_date": "2014-01-01"}]
        html = "<p>per Sentence 3.7.4.3.(5) and Sentence 3.7.4.3. generally</p>"
        records = [
            _record("Sentence 3.7.4.3.(5)", to_provision=target,
                    occurrence=0, targets=targets),
            _record("Sentence 3.7.4.3.", to_provision=target,
                    occurrence=0, targets=targets),
        ]
        out = linkify(html, records, CODE_NAME)
        assert out.count('class="cross-ref ui-cite"') == 2
        assert ">Sentence 3.7.4.3.(5)</a>" in out
        assert ">Sentence 3.7.4.3.</a> generally" in out

    def test_composes_with_term_highlighting(self, edition: CodeEdition) -> None:
        """Order matters: linkify first, then highlight.

        Highlighting inserts ``<mark>`` mid-text; run it first and the surface
        string is split out from under the matcher.  Run this way and both
        survive — the mark lands inside the anchor, the anchor's markup intact.
        """
        target = _provision(edition, "3.2.5.")
        record = _record(
            "Subsection 3.2.5.", to_provision=target, occurrence=0,
            targets=[{"version": 0, "effective_date": "2006-12-31",
                      "ineffective_date": "2014-01-01"}],
        )
        linked = linkify(
            "<p>fire ratings in Subsection 3.2.5.</p>", [record], CODE_NAME,
        )
        out = highlight_terms(linked, ["fire"])
        assert '<mark class="match-highlight">fire</mark>' in out
        assert 'class="cross-ref ui-cite"' in out
        assert 'href="' in out and "<mark" not in out.split('href="')[1][:60]


@pytest.mark.django_db
class TestProducerSpans:
    """The shipped shape: ``container`` + ``start``/``end`` into that string.

    A span is exact, so nothing here matches text — the surface text is only a
    label and an audit trail.
    """

    TARGETS = [{"version": 0, "effective_date": "2006-12-31",
                "ineffective_date": "2014-01-01"}]

    def _span_record(self, target, html: str, surface: str, **kwargs):
        start = html.index(surface)
        return _record(
            surface, to_provision=target, targets=self.TARGETS,
            start=start, end=start + len(surface), **kwargs,
        )

    def test_span_wraps_exactly_those_characters(self, edition: CodeEdition) -> None:
        target = _provision(edition, "3.2.5.")
        html = "<p>as required by Subsection 3.2.5. of this Code</p>"
        out = linkify(
            html, [self._span_record(target, html, "Subsection 3.2.5.")], CODE_NAME,
        )
        assert ">Subsection 3.2.5.</a>" in out
        assert out.startswith("<p>as required by ")

    def test_span_is_used_even_when_the_text_repeats(
        self, edition: CodeEdition
    ) -> None:
        """The case the occurrence fallback gets wrong: the *second* mention is
        the citation; the first is an external reference the detector excluded.
        """
        target = _provision(edition, "3.2.5.")
        html = "<p>Article 3.2.5. of the Fire Code, and Article 3.2.5. here</p>"
        start = html.rindex("Article 3.2.5.")
        record = _record(
            "Article 3.2.5.", to_provision=target, targets=self.TARGETS,
            start=start, end=start + len("Article 3.2.5."),
        )
        out = linkify(html, [record], CODE_NAME)
        assert out.count("<a ") == 1
        assert out.index("<a ") > out.index("Fire Code")

    def test_block_straddling_span_links_each_run(
        self, edition: CodeEdition
    ) -> None:
        """``Section</p><p>9.38.`` — one citation, one anchor per text run, and
        the block markup survives between them."""
        target = _provision(edition, "9.38.")
        html = "<p>in accordance with Section</p><p>9.38. shall be prepared</p>"
        start = html.index("Section")
        end = html.index("9.38.") + len("9.38.")
        record = _record(
            "Section 9.38.", to_provision=target, targets=self.TARGETS,
            start=start, end=end,
        )
        out = linkify(html, [record], CODE_NAME)
        assert out.count('class="cross-ref ui-cite"') == 2
        assert ">Section</a></p><p><a " in out
        assert ">9.38.</a>" in out

    def test_split_anchor_grows_one_set_of_chips(self, edition: CodeEdition) -> None:
        """Fan-out chips belong to the citation, not to each of its runs."""
        target = _provision(edition, "9.38.")
        html = "<p>under Section</p><p>9.38. of Division B</p>"
        record = _record(
            "Section 9.38.", to_provision=target,
            targets=self.TARGETS + [
                {"version": 1, "effective_date": "2010-01-01",
                 "ineffective_date": "2014-01-01"},
            ],
            start=html.index("Section"),
            end=html.index("9.38.") + len("9.38."),
        )
        out = linkify(html, [record], CODE_NAME, fan_out=True)
        assert out.count('class="cross-ref-chip ui-cite"') == 1

    def test_span_past_the_end_of_the_html_is_skipped(
        self, edition: CodeEdition
    ) -> None:
        """Stored rows outliving the body they indexed (a partial reload)."""
        target = _provision(edition, "3.2.5.")
        record = _record(
            "3.2.5.", to_provision=target, targets=self.TARGETS, start=500, end=520,
        )
        assert linkify("<p>short</p>", [record], CODE_NAME) == "<p>short</p>"

    def test_table_and_note_records_link_their_own_container(
        self, edition: CodeEdition
    ) -> None:
        target = _provision(edition, "3.2.5.")
        provision = _provision(edition, "9.10.1.1.")
        version = _version(provision, html="<p>body</p>")
        table = ProvisionVersionTable.objects.create(
            version=version, table_id="Table-4.1.8.6.",
            html="<td>see Article 3.2.5.</td>",
            notes="<p>Notes: per Article 3.2.5.</p>",
        )
        rows = [
            self._span_record(
                target, table.html, "Article 3.2.5.",
                container=ProvisionCrossReference.Container.TABLE,
                table_id="Table-4.1.8.6.",
            ),
            self._span_record(
                target, table.notes, "Article 3.2.5.",
                container=ProvisionCrossReference.Container.NOTE,
                table_id="Table-4.1.8.6.",
            ),
        ]
        annotate_tables([table], rows, CODE_NAME)
        assert 'class="cross-ref ui-cite"' in table.linked_html
        assert 'class="cross-ref ui-cite"' in table.linked_notes
        # Each record anchors only in its own container — the note record's
        # offsets are meaningless against the table html and vice versa.
        assert table.linked_html.count("<a ") == 1
        assert table.linked_notes.count("<a ") == 1

    def test_body_records_never_touch_a_table(self, edition: CodeEdition) -> None:
        target = _provision(edition, "3.2.5.")
        provision = _provision(edition, "9.10.1.1.")
        version = _version(provision, html="<p>see Article 3.2.5. here</p>")
        table = ProvisionVersionTable.objects.create(
            version=version, table_id="Table-4.1.8.6.",
            html="<td>see Article 3.2.5.</td>",
        )
        body = self._span_record(target, version.html, "Article 3.2.5.")
        annotate_tables([table], [body], CODE_NAME)
        assert "<a " not in table.linked_html


# ── Cite lists ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCiteLists:
    def test_cites_dedupes_by_target_provision(self, edition: CodeEdition) -> None:
        target = _provision(edition, "3.2.5.")
        targets = [{"version": 0, "effective_date": "2006-12-31",
                    "ineffective_date": "2014-01-01"}]
        rows = cites(
            [
                _record("Subsection 3.2.5.", to_provision=target, targets=targets),
                _record("3.2.5.", to_provision=target, targets=targets),
            ],
            CODE_NAME,
        )
        assert len(rows) == 1
        assert rows[0]["provision_id"] == "3.2.5."
        assert rows[0]["url"]

    def test_cited_by_lists_only_overlapping_citing_versions(
        self, edition: CodeEdition
    ) -> None:
        """The fan-in answers "who pointed here *then*", not "ever"."""
        target = _provision(edition, "3.2.5.")
        target_v0 = _version(target, html="<p>3.2.5. body</p>")

        early = _provision(edition, "9.10.1.1.")
        early_v0 = _version(
            early, effective=date(2006, 12, 31), ineffective=date(2008, 1, 1),
        )
        later = _provision(edition, "9.10.2.2.")
        later_v0 = _version(
            later, effective=date(2020, 1, 1), ineffective=None,
        )
        for citing in (early_v0, later_v0):
            ProvisionCrossReference.objects.create(
                from_version=citing, to_provision=target,
                surface_text="Subsection 3.2.5.", occurrence=0,
            )

        rows = cited_by(target_v0, target, CODE_NAME)
        assert [r["provision_id"] for r in rows] == ["9.10.1.1."]
        assert rows[0]["version_label"] == "v0"
        assert rows[0]["url"]

    def test_cited_by_map_matches_the_single_lookup(
        self, edition: CodeEdition
    ) -> None:
        """The batched search-path form must agree with the per-page form."""
        target = _provision(edition, "3.2.5.")
        target_v0 = _version(target)
        citing = _provision(edition, "9.10.1.1.")
        ProvisionCrossReference.objects.create(
            from_version=_version(citing), to_provision=target,
            surface_text="Subsection 3.2.5.", occurrence=0,
        )
        loaded = CodeEditionProvisionVersion.objects.select_related(
            "provision__edition__code"
        ).get(pk=target_v0.pk)
        assert cited_by_map([loaded])[target_v0.pk] == cited_by(
            target_v0, target, CODE_NAME
        )

    def test_permalink_page_renders_links_and_fan_in(
        self, edition: CodeEdition, client
    ) -> None:
        """End to end on the surface that pins a version rather than a date."""
        target = _provision(edition, "3.2.5.")
        _version(target, html="<p>3.2.5. body text</p>")
        citing = _provision(edition, "9.10.1.1.")
        citing_v0 = _version(
            citing, html="<p>conforming to Subsection 3.2.5. of Division B</p>",
        )
        ProvisionCrossReference.objects.create(
            from_version=citing_v0, to_provision=target,
            surface_text="Subsection 3.2.5.", occurrence=0,
            targets=[{"version": 0, "effective_date": "2006-12-31",
                      "ineffective_date": "2014-01-01"}],
        )

        citing_page = client.get(
            provision_permalink_url(CODE_NAME, "B", "9.10.1.1.", 0)
        ).content.decode()
        assert 'class="cross-ref ui-cite"' in citing_page
        assert ">Subsection 3.2.5.</a>" in citing_page

        target_page = client.get(
            provision_permalink_url(CODE_NAME, "B", "3.2.5.", 0)
        ).content.decode()
        assert "Cited by (1)" in target_page
        assert "9.10.1.1." in target_page

    def test_cited_by_dedupes_repeated_citations(self, edition: CodeEdition) -> None:
        target = _provision(edition, "3.2.5.")
        target_v0 = _version(target)
        citing_v0 = _version(_provision(edition, "9.10.1.1."))
        for surface, occurrence in (("Subsection 3.2.5.", 0), ("3.2.5.", 1)):
            ProvisionCrossReference.objects.create(
                from_version=citing_v0, to_provision=target,
                surface_text=surface, occurrence=occurrence,
            )
        assert len(cited_by(target_v0, target, CODE_NAME)) == 1


@pytest.mark.django_db
class TestAlternates:
    """A citation whose *printed* id resolves but a curator judged another
    provision was meant: printed is the primary link, the intended reading is a
    ``cross-ref-alt`` chip carrying the note (contract §``alternates[]``)."""

    TARGETS = [{"version": 0, "effective_date": "2006-12-31",
                "ineffective_date": "2014-01-01"}]

    def _cite_with_alt(self, edition, html, surface, *, note="printed vs meant"):
        printed = _provision(edition, "6.2.2.1.")   # what the Code printed
        intended = _provision(edition, "6.2.1.1.")  # what we believe was meant
        _version(printed)
        _version(intended)
        citing = _version(_provision(edition, "1.3.1.2."), html=html)
        start = html.index(surface)
        record = ProvisionCrossReference.objects.create(
            from_version=citing, to_provision=printed, surface_text=surface,
            container="body", start=start, end=start + len(surface),
            targets=self.TARGETS, note=note,
        )
        ProvisionCrossReferenceAlternate.objects.create(
            cross_reference=record, to_provision=intended, targets=self.TARGETS,
        )
        return record, printed, intended

    def test_printed_is_primary_intended_is_a_chip(
        self, edition: CodeEdition
    ) -> None:
        html = "<p>as in 6.2.2.1. of Division B</p>"
        record, _, _ = self._cite_with_alt(edition, html, "6.2.2.1.")
        out = linkify(html, [record], CODE_NAME, on_date=date(2008, 1, 1))
        # Primary anchor is the printed id; the chip is the intended one.
        assert 'class="cross-ref ui-cite"' in out
        assert 'data-cross-ref="6.2.2.1."' in out
        assert 'class="cross-ref-alt ui-cite"' in out
        assert 'data-cross-ref-alt="6.2.1.1."' in out
        assert ">6.2.1.1.</a>" in out
        # The note rides on the chip so a hover explains why two appear.
        assert "printed vs meant" in out

    def test_no_alternate_no_alt_chip(self, edition: CodeEdition) -> None:
        """The common record — a printed id with no curator alternate — grows
        no ``cross-ref-alt`` chip."""
        target = _provision(edition, "3.2.5.")
        _version(target)
        citing = _version(_provision(edition, "1.3.1.2."), html="<p>see 3.2.5.</p>")
        record = ProvisionCrossReference.objects.create(
            from_version=citing, to_provision=target, surface_text="3.2.5.",
            container="body", start=8, end=8 + len("3.2.5."), targets=self.TARGETS,
        )
        out = linkify("<p>see 3.2.5.</p>", [record], CODE_NAME)
        assert "cross-ref-alt" not in out

    def test_cites_row_carries_the_alternate(self, edition: CodeEdition) -> None:
        """The image-only fallback keeps parity: the alternate rides on the row."""
        html = "<p>as in 6.2.2.1. of Division B</p>"
        record, _, _ = self._cite_with_alt(edition, html, "6.2.2.1.")
        (row,) = cites([record], CODE_NAME, on_date=date(2008, 1, 1))
        assert row["provision_id"] == "6.2.2.1."          # printed leads
        assert [a["provision_id"] for a in row["alternates"]] == ["6.2.1.1."]

    def test_permalink_page_shows_the_alt_chip(
        self, edition: CodeEdition, client
    ) -> None:
        html = "<p>conforming to 6.2.2.1. of Division B</p>"
        self._cite_with_alt(edition, html, "6.2.2.1.")
        page = client.get(
            provision_permalink_url(CODE_NAME, "B", "1.3.1.2.", 0)
        ).content.decode()
        assert 'class="cross-ref-alt ui-cite"' in page
        assert ">6.2.1.1.</a>" in page
