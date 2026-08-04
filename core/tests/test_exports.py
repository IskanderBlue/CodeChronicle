"""Tests for the export endpoints — the citation menu and the export log.

Two properties carry the weight.  The **gate** must hold on both the read path
and the write path, or a free reader either sees a locked edition's citation
or is counted as having exported one.  And the **counts must be clean**: the
whole reason four exports ship at once is that the counts decide which ones
survive, so a kind we do not recognise is refused rather than recorded under a
name the insights table cannot read.
"""

from datetime import date

import pytest
from django.urls import reverse

from core.insights import export_counts
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    ProvisionVersionTable,
    Regulation,
    User,
)

FREE = "OBC_2006"
PAID = "OBC_2012"


def _edition(code, edition_id, **kwargs):
    return CodeEdition.objects.create(
        code=code, edition_id=edition_id, year=int(edition_id), **kwargs
    )


@pytest.fixture
def corpus(db, settings):
    """One free-tier edition and one Pro-only edition, each with a provision."""
    settings.FREE_TIER_CODE_NAMES = [FREE]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    out = {}
    for edition_id, provision_id in (("2006", "3.2.5.7."), ("2012", "1.10.2.4.")):
        edition = _edition(code, edition_id, effective_date=date(int(edition_id), 1, 1))
        Regulation.objects.create(
            edition=edition,
            reg_id=f"350/{edition_id[2:]}",
            role=Regulation.Role.BASE,
            effective_date=date(int(edition_id), 1, 1),
        )
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id=provision_id, level="article", division="B",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(int(edition_id), 1, 1),
            title="Water Supply",
            html="<p>text</p>",
        )
        out[edition_id] = f"OBC_{edition_id}/B/{provision_id}/v0"
    return out


def _exports():
    return EngagementEvent.objects.filter(
        event_type=EngagementEvent.EventType.EXPORT
    )


@pytest.mark.django_db
class TestTheCitationPanel:
    def test_a_free_reader_gets_the_free_edition(self, client, corpus):
        response = client.get(reverse("core:citation_panel"), {"v": corpus["2006"]})
        assert response.status_code == 200
        body = response.content.decode()
        # Both formats, shown in full — a reader picks by reading, not by
        # trusting a label.
        assert "as it appeared on" in body
        assert "Retrieved" in body

    def test_a_free_reader_is_refused_the_pro_edition(self, client, corpus):
        response = client.get(reverse("core:citation_panel"), {"v": corpus["2012"]})
        assert response.status_code == 403

    def test_a_pro_reader_gets_the_pro_edition(self, client, corpus):
        User.objects.create_user(
            email="pro@example.com", password="testpass", pro_courtesy=True,
        )
        client.login(email="pro@example.com", password="testpass")
        response = client.get(reverse("core:citation_panel"), {"v": corpus["2012"]})
        assert response.status_code == 200

    def test_an_unknown_version_is_named_not_500ed(self, client, corpus):
        response = client.get(
            reverse("core:citation_panel"), {"v": "OBC_2006/B/9.9.9.9./v0"}
        )
        assert response.status_code == 400

    def test_opening_the_menu_is_not_an_export(self, client, corpus):
        client.get(reverse("core:citation_panel"), {"v": corpus["2006"]})
        assert _exports().count() == 0


@pytest.mark.django_db
class TestRecordingAnExport:
    def test_a_copy_is_recorded_with_its_kind_and_format(self, client, corpus):
        response = client.post(
            reverse("core:record_export"),
            {"kind": "citation", "format": "legal", "v": corpus["2006"]},
        )
        assert response.status_code == 204
        event = _exports().get()
        assert event.context["kind"] == "citation"
        assert event.context["format"] == "legal"
        assert event.context["provision_id"] == "3.2.5.7."
        assert event.object_type == "CodeEditionProvisionVersion"

    def test_an_unknown_kind_is_refused_rather_than_counted(self, client, corpus):
        response = client.post(reverse("core:record_export"), {"kind": "everything"})
        assert response.status_code == 400
        assert _exports().count() == 0

    def test_an_unknown_citation_format_is_refused(self, client, corpus):
        response = client.post(
            reverse("core:record_export"),
            {"kind": "citation", "format": "bluebook", "v": corpus["2006"]},
        )
        assert response.status_code == 400
        assert _exports().count() == 0

    def test_a_free_reader_cannot_log_an_export_of_a_locked_edition(
        self, client, corpus
    ):
        response = client.post(
            reverse("core:record_export"),
            {"kind": "citation", "format": "legal", "v": corpus["2012"]},
        )
        assert response.status_code == 400
        # Otherwise the counts would show value delivered for a request we
        # refused, and the conversion numbers are the reason this row exists.
        assert _exports().count() == 0


@pytest.mark.django_db
class TestTheInsightsTable:
    """The counts are the reason four exports shipped at once."""

    def test_every_kind_has_a_row_even_at_zero(self, corpus):
        rows = export_counts()
        assert [r["kind"] for r in rows] == [
            "citation", "provision_pdf", "results_csv", "comparison_pdf",
        ]
        # A missing line would read as "not built yet", which is the opposite
        # of the finding the table exists to report.
        assert all(r["total"] == 0 for r in rows)

    def test_it_counts_each_kind_and_breaks_out_the_citation_formats(self, corpus):
        for kind, fmt in (
            ("citation", "legal"),
            ("citation", "legal"),
            ("citation", "report"),
            ("results_csv", None),
        ):
            context = {"kind": kind}
            if fmt:
                context["format"] = fmt
            EngagementEvent.objects.create(
                ip_address="203.0.113.4",
                event_type=EngagementEvent.EventType.EXPORT,
                context=context,
            )
        rows = {r["kind"]: r for r in export_counts()}
        assert rows["citation"]["total"] == 3
        assert rows["results_csv"]["total"] == 1
        assert rows["provision_pdf"]["total"] == 0
        formats = {f["format"]: f["total"] for f in rows["citation"]["formats"]}
        assert formats == {"legal": 2, "report": 1, "reference": 0}

    def test_other_event_types_are_not_counted_as_exports(self, corpus):
        EngagementEvent.objects.create(
            ip_address="203.0.113.4",
            event_type=EngagementEvent.EventType.VERSION_COMPARISON,
            context={"kind": "comparison_pdf"},
        )
        rows = {r["kind"]: r for r in export_counts()}
        # A comparison *viewed* is not a comparison *exported*, and the two
        # numbers have to be readable against each other.
        assert rows["comparison_pdf"]["total"] == 0


def _stub_search(seen, payload=None):
    """Stand in for the pipeline, recording what the export asked it for."""
    def _run(query, **kwargs):
        seen["query"] = query
        seen.update(kwargs)
        return payload or {
            "success": True,
            "results": [],
            "locked_preview": [],
            "search_history_id": None,
        }
    return _run


def _card(version):
    return {
        "id": "3.2.5.7.",
        "division": "B",
        "title": "Water Supply",
        "code_edition": "OBC_2006",
        "score": 1.234,
        "version": version,
    }


@pytest.mark.django_db
class TestTheResultsCsv:
    def test_an_anonymous_reader_is_refused(self, client, corpus):
        response = client.post(reverse("core:results_csv"), {"query": "fire"})
        assert response.status_code == 403
        assert _exports().count() == 0

    def test_it_re_runs_the_search_the_page_posted(
        self, client, corpus, monkeypatch
    ):
        seen: dict = {}
        monkeypatch.setattr("core.views.exports.run_search", _stub_search(seen))
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")

        client.post(
            reverse("core:results_csv"),
            {"query": "fire", "date": "2007-01-01", "province": "ON"},
        )
        # Same query, same overrides, same floor — the export matches the
        # screen because one pipeline decided both, not because anything was
        # copied across.
        assert seen["query"] == "fire"
        assert seen["date_override"] == "2007-01-01"
        assert seen["province_override"] == "ON"
        assert "match_threshold" in seen

    def test_a_row_per_result_with_the_dates_score_and_url(
        self, client, corpus, monkeypatch
    ):
        version = CodeEditionProvisionVersion.objects.get(
            provision__provision_id="3.2.5.7."
        )
        monkeypatch.setattr(
            "core.views.exports.run_search",
            _stub_search({}, {
                "success": True,
                "results": [_card(version)],
                "locked_preview": [],
                "search_history_id": None,
            }),
        )
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")

        response = client.post(reverse("core:results_csv"), {"query": "fire"})
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert "attachment;" in response["Content-Disposition"]
        lines = response.content.decode("utf-8-sig").strip().splitlines()
        assert lines[0] == ",".join(
            [
                "provision_id", "division", "title", "edition", "effective_date",
                "ineffective_date", "score", "locked", "url",
            ]
        )
        assert "3.2.5.7." in lines[1]
        assert "1.234" in lines[1]
        assert "false" in lines[1]
        assert "/provision/OBC_2006/B/3.2.5.7./v0/" in lines[1]

    def test_a_locked_row_carries_identity_only(
        self, client, corpus, monkeypatch
    ):
        monkeypatch.setattr(
            "core.views.exports.run_search",
            _stub_search({}, {
                "success": True,
                "results": [],
                "locked_preview": [{
                    "id": "1.10.2.4.",
                    "division": "B",
                    "title": "Maintenance",
                    "code_edition": "OBC_2012",
                }],
                "search_history_id": None,
            }),
        )
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")

        response = client.post(reverse("core:results_csv"), {"query": "fire"})
        row = response.content.decode("utf-8-sig").strip().splitlines()[1]
        # The reader saw that these exist and nothing more, so the row says
        # that: identity, marked locked, and no score we did not serve.
        assert row.startswith(
            "1.10.2.4.,B,Maintenance,Ontario Building Code 2012,,,,true,"
        )

    def test_the_export_is_recorded_with_its_row_counts(
        self, client, corpus, monkeypatch
    ):
        monkeypatch.setattr("core.views.exports.run_search", _stub_search({}))
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")

        client.post(reverse("core:results_csv"), {"query": "fire"})
        event = _exports().get()
        assert event.context["kind"] == "results_csv"
        assert event.context["rows"] == 0

    def test_a_failed_search_is_not_a_csv_of_nothing(
        self, client, corpus, monkeypatch
    ):
        monkeypatch.setattr(
            "core.views.exports.run_search",
            _stub_search({}, {"success": False, "error": "No province."}),
        )
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")

        response = client.post(reverse("core:results_csv"), {"query": "fire"})
        assert response.status_code == 400
        assert _exports().count() == 0


def _print_url():
    return reverse(
        "core:provision_print", args=["OBC_2006", "B", "3.2.5.7.", 0]
    )


@pytest.mark.django_db
class TestThePrintableProvision:
    def test_an_anonymous_reader_is_asked_to_sign_in(self, client, corpus):
        response = client.get(_print_url())
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]
        # The ask is the point, so nothing is recorded: an export that did not
        # happen must not appear in the counts that decide what survives.
        assert _exports().count() == 0

    def test_a_signed_in_reader_gets_the_exhibit(self, client, corpus):
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")
        response = client.get(_print_url())
        assert response.status_code == 200
        body = response.content.decode()
        # Everything an exhibit needs to stand on its own.
        assert "3.2.5.7." in body
        assert "in force" in body
        assert "O. Reg. 350/06" in body
        assert "Retrieved" in body
        assert "Not legal advice" in body

    def test_it_is_recorded_as_an_export_and_not_as_a_view(self, client, corpus):
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")
        client.get(_print_url())
        event = _exports().get()
        assert event.context["kind"] == "provision_pdf"
        # Recording both would double-count one reader and make the export
        # counts unreadable against the view totals.
        assert not EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW
        ).exists()

    def test_a_scanned_provision_does_not_print_its_tables_twice(
        self, client, corpus
    ):
        version = CodeEditionProvisionVersion.objects.get(
            provision__provision_id="3.2.5.7."
        )
        version.page_images = [
            {"image": "documents/p.webp",
             "bboxes": [{"x": 0.02, "y": 0.1, "w": 0.45, "h": 0.3}]}
        ]
        version.save(update_fields=["page_images"])
        ProvisionVersionTable.objects.create(
            version=version, table_id="Table-3.2.5.7.", caption="Water supply",
            html="<table><tr><td>x</td></tr></table>",
        )
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")

        body = client.get(_print_url()).content.decode()
        # The scan already shows the table. Printing the row as well puts the
        # same table on the page twice and leaves the reader of an exhibit to
        # decide which copy is the evidence.
        assert "Water supply" not in body
        assert "the page images already show them" in body

        # ...and the reader can still ask for it.
        forced = client.get(_print_url(), {"tables": "on"}).content.decode()
        assert "Water supply" in forced

    def test_an_html_provision_still_prints_its_tables(self, client, corpus):
        version = CodeEditionProvisionVersion.objects.get(
            provision__provision_id="3.2.5.7."
        )
        ProvisionVersionTable.objects.create(
            version=version, table_id="Table-3.2.5.7.", caption="Water supply",
            html="<table><tr><td>x</td></tr></table>",
        )
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")

        body = client.get(_print_url()).content.decode()
        # No page images, so the table is nowhere else in the exhibit.
        assert "Water supply" in body

    def test_a_locked_edition_is_refused_even_to_a_signed_in_reader(
        self, client, corpus
    ):
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")
        response = client.get(
            reverse("core:provision_print", args=["OBC_2012", "B", "1.10.2.4.", 0])
        )
        assert response.status_code == 403
        assert _exports().count() == 0
