"""Tests for reader reports — the "this looks wrong" dialog and its queue.

Two design rules under test throughout. First, the report is free for
everybody: anonymous, free and Pro all file the same way, because a reader who
disputes a text is doing our verification for us. Second, the target is stored
as text, so a report survives the reload that replaces every provision pk.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionFeedback,
    Regulation,
    User,
)
from core.views.feedback import MAX_REPORTS_PER_IP_PER_DAY


@pytest.fixture
def provision(db):
    """One OBC 2006 article with a version, plus its base regulation."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006, effective_date=date(2006, 12, 31),
    )
    node = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.2.4.5.", level="article", division="B",
    )
    version = CodeEditionProvisionVersion.objects.create(
        provision=node, version=0, effective_date=date(2006, 12, 31),
        title="Fire alarm", html="<p>Text</p>",
    )
    regulation = Regulation.objects.create(
        reg_id="350/06", edition=edition, role="base",
        effective_date=date(2006, 12, 31),
    )
    return {"edition": edition, "provision": node, "version": version,
            "regulation": regulation}


def _payload(**overrides):
    """A well-formed provision report."""
    data = {
        "code_edition": "OBC_2006",
        "division": "B",
        "provision_id": "3.2.4.5.",
        "version": "0",
        "note": "The in-force end date is a day early.",
        "surface": "permalink",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestFilingAReport:
    def test_anonymous_reader_can_file(self, client):
        response = client.post(reverse("core:report_problem"), _payload())
        assert response.status_code == 200
        row = ProvisionFeedback.objects.get()
        assert row.provision_id == "3.2.4.5."
        assert row.version == 0
        assert row.user is None
        assert row.status == ProvisionFeedback.Status.NEW
        assert b"recorded" in response.content.lower()

    def test_free_and_pro_readers_can_file(self, client):
        """Gating never applies here. A dispute is worth more than the gate."""
        free = User.objects.create_user(email="free@example.com", password="pw")
        pro = User.objects.create_user(
            email="pro@example.com", password="pw", pro_courtesy=True
        )
        for user in (free, pro):
            client.force_login(user)
            client.post(reverse("core:report_problem"), _payload())
        assert ProvisionFeedback.objects.count() == 2
        assert set(
            ProvisionFeedback.objects.values_list("user__email", flat=True)
        ) == {"free@example.com", "pro@example.com"}

    def test_a_signed_in_report_stores_no_ip(self, client):
        """The account already identifies them; the IP would be surplus."""
        user = User.objects.create_user(email="reader@example.com", password="pw")
        client.force_login(user)
        client.post(reverse("core:report_problem"), _payload())
        row = ProvisionFeedback.objects.get()
        assert row.user == user
        assert row.ip_address is None

    def test_version_zero_is_stored_not_dropped(self, client):
        """v0 is falsy and is the most common version. Nothing may treat it
        as a missing value."""
        client.post(reverse("core:report_problem"), _payload(version="0"))
        assert ProvisionFeedback.objects.get().version == 0

    def test_keeps_a_valid_email_and_drops_a_malformed_one(self, client):
        client.post(
            reverse("core:report_problem"), _payload(email="reader@example.com")
        )
        client.post(reverse("core:report_problem"), _payload(email="not-an-address"))
        emails = list(
            ProvisionFeedback.objects.order_by("id").values_list("email", flat=True)
        )
        assert emails == ["reader@example.com", ""]

    def test_an_empty_note_is_refused_and_stores_nothing(self, client):
        response = client.post(reverse("core:report_problem"), _payload(note="   "))
        assert response.status_code == 200
        assert ProvisionFeedback.objects.count() == 0
        assert b"Tell us what is wrong" in response.content

    def test_a_report_with_no_target_is_a_bad_request(self, client):
        """The form always carries a target, so this is a malformed post and
        not a mistake the reader could correct."""
        response = client.post(
            reverse("core:report_problem"),
            {"note": "something is wrong", "code_edition": "OBC_2006"},
        )
        assert response.status_code == 400
        assert ProvisionFeedback.objects.count() == 0

    def test_a_regulation_report_needs_no_provision(self, client):
        client.post(
            reverse("core:report_problem"),
            {"code_edition": "OBC_2006", "reg_id": "350/06",
             "note": "The filing date is wrong.", "surface": "regulation"},
        )
        row = ProvisionFeedback.objects.get()
        assert row.reg_id == "350/06"
        assert row.provision_id == ""
        assert row.version is None

    def test_unknown_surface_falls_back(self, client):
        client.post(reverse("core:report_problem"), _payload(surface="not-a-surface"))
        assert ProvisionFeedback.objects.get().surface == "permalink"

    def test_over_limit_posts_are_accepted_silently_and_not_stored(self, client):
        for i in range(MAX_REPORTS_PER_IP_PER_DAY):
            client.post(reverse("core:report_problem"), _payload(note=f"fault {i}"))
        response = client.post(
            reverse("core:report_problem"), _payload(note="one too many")
        )
        assert response.status_code == 200
        assert ProvisionFeedback.objects.count() == MAX_REPORTS_PER_IP_PER_DAY
        assert not ProvisionFeedback.objects.filter(note="one too many").exists()

    def test_get_is_not_allowed(self, client):
        assert client.get(reverse("core:report_problem")).status_code == 405


@pytest.mark.django_db
class TestTheTriggerOnEachSurface:
    """The affordance must reach all three reading surfaces, and must not
    appear on the pages that only exhibit a component."""

    def test_the_provision_permalink_offers_it(self, client, provision):
        body = client.get("/provision/OBC_2006/B/3.2.4.5./v0/").content.decode()
        assert "This looks wrong" in body
        assert 'name="note"' in body

    def test_the_regulation_page_offers_it(self, client, provision):
        body = client.get(
            reverse("core:regulation_detail", args=[provision["regulation"].pk])
        ).content.decode()
        assert "This looks wrong" in body
        assert 'name="reg_id"' in body

    def test_the_landing_specimen_does_not_offer_it(self, client):
        """The landing page mounts a real band as a worked example. A report
        filed from there would name a provision nobody was reading."""
        assert "This looks wrong" not in client.get(
            reverse("core:about")
        ).content.decode()

    def test_the_search_result_body_turns_it_on(self):
        """Read from the source, because rendering one search result needs a
        parsed query and a scored corpus. What can go wrong here is the wiring
        — a band mounted without allow_report renders perfectly and silently
        drops the affordance — and the source is where that shows."""
        source = Path("templates/partials/_result_body.html").read_text(
            encoding="utf-8"
        )
        assert source.count("allow_report=True") == 2, (
            "both the master-detail band and the stacked banner must turn it on"
        )
        assert 'report_surface="search"' in source

    def test_the_verification_guide_does_not_offer_it(self, client):
        """Its rails are illustrative dates with no provision behind them."""
        assert "This looks wrong" not in client.get(
            reverse("core:verification_guide")
        ).content.decode()


@pytest.mark.django_db
class TestTheQueue:
    def _staff(self, client):
        user = User.objects.create_user(
            email="staff@example.com", password="pw", is_staff=True
        )
        client.force_login(user)
        return user

    def _report(self, **overrides):
        fields = {
            "code_edition": "OBC_2006", "division": "B",
            "provision_id": "3.2.4.5.", "version": 0,
            "note": "Wrong date.", "surface": "permalink",
        }
        fields.update(overrides)
        return ProvisionFeedback.objects.create(**fields)

    def test_the_queue_lists_a_report_and_links_to_it(self, client):
        self._staff(client)
        self._report()
        body = client.get(reverse("core:insights")).content.decode()
        assert "Reader reports" in body
        assert "Wrong date." in body
        assert "/provision/OBC_2006/B/3.2.4.5./v0/" in body

    def test_untriaged_reports_sort_above_newer_resolved_ones(self, client):
        self._staff(client)
        old_new = self._report(note="OLD AND UNTRIAGED")
        ProvisionFeedback.objects.filter(pk=old_new.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        self._report(note="NEW BUT FIXED", status=ProvisionFeedback.Status.FIXED)
        body = client.get(reverse("core:insights")).content.decode()
        assert body.index("OLD AND UNTRIAGED") < body.index("NEW BUT FIXED")

    def test_a_new_report_outside_the_window_is_still_listed(self, client):
        """An unanswered report does not stop being unanswered because the
        window moved."""
        self._staff(client)
        stale = self._report(note="ANCIENT AND UNANSWERED")
        ProvisionFeedback.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(days=400)
        )
        body = client.get(reverse("core:insights")).content.decode()
        assert "ANCIENT AND UNANSWERED" in body

    def test_the_status_control_moves_a_report(self, client):
        self._staff(client)
        row = self._report()
        response = client.post(
            reverse("core:feedback_status", args=[row.pk]), {"status": "fixed"}
        )
        assert response.status_code == 200
        row.refresh_from_db()
        assert row.status == ProvisionFeedback.Status.FIXED
        # The response is the re-rendered row, not the whole page.
        assert b"<tr" in response.content
        assert b"Reader reports" not in response.content

    def test_the_current_status_is_marked_in_the_control(self, client):
        """Marked with a component class, not a utility. base.html's unlayered
        .ui-btn-ghost beats a Tailwind utility in @layer utilities whatever the
        source order, so `text-secondary` here rendered every button
        identically and the control showed no state at all."""
        self._staff(client)
        self._report(status=ProvisionFeedback.Status.FIXED)
        body = client.get(reverse("core:insights")).content.decode()
        # Count the class attribute's own occurrence: the bare name also
        # appears in the .ui-btn-ghost.is-current rule in base.html.
        assert body.count('is-current"') == 1
        assert 'aria-current="true"' in body
        # The colour utilities must not come back on this control: they render
        # and do nothing, which is the failure that hides.
        row_source = Path("templates/partials/_feedback_row.html").read_text(
            encoding="utf-8"
        )
        assert "text-secondary" not in row_source

    def test_an_unknown_status_is_refused(self, client):
        self._staff(client)
        row = self._report()
        response = client.post(
            reverse("core:feedback_status", args=[row.pk]), {"status": "deleted"}
        )
        assert response.status_code == 400
        row.refresh_from_db()
        assert row.status == ProvisionFeedback.Status.NEW

    def test_a_non_staff_reader_cannot_see_or_move_reports(self, client):
        row = self._report()
        user = User.objects.create_user(email="reader@example.com", password="pw")
        client.force_login(user)
        assert client.get(reverse("core:insights")).status_code == 302
        assert client.post(
            reverse("core:feedback_status", args=[row.pk]), {"status": "fixed"}
        ).status_code == 302
        row.refresh_from_db()
        assert row.status == ProvisionFeedback.Status.NEW


@pytest.mark.django_db
class TestTheTargetSurvivesAReload:
    def test_the_reference_reads_without_the_provision_row(self):
        """The whole reason the target is text. Deleting every provision row
        stands in for the reload that replaces them all."""
        row = ProvisionFeedback.objects.create(
            code_edition="OBC_2006", division="B", provision_id="3.2.4.5.",
            version=2, note="Wrong.",
        )
        CodeEditionProvision.objects.all().delete()
        assert row.target_ref == "OBC_2006 · Div B · 3.2.4.5. · v2"

    def test_a_regulation_reference_names_the_number(self):
        row = ProvisionFeedback.objects.create(
            code_edition="OBC_2006", reg_id="350/06", note="Wrong.",
        )
        assert row.target_ref == "OBC_2006 · O. Reg. 350/06"
