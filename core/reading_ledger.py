"""Recording which provision texts an account has been given, on the website.

``api.provisions.record_fetch`` does this for the API, one text to a request.
The website hands over many texts in one render, so this module takes the whole
set a page delivered and writes it in a fixed number of queries.

Why it exists.  A subscriber who can read the corpus can copy the corpus: 8,865
versions carry text, about 10 MB, and a heavy working day is the same order of
magnitude as the whole thing.  No threshold separates them, so the control is a
record rather than a limit — nothing here refuses anything.  What the record
needs is *what an account was given*, and it must be measured the same way on
both surfaces or the two cannot be read together.

Three rules the callers depend on:

* **Record what the page rendered, not what the request named.**  A permalink
  used to write one event naming the matched provision while rendering up to
  forty texts.  An account served the whole corpus then read as about 2%
  coverage, which inverts the signal this ledger exists to produce.
* **Text only.**  Every division, part, section and subsection in this corpus
  has an empty body on purpose.  Delivering a heading delivers nothing anybody
  could copy, and counting headings would inflate every account's coverage
  against a denominator of the same shape.
* **Never fatal.**  A ledger failure must not break a read.  Same contract as
  ``core.events.record_event``.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import reduce
from operator import or_

from coloured_logger import Logger
from django.db.models import F, Q
from django.http import HttpRequest
from django.utils import timezone

from core.models import CodeEditionProvisionVersion, ProvisionFetch

logger = Logger(__name__)


def keys_for(
    versions: Iterable[CodeEditionProvisionVersion],
) -> list[tuple[str, str, str, int]]:
    """The ledger keys for versions that actually carry text.

    The key is the same tuple ``api.provisions.record_fetch`` writes:
    ``edition.code_name`` (``"OBC_2006"`` — the permalink's own form) and the
    bare division letter.  Any other spelling misses
    ``unique_provision_fetch_per_user``, and the account's ledger then splits in
    two with its coverage halved — a failure that reads as a well-behaved
    reader, which is the one failure this ledger cannot afford.
    """
    keys: list[tuple[str, str, str, int]] = []
    for version in versions:
        if not (version.html or "").strip():
            continue
        provision = version.provision
        keys.append((
            provision.edition.code_name,
            provision.division,
            provision.provision_id,
            version.version,
        ))
    return keys


def record_reads(
    request: HttpRequest,
    keys: Iterable[tuple[str, str, str, int]],
    *,
    source: str = ProvisionFetch.Source.WEB,
) -> int:
    """Add every text this page delivered to the reader's ledger.

    Signed-in readers only.  An anonymous response is stored at the edge and
    never reaches Django, so an anonymous ledger would be full of holes it could
    not report — and anonymous means free tier, which is the content we publish
    to crawlers on purpose.

    Three queries whatever the page size: one SELECT for what the account
    already holds among these keys, one insert for the rest, one UPDATE for the
    repeats.

    Answers **how many distinct keys it confirmed**, so a caller can say what
    reached the ledger beside what it handed over.  A failure answers ``0``
    rather than a part count: the writes are not one transaction, so after an
    exception the number written is unknown, and a watch that guesses low
    raises an alarm where a watch that guesses high hides one.  An anonymous
    reader also answers ``0``, which is not a failure — see
    ``core.insights.ledger_health``, which counts signed-in readers only.
    """
    try:
        user = request.user if request.user.is_authenticated else None
        if user is None:
            return 0

        wanted = set(keys)
        if not wanted:
            return 0

        # One OR group per key.  This asks for exactly the rows wanted, which
        # an ``__in`` filter per column cannot do: those match a cross product
        # and need a second pass in Python to remove what they over-matched.
        match = reduce(
            or_,
            (
                Q(code_edition=edition, division=division,
                  provision_id=provision_id, version=version)
                for (edition, division, provision_id, version) in wanted
            ),
        )
        existing = {
            (row.code_edition, row.division, row.provision_id, row.version): row.pk
            for row in ProvisionFetch.objects
            .filter(user=user)
            .filter(match)
            .only("id", "code_edition", "division", "provision_id", "version")
        }

        now = timezone.now()
        fresh = [
            ProvisionFetch(
                user=user,
                code_edition=edition,
                division=division,
                provision_id=provision_id,
                version=version,
                source=source,
                first_fetched_at=now,
                last_fetched_at=now,
            )
            for (edition, division, provision_id, version) in wanted
            if (edition, division, provision_id, version) not in existing
        ]
        if fresh:
            # ``ignore_conflicts`` because two tabs on one page race between the
            # SELECT above and this insert, and the unique constraint raises.
            # The cost of losing that race is one uncounted repeat.
            ProvisionFetch.objects.bulk_create(fresh, ignore_conflicts=True)

        repeat_pks = list(existing.values())
        if repeat_pks:
            # Incremented in the database, not read-then-written, so two
            # requests at once cannot lose a count.
            ProvisionFetch.objects.filter(pk__in=repeat_pks).update(
                fetch_count=F("fetch_count") + 1, last_fetched_at=now
            )
        return len(wanted)
    except Exception as e:  # noqa: BLE001 — a ledger write is never fatal
        logger.error("Error recording reading ledger rows: %s", e)
        return 0


def record_versions(
    request: HttpRequest,
    versions: Iterable[CodeEditionProvisionVersion],
    *,
    source: str = ProvisionFetch.Source.WEB,
) -> tuple[int, int]:
    """``record_reads`` for callers holding version instances.

    Answers ``(delivered, recorded)`` — the texts this page handed over, and
    the ledger keys that reached the database.  A caller stamps both on the
    view event it writes anyway, and ``core.insights.ledger_health`` reads the
    pair back.

    The two numbers come from two functions on purpose, which is the same rule
    ``ledger_health`` is built on: ``record_reads`` swallows every failure, so
    a number it alone produced could not report its own silence.  ``keys_for``
    touches no database and cannot fail the way a write can.

    ``delivered`` counts **distinct** keys, measured exactly as ``recorded``
    is.  Counting the versions instead would report a shortfall on every page
    carrying a heading (no text, so no key) and on a transition (two versions
    of one provision, two keys, one row each).
    """
    keys = keys_for(versions)
    return len(set(keys)), record_reads(request, keys, source=source)
