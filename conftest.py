"""Shared pytest fixtures.

Content gating (core.access) is unconditional, so any anonymous request to a
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
