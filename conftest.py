"""Shared pytest fixtures.

Content gating (accounts.access) is unconditional, so any anonymous request to a
gated surface is scoped to ``settings.FREE_TIER_CODE_NAMES``. Most tests
exercise those surfaces with fixture editions and are not about gating —
widen the free scope to the editions test fixtures create so they keep
testing their own subject. Gating tests (test_access.py, the lineage lock
tests) pin their own narrower scope explicitly, overriding this.
"""

import pytest


@pytest.fixture(autouse=True)
def _free_scope_covers_fixture_editions(settings):
    settings.FREE_TIER_CODE_NAMES = [
        "OBC_1997",
        "OBC_2006",
        "OBC_2012",
        "OBC_2024",
        "NBC_2025",
        "BCBC_2018",
    ]


@pytest.fixture(autouse=True)
def _turnstile_is_off(settings):
    """Pin the Turnstile check off, whatever the developer's ``.env`` says.

    A developer can set ``TURNSTILE_SECRET_KEY`` in ``.env`` to run the real
    widget on localhost.  ``base.py`` calls ``load_dotenv``, so without this
    pin every signup test would call Cloudflare and fail.  The Turnstile tests
    set a secret explicitly, which overrides this.
    """
    settings.TURNSTILE_SECRET_KEY = ""


@pytest.fixture(autouse=True)
def _team_memberships_are_honoured(settings):
    """Pin ``TEAM_MEMBERSHIPS_ENABLED`` on, whatever the developer's ``.env`` says.

    It is a development switch: it sets the signed-in reader's team membership
    aside so both the "buy seats" and the "manage seats" states are reachable
    without making and destroying an organization.  ``base.py`` calls
    ``load_dotenv``, so a developer who turns it off in ``.env`` would
    otherwise turn three tests red — a convenience toggle that can fail the
    suite is worse than no toggle.

    ``TestTheTeamMembershipSwitch`` sets it to ``False`` explicitly, which
    overrides this.
    """
    settings.TEAM_MEMBERSHIPS_ENABLED = True
