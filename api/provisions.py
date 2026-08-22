"""Fetching one provision version — the only route by which the API serves text.

A search answers with the map: which provisions, which versions, which days.
A caller reads that the way somebody reads a results page, and asks for the two
or three that look right. This module answers those asks.

The split is deliberate and does two jobs at once. It matches how the product
is actually read, so an API caller does the same work a person does. And it
makes the text **countable**: every provision text that leaves here is one
request, recorded against one account in ``ProvisionFetch``. Bundled a hundred
to a search response, nothing could say which provisions an account had taken,
which is why volume was the only available signal and volume tells us nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import F, Q
from django.utils import timezone

from api.schemas import ProvisionOut, TableOut, VersionOut, clause_citation
from core.code_names import edition_display_name
from core.models import (
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionFetch,
    User,
)
from core.permalinks import provision_permalink_url
from core.provision_levels import CONTAINER_LEVELS
from core.seo import last_governed_day


def find_provision(edition: str, division: str, provision_id: str) -> CodeEditionProvision | None:
    """The provision named by a search result's own fields, or ``None``.

    ``edition`` is the key a search result and ``/api/codes`` both print, e.g.
    "OBC_2012"; it splits on the underscore the way a permalink does.
    ``division`` is a bare letter, and empty for an edition published without
    divisions — which is why these arrive as query parameters rather than as
    path segments: an empty segment is not a path.
    """
    code, _, edition_id = edition.partition("_")
    if not code or not edition_id or not provision_id:
        return None
    return (
        CodeEditionProvision.objects.select_related("edition__code", "parent")
        .filter(
            edition__code__code=code,
            edition__edition_id=edition_id,
            division=division,
            provision_id=provision_id,
        )
        .first()
    )


def version_in_force(
    provision: CodeEditionProvision, on: date
) -> CodeEditionProvisionVersion | None:
    """The version governing ``provision`` on ``on``, or ``None``.

    The window is half-open — ``effective_date <= on < ineffective_date`` —
    which is the same test the search runs, so the API cannot disagree with
    itself about which text applied on a day.

    A zero-width version is skipped: one filed and superseded on the same day
    governed nothing, and answering with it would name a text that never
    applied to anybody's building.
    """
    return (
        provision.versions.filter(effective_date__lte=on)
        .filter(Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=on))
        .exclude(ineffective_date=F("effective_date"))
        .order_by("-version")
        .first()
    )


def record_fetch(user: User, version: CodeEditionProvisionVersion) -> bool:
    """Add this text to the account's ledger. Returns whether it was new.

    Written on the way out, once the fetch has succeeded, because the ledger
    answers "what does this account hold" and a refused request delivered
    nothing. The increment is done in the database rather than read-then-write,
    so two calls at once cannot lose a count.
    """
    provision = version.provision
    _, created = ProvisionFetch.objects.get_or_create(
        user=user,
        code_edition=provision.edition.code_name,
        division=provision.division,
        provision_id=provision.provision_id,
        version=version.version,
        # Named, never defaulted. The website writes to this table too, and the
        # two populations are read differently — a website row arrives in a
        # batch from one page render, an API row is one deliberate ask.
        defaults={"fetch_count": 1, "source": ProvisionFetch.Source.API},
    )
    if not created:
        ProvisionFetch.objects.filter(
            user=user,
            code_edition=provision.edition.code_name,
            division=provision.division,
            provision_id=provision.provision_id,
            version=version.version,
        ).update(fetch_count=F("fetch_count") + 1, last_fetched_at=timezone.now())
    return created


def provision_out(version: CodeEditionProvisionVersion) -> ProvisionOut:
    """Project one version onto the API's shape.

    Named fields only, exactly as ``api.schemas.result_out`` does: text reaches
    a caller because somebody decided it should.
    """
    provision = version.provision
    edition = provision.edition.code_name
    clause: Any = version.last_contributing_clause
    return ProvisionOut(
        id=provision.provision_id,
        title=version.title or "",
        division=provision.division,
        edition=edition,
        edition_name=edition_display_name(edition),
        parent_id=provision.parent.provision_id if provision.parent else "",
        url=provision_permalink_url(
            edition, provision.division, provision.provision_id, version.version
        ),
        html=version.html or "",
        is_container=provision.level in CONTAINER_LEVELS,
        tables=[
            TableOut(
                id=table.table_id,
                caption=table.caption,
                html=table.html,
                notes=table.notes,
            )
            for table in version.tables.all()
        ],
        version=VersionOut(
            number=version.version,
            effective_date=version.effective_date,
            ineffective_date=version.ineffective_date,
            last_governed_day=last_governed_day(version.ineffective_date),
            is_base=version.version == 0,
            amended_by=clause_citation(clause),
        ),
    )
