"""Free-tier content gate (core.access) — helpers and gated surfaces.

The gate ships behind FREE_TIER_GATING_ENABLED (default off), so every
gating test flips the flag on via the ``settings`` fixture; the default-off
tests pin the no-user-facing-change guarantee.
"""

from datetime import date

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client

from core.access import edition_allowed, partition_results, user_is_unrestricted
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionMapping,
    Regulation,
    User,
)


@pytest.fixture
def two_editions(db):
    """OBC 2006 (free scope) and OBC 2012 (locked), each with one
    provision+version and a base regulation."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    data: dict[str, dict] = {}
    for edition_id, year, effective in (
        ("2006", 2006, date(2006, 12, 31)),
        ("2012", 2012, date(2014, 1, 1)),
    ):
        edition = CodeEdition.objects.create(
            code=code, edition_id=edition_id, year=year, effective_date=effective,
        )
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id="1.1.1.1.", level="article", division="B",
        )
        version = CodeEditionProvisionVersion.objects.create(
            provision=provision, version=0, effective_date=effective,
            title="Scope", html="<p>Scope text</p>",
        )
        regulation = Regulation.objects.create(
            reg_id=f"350/{edition_id[-2:]}", edition=edition, role="base",
            effective_date=effective,
        )
        data[edition_id] = {
            "edition": edition,
            "provision": provision,
            "version": version,
            "regulation": regulation,
        }
    return data


@pytest.fixture
def pro_user(db):
    return User.objects.create_user(
        email="pro@example.com", password="testpass", pro_courtesy=True,
    )


@pytest.fixture
def free_user(db):
    return User.objects.create_user(email="free@example.com", password="testpass")


class TestAccessHelpers:
    def test_gating_disabled_everyone_unrestricted(self, settings):
        settings.FREE_TIER_GATING_ENABLED = False
        assert user_is_unrestricted(None)
        assert user_is_unrestricted(AnonymousUser())
        assert edition_allowed(AnonymousUser(), "OBC_2012")

    def test_gating_on_anonymous_scoped_to_free_set(self, settings):
        settings.FREE_TIER_GATING_ENABLED = True
        settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
        assert not user_is_unrestricted(None)
        assert not user_is_unrestricted(AnonymousUser())
        assert edition_allowed(AnonymousUser(), "OBC_2006")
        assert not edition_allowed(AnonymousUser(), "OBC_2012")

    @pytest.mark.django_db
    def test_gating_on_free_user_scoped(self, settings, free_user):
        settings.FREE_TIER_GATING_ENABLED = True
        settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
        assert not user_is_unrestricted(free_user)
        assert edition_allowed(free_user, "OBC_2006")
        assert not edition_allowed(free_user, "OBC_2012")

    @pytest.mark.django_db
    def test_gating_on_pro_user_unrestricted(self, settings, pro_user):
        settings.FREE_TIER_GATING_ENABLED = True
        settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
        assert user_is_unrestricted(pro_user)
        assert edition_allowed(pro_user, "OBC_2012")

    def test_partition_results_counts_locked_per_edition(self, settings):
        settings.FREE_TIER_GATING_ENABLED = True
        settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
        results = [
            {"code_edition": "OBC_2006", "id": "a"},
            {"code_edition": "OBC_2012", "id": "b"},
            {"code_edition": "OBC_2012", "id": "c"},
        ]
        kept, locked = partition_results(AnonymousUser(), results)
        assert [r["id"] for r in kept] == ["a"]
        assert locked == {"OBC_2012": 2}

    def test_partition_results_unrestricted_passthrough(self, settings):
        settings.FREE_TIER_GATING_ENABLED = False
        results = [{"code_edition": "OBC_2012", "id": "b"}]
        kept, locked = partition_results(AnonymousUser(), results)
        assert kept == results
        assert locked == {}


@pytest.mark.django_db
class TestGatedViews:
    """Full-page and partial surfaces with the gate flipped on."""

    def _enable(self, settings):
        settings.FREE_TIER_GATING_ENABLED = True
        settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]

    def test_permalink_locked_edition_403_teaser(
        self, settings, client: Client, two_editions
    ):
        self._enable(settings)
        response = client.get("/provision/OBC_2012/B/1.1.1.1./v0/")
        assert response.status_code == 403
        content = response.content.decode()
        assert "OBC 2012 is Pro content" in content
        assert "/pricing/" in content

    def test_permalink_free_edition_allowed(
        self, settings, client: Client, two_editions
    ):
        self._enable(settings)
        response = client.get("/provision/OBC_2006/B/1.1.1.1./v0/")
        assert response.status_code == 200

    def test_permalink_locked_edition_allowed_for_pro(
        self, settings, client: Client, two_editions, pro_user
    ):
        self._enable(settings)
        client.force_login(pro_user)
        response = client.get("/provision/OBC_2012/B/1.1.1.1./v0/")
        assert response.status_code == 200

    def test_permalink_locked_edition_open_when_gating_off(
        self, settings, client: Client, two_editions
    ):
        settings.FREE_TIER_GATING_ENABLED = False
        response = client.get("/provision/OBC_2012/B/1.1.1.1./v0/")
        assert response.status_code == 200

    def test_regulation_detail_gated_by_its_edition(
        self, settings, client: Client, two_editions
    ):
        self._enable(settings)
        locked_reg = two_editions["2012"]["regulation"]
        free_reg = two_editions["2006"]["regulation"]
        assert client.get(f"/regulation/{locked_reg.pk}/").status_code == 403
        assert client.get(f"/regulation/{free_reg.pk}/").status_code == 200

    def test_edition_chain_gated(self, settings, client: Client, two_editions):
        self._enable(settings)
        locked = two_editions["2012"]["edition"]
        free = two_editions["2006"]["edition"]
        assert client.get(f"/edition/{locked.pk}/chain/").status_code == 403
        assert client.get(f"/edition/{free.pk}/chain/").status_code == 200

    def test_viewer_section_content_locked_teaser(
        self, settings, client: Client, two_editions
    ):
        self._enable(settings)
        response = client.get(
            "/viewer/section-content/",
            {"code": "OBC", "edition_id": "2012", "division": "B",
             "provision_id": "1.1.1.1."},
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "Ontario Building Code 2012 is Pro content" in content
        assert "Scope text" not in content

    def test_viewer_section_content_free_edition_renders(
        self, settings, client: Client, two_editions
    ):
        self._enable(settings)
        response = client.get(
            "/viewer/section-content/",
            {"code": "OBC", "edition_id": "2006", "division": "B",
             "provision_id": "1.1.1.1."},
        )
        assert "Scope text" in response.content.decode()

    def test_viewer_edition_nav_locks_adjacent_edition(
        self, settings, client: Client, two_editions
    ):
        self._enable(settings)
        # An identity-carry mapping row so the lineage link into 2012
        # exists (number equality alone never links).
        ProvisionMapping.objects.create(
            old_provision=two_editions["2006"]["provision"],
            new_provision=two_editions["2012"]["provision"],
            mapping_type="renumbered",
        )
        response = client.get(
            "/viewer/edition-nav/",
            {"code": "OBC_2006", "provision_id": "1.1.1.1.", "division": "B"},
        )
        content = response.content.decode()
        # The 2012 successor stays visible as a teaser, but links to pricing
        # instead of carrying the viewer payload.
        assert "OBC 2012" in content
        assert "Pro" in content
        assert "/pricing/" in content
        assert "data-edition-result" not in content

    def test_viewer_edition_nav_unlocked_for_pro(
        self, settings, client: Client, two_editions, pro_user
    ):
        self._enable(settings)
        ProvisionMapping.objects.create(
            old_provision=two_editions["2006"]["provision"],
            new_provision=two_editions["2012"]["provision"],
            mapping_type="renumbered",
        )
        client.force_login(pro_user)
        response = client.get(
            "/viewer/edition-nav/",
            {"code": "OBC_2006", "provision_id": "1.1.1.1.", "division": "B"},
        )
        assert "data-edition-result" in response.content.decode()


@pytest.mark.django_db
class TestPricingPage:
    """The pricing view tracks the gate flag, so page and gate can't skew."""

    def test_gating_off_serves_early_access_placeholder(self, settings, client: Client):
        settings.FREE_TIER_GATING_ENABLED = False
        content = client.get("/pricing/").content.decode()
        assert "Early Access" in content
        assert "Choose your plan" not in content

    def test_gating_on_serves_plan_cards(self, settings, client: Client):
        settings.FREE_TIER_GATING_ENABLED = True
        content = client.get("/pricing/").content.decode()
        assert "Choose your plan" in content
        assert "Ontario Building Code 2006" in content
        assert "Every covered edition (OBC 2006, 2012, and counting)" in content
        # Keeps the early-access page's lower half (partner pitch + roadmap)
        # but not its free-for-now framing.
        assert "Roadmap" in content
        assert "currently in early access" not in content

    def test_gating_on_pro_user_sees_pro_as_current(
        self, settings, client: Client, pro_user
    ):
        settings.FREE_TIER_GATING_ENABLED = True
        client.force_login(pro_user)
        content = client.get("/pricing/").content.decode()
        assert "Manage Subscription" in content
