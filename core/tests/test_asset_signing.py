"""Tokens on the mirrored assets (``core.asset_signing``).

The exposure being closed: the edge Worker serves R2 directly, so Django is
not in the path and ``core.access`` never sees a request for a scan.  The
``documents/`` keys are sequential, so an edition we gate could be walked page
by page without ever loading a gated page.
"""

import pytest
from django.template import Context, Template
from django.test import override_settings

from config.assets import MIRRORED_PREFIXES, SIGNED_PREFIXES
from core.asset_signing import (
    TOKEN_PARAM,
    asset_token,
    asset_url,
    needs_token,
    token_is_valid,
)


class TestWhichPrefixesAreSigned:
    def test_the_page_scans_are_signed(self):
        assert needs_token("documents/ont_reg_1997_v2/221.webp")

    @pytest.mark.parametrize("prefix", ["laws", "elaws", "amended"])
    def test_the_figure_fragments_are_not(self, prefix):
        # These are referenced from free and paid editions alike, and laws/
        # paths are baked into HTML this product renders verbatim.
        assert not needs_token(f"{prefix}/images/x.webp")

    def test_every_signed_prefix_is_actually_served_from_the_edge(self):
        # A signed prefix the Worker never routes would sign URLs that 404,
        # and the mismatch would only show as broken images.
        assert set(SIGNED_PREFIXES) <= set(MIRRORED_PREFIXES)


class TestTheUrls:
    def test_an_open_asset_keeps_a_bare_path(self):
        assert asset_url("laws/images/x.webp") == "/laws/images/x.webp"

    def test_a_signed_asset_carries_a_token(self):
        url = asset_url("documents/d/1.webp")
        assert url.startswith("/documents/d/1.webp?")
        assert f"{TOKEN_PARAM}=" in url

    def test_an_empty_key_renders_no_src(self):
        # "/" would point an <img> at the site root and fetch the whole page.
        assert asset_url("") == ""

    def test_a_leading_slash_does_not_change_the_token(self):
        assert asset_token("/documents/d/1.webp") == asset_token("documents/d/1.webp")


class TestTheTokenCannotBeGuessed:
    def test_each_key_gets_its_own_token(self):
        # The whole point: holding page 1 must not yield page 2.
        assert asset_token("documents/d/1.webp") != asset_token("documents/d/2.webp")

    def test_a_token_is_stable_across_calls(self):
        # Stability is what lets a cached page and a printed exhibit keep
        # working; see the module docstring on why these do not expire.
        assert asset_token("documents/d/1.webp") == asset_token("documents/d/1.webp")

    def test_the_secret_changes_every_token(self):
        with override_settings(ASSET_SIGNING_KEY="one"):
            first = asset_token("documents/d/1.webp")
        with override_settings(ASSET_SIGNING_KEY="two"):
            second = asset_token("documents/d/1.webp")
        assert first != second

    def test_validation_rejects_a_wrong_token(self):
        assert token_is_valid("documents/d/1.webp", asset_token("documents/d/1.webp"))
        assert not token_is_valid("documents/d/1.webp", asset_token("documents/d/2.webp"))
        assert not token_is_valid("documents/d/1.webp", "")


class TestTheTemplateFilter:
    def _render(self, key: str) -> str:
        template = Template("{% load asset_tags %}{{ key|asset_url }}")
        return template.render(Context({"key": key}))

    def test_it_signs_through_the_template(self):
        rendered = self._render("documents/d/1.webp")
        assert rendered.startswith("/documents/d/1.webp?")
        # Django escapes "&" in templates; with one parameter there is none,
        # but assert the token survives rendering intact.
        assert asset_token("documents/d/1.webp") in rendered

    def test_it_leaves_an_open_asset_alone(self):
        assert self._render("laws/images/x.webp") == "/laws/images/x.webp"
