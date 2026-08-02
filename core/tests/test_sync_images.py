"""Tests for the asset mirror — which trees are published, and from where.

The defect these guard against is silent. ``sync_images`` reported success
while publishing 96 of the 532 objects production needs, because the trees
live under two CCM roots and the command took one; and ``elaws/`` had a bucket
prefix with no edge route, so it would have 404'd even once uploaded. Neither
failure raised anything. So the tests check the *lists* against each other,
which is where the drift happens.
"""

import re
from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from config.assets import DEFAULT_ASSET_SOURCES, MIRRORED_PREFIXES
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionVersionAsset,
)

# parents[2] is this repository; parents[3] is the directory holding it and
# its sibling repositories.
TERRAFORM_VARIABLES = (
    Path(__file__).resolve().parents[3]
    / "CodeChronicleTerraform" / "modules" / "cloudflare" / "variables.tf"
)


def _tree(root: Path, prefix: str, *names: str) -> Path:
    """Create ``root/prefix`` holding one file per name."""
    directory = root / prefix
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text(name, encoding="utf-8")
    return directory


class TestThePrefixListIsOneList:
    """Three places name these prefixes. Two are in this repository."""

    def test_the_dev_urlconf_serves_exactly_the_mirrored_prefixes(self):
        """Django serves these from disk when DEBUG is on. A prefix served in
        development and absent from the published set works locally and 404s
        in production — the failure is invisible until a reader hits it."""
        source = (
            Path(__file__).resolve().parents[2]
            / "code_chronicle" / "urls.py"
        ).read_text(encoding="utf-8")
        assert "for _prefix in MIRRORED_PREFIXES:" in source, (
            "the URLconf must loop over the shared constant, not its own copy"
        )

    @pytest.mark.skipif(
        not TERRAFORM_VARIABLES.exists(),
        reason="the Terraform repository is not checked out beside this one",
    )
    def test_the_terraform_routes_cover_every_mirrored_prefix(self):
        """The edge Worker only sees a path that a route sends to it. This is
        the check that ``elaws/`` failed: it was in the bucket and in no
        route, so every request for it reached the origin and 404'd."""
        source = TERRAFORM_VARIABLES.read_text(encoding="utf-8")
        match = re.search(
            r'variable "asset_path_prefixes".*?default\s*=\s*\[(.*?)\]',
            source, re.DOTALL,
        )
        assert match, "asset_path_prefixes must declare a default list"
        routed = set(re.findall(r'"([^"]+)"', match.group(1)))
        assert set(MIRRORED_PREFIXES) == routed, (
            "every mirrored prefix needs an edge route, and a route with no "
            "prefix is dead weight"
        )


@pytest.mark.django_db
class TestTheSourceRoots:
    """CCM splits the trees across two roots, so the sync searches both."""

    def test_both_default_roots_are_searched(self, tmp_path):
        """The whole bug in one test: prefixes spread over two roots must all
        publish, not just the ones under the first root."""
        first, second, dest = (
            tmp_path / "outputs", tmp_path / "images", tmp_path / "dest"
        )
        _tree(first, "laws", "a.png")
        _tree(second, "documents", "b.webp")
        _tree(second, "elaws", "c.jpg")

        call_command(
            "sync_images", backend="local", dest=str(dest),
            source=[str(first), str(second)],
        )

        assert (dest / "laws" / "a.png").exists()
        assert (dest / "documents" / "b.webp").exists()
        assert (dest / "elaws" / "c.jpg").exists()

    def test_the_first_root_holding_a_prefix_wins(self, tmp_path):
        """Order decides, so a stale second copy cannot overwrite the good
        one. Order is the only rule; there is no merge."""
        first, second, dest = (
            tmp_path / "one", tmp_path / "two", tmp_path / "dest"
        )
        (first / "laws").mkdir(parents=True)
        (first / "laws" / "a.png").write_text("winner", encoding="utf-8")
        (second / "laws").mkdir(parents=True)
        (second / "laws" / "a.png").write_text("loser-x", encoding="utf-8")

        call_command(
            "sync_images", backend="local", dest=str(dest),
            source=[str(first), str(second)],
        )

        assert (dest / "laws" / "a.png").read_text(encoding="utf-8") == "winner"

    def test_a_prefix_no_root_holds_publishes_nothing_and_warns(
        self, tmp_path, caplog
    ):
        """It must not read as success. Reporting the absent tree is the
        signal that was missing when production ran a quarter-published."""
        source, dest = tmp_path / "src", tmp_path / "dest"
        _tree(source, "laws", "a.png")

        with caplog.at_level("WARNING"):
            call_command(
                "sync_images", backend="local", dest=str(dest),
                source=[str(source)],
            )

        assert not (dest / "documents").exists()
        assert "documents" in caplog.text
        assert "elaws" in caplog.text

    def test_an_explicit_source_that_does_not_exist_is_an_error(self, tmp_path):
        """A typed path that is wrong is an operator mistake, not a partial
        corpus to publish quietly."""
        with pytest.raises(CommandError):
            call_command(
                "sync_images", backend="local", dest=str(tmp_path / "dest"),
                source=[str(tmp_path / "no-such-root")],
            )

    def test_the_defaults_name_two_distinct_roots(self):
        """One root cannot hold both an outputs tree and an intermediates
        tree, so a single default would reintroduce the bug."""
        assert len(set(DEFAULT_ASSET_SOURCES)) == 2


@pytest.mark.django_db
class TestTheManifest:
    """Which registered assets the sync checks, and reports as absent."""

    def test_a_version_scoped_asset_is_reported_when_the_bytes_are_absent(
        self, tmp_path, caplog,
    ):
        """The check the corpus was missing.

        A body-only reference has no ``RegulationAsset`` row, so the sync saw
        nothing to look for and reported ``missing_manifest=0`` while readers
        got a 404.  Registering the version scope is what makes the gap
        visible.
        """
        edition = CodeEdition.objects.create(
            code=Code.objects.create(code="OBC"),
            edition_id="2012",
            year=2012,
            effective_date=date(2012, 1, 1),
        )
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id="1.1.1.1.",
            level=CodeEditionProvision.Level.ARTICLE, division="B",
        )
        version = CodeEditionProvisionVersion.objects.create(
            provision=provision, version=0, effective_date=date(2012, 1, 1),
        )
        ProvisionVersionAsset.objects.create(
            version=version,
            path="laws/images/en/120332_eV020_files/image004.gif",
            sha256="c" * 64,
        )

        source, dest = tmp_path / "src", tmp_path / "dest"
        _tree(source, "laws", "unrelated.gif")

        with caplog.at_level("WARNING"):
            with pytest.raises(CommandError):
                call_command(
                    "sync_images", backend="local", dest=str(dest),
                    source=[str(source)], prefix="laws", strict_manifest=True,
                )

        assert "120332_eV020_files/image004.gif" in caplog.text
