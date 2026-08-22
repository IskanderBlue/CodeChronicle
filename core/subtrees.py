"""Walking a provision's subtree, knowing when to stop, and what to show then.

A provision permalink renders the matched provision *and everything under it*,
which is right at the leaf end — an article and its sentences read as one
thing — and wrong at the top: ``OBC_2006/B/Part 9`` is 1,339 provisions and
about 1.9 MB of database reads in one request.

Two surfaces walk a subtree, and both have to stop in the same place and say
the same thing when they do, so the whole rule lives here rather than in
either of them:

* ``core.views.regulation.provision_permalink`` — the reading page and the
  exhibit.
* ``core.views.search.viewer_section_content`` — the search overlay, which
  walks the *parent's* subtree so a reader sees the match in context.

They differ only in which provision they start from.  Both mount
``templates/partials/_provision_contents.html`` over :func:`contents_view`,
because a reader who meets the contents of Part 9 in the overlay and again on
its own page must meet the same list; two lists of one thing that drift is the
failure this module exists to prevent.
"""

from __future__ import annotations

from typing import Any

from django.db import connection
from django.db.models import Count

from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    natural_provision_key,
)
from core.permalinks import provision_permalink_url
from core.seo import last_governed_day

#: How many provisions a page may render as text before it stops walking.
#:
#: In OBC 2006, 95% of provisions have fewer than a dozen descendants, while
#: ``B`` has 2,934 and ``Part 9`` has 1,338.  Nobody reads Part 9 on a screen
#: from top to bottom; they want to know what is in it.  So a page changes
#: character rather than paginating: page 3 of Part 9 is not a thing a code
#: consultant can ask for, and ``?page=`` would multiply the URL count when the
#: point is to cut the work.
#:
#: The switch is by measured size, not by level name, because "section" runs
#: from 0 to 201 descendants in this corpus — the name does not predict the
#: cost.  Measuring also means a differently-shaped edition needs no new rule.
#:
#: On the permalink this also removes a duplicate-text problem.  An article's
#: text used to appear on its own page, its subsection's, its section's, its
#: part's and its division's — five URLs for one text, with nothing to say
#: which is the subject, because the canonical rule picks the highest *version*
#: and says nothing about containment.
CONTENTS_THRESHOLD = 40


def walk_subtree(
    root: CodeEditionProvision,
    *,
    edition: CodeEdition,
    division: str,
    limit: int = CONTENTS_THRESHOLD,
) -> tuple[list[CodeEditionProvision], bool]:
    """``root`` and its descendants, or as many as ``limit`` allows.

    Answers ``(provisions, oversized)``.  ``oversized`` is True when the walk
    stopped early, which is the caller's signal to render something other than
    the whole subtree.

    A generation at a time, so the limit is a stopping condition rather than a
    second query.  It stops on the generation that *would* breach the limit, so
    at worst it loads one generation too many — bare provision rows, where the
    cost avoided is their versions, tables, scans and rendering.

    ``root`` itself is always in the answer, even where one provision already
    breaches the limit.  A page that renders nothing is not a page.
    """
    provisions: list[CodeEditionProvision] = [root]
    frontier = [root.pk]
    while frontier:
        children = list(
            CodeEditionProvision.objects
            .filter(parent_id__in=frontier, edition=edition, division=division)
        )
        if not children:
            return provisions, False
        if len(provisions) + len(children) > limit:
            return provisions, True
        provisions.extend(children)
        frontier = [c.pk for c in children]
    return provisions, False


def descendant_count(provision: CodeEditionProvision, division: str) -> int:
    """How many provisions sit under ``provision``, at any depth.

    :func:`walk_subtree` stops early once it knows the answer is "too many",
    which is the point of it — so the total is not a by-product and has to be
    asked for.  One recursive query answers it in the database rather than
    dragging every id back to say how many there were.

    Worth the query only because the page states the number: a reader told
    their text is not being shown is owed the size of what is being withheld,
    and "too much to show" is a judgement they have no way to check.
    """
    table = CodeEditionProvision._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH RECURSIVE descendants AS (
                SELECT id FROM {table} WHERE id = %s
                UNION ALL
                SELECT child.id
                FROM {table} child
                JOIN descendants ON child.parent_id = descendants.id
                WHERE child.edition_id = %s AND child.division = %s
            )
            SELECT count(*) - 1 FROM descendants
            """,
            [provision.pk, provision.edition_id, division],
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


# ── What a provision contains, when it is too big to show as text ────────
# A permalink shows one provision pinned to one version.  A reader needs to
# walk up to the parent and down to the children — but each related provision
# has its own version timeline, so a single linked version can overlap
# *several* versions of a neighbour.  Links are emitted per overlapping
# version, not per provision.


def related_links(
    provision: CodeEditionProvision,
    ref: CodeEditionProvisionVersion,
    code_name: str,
) -> dict[str, Any]:
    """A neighbour provision plus a link to each version overlapping ``ref``.

    Uses the provision's prefetched ``versions`` cache; the versions whose
    in-force window touches the pinned version's are the ones a reader on
    this page could have been looking at, so each gets its own link.

    The shape a contents row and a navigation row share.  ``_permalink_nav_item.html``
    and ``_provision_contents.html`` both read it, which is why it is public
    rather than private to whichever view built it first.
    """
    versions = sorted(
        (v for v in provision.versions.all() if v.overlaps(ref)),
        key=lambda v: v.version,
    )
    return {
        "provision_id": provision.provision_id,
        # The row names a *different* provision, so its label carries the
        # title (tasks/c-lineage-anchor-text.md).  The last overlapping
        # version's title is the provision's most recent reading inside the
        # pinned window; where a title changed mid-window, each version's own
        # title still shows on its own link below.
        "title": versions[-1].title if versions else "",
        "versions": [
            {
                "version": v.version,
                "title": v.title,
                "effective_date": v.effective_date,
                # The last day this version governed.  The row's tooltip says
                # "to", and the stored end is the first day the text did not
                # apply, so the template must not print that date.
                "last_day": last_governed_day(v.ineffective_date),
                "never_in_force": v.never_in_force,
                "url": provision_permalink_url(
                    code_name, provision.division, provision.provision_id, v.version
                ),
            }
            for v in versions
        ],
    }


def plural(noun: str, count: int) -> str:
    """``"section"`` or ``"sections"``.  Empty noun stays empty."""
    if not noun:
        return ""
    return noun if count == 1 else f"{noun}s"


def _contents_rows(
    provision: CodeEditionProvision,
    ref: CodeEditionProvisionVersion,
    code_name: str,
    division: str,
) -> list[dict[str, Any]]:
    """The direct children of ``provision``, as rows for a table of contents.

    Each row is a :func:`related_links` entry — so the number, the title and
    one link per overlapping version, exactly as the navigation renders a
    neighbour — plus a count of what sits under it.

    The count's noun comes from the rows themselves rather than from an
    assumed part/section/subsection/article ladder.  An edition that nests
    differently then describes itself correctly instead of being mislabelled.
    """
    children = sorted(
        CodeEditionProvision.objects
        .filter(parent_id=provision.pk, edition=provision.edition, division=division)
        .prefetch_related("versions"),
        key=lambda p: natural_provision_key(p.provision_id),
    )
    if not children:
        return []

    # One grouped query for the whole generation below.  Grouping by level as
    # well as by parent is what lets the row name what it is counting.
    tallies: dict[int, dict[str, int]] = {}
    grandchildren = (
        CodeEditionProvision.objects
        .filter(
            parent_id__in=[c.pk for c in children],
            edition=provision.edition,
            division=division,
        )
        .values("parent_id", "level")
        .annotate(n=Count("pk"))
    )
    for row in grandchildren:
        tallies.setdefault(row["parent_id"], {})[row["level"]] = row["n"]

    rows = []
    for child in children:
        by_level = tallies.get(child.pk, {})
        total = sum(by_level.values())
        # The commonest level present, so a generation that mixes levels is
        # named by what most of it is rather than by whichever sorted first.
        noun = max(by_level, key=lambda k: by_level[k]) if by_level else ""
        row = related_links(child, ref, code_name)
        row["level"] = child.level
        row["child_count"] = total
        row["child_noun"] = plural(noun, total)
        rows.append(row)
    return rows


def contents_view(
    provision: CodeEditionProvision,
    ref: CodeEditionProvisionVersion,
    code_name: str,
    division: str,
) -> dict[str, Any]:
    """Everything ``_provision_contents.html`` needs, for any surface.

    One function because the block states a number, and the number has to be
    asked for: :func:`walk_subtree` stops early once it knows the answer is
    "too many", so the total is not a by-product of the walk.  A caller that
    built the rows itself and then reached for the count separately is a
    caller that can get the two out of step.

    The noun is derived from the rows rather than passed in, for the same
    reason it is derived inside :func:`_contents_rows`: a differently-shaped
    edition then describes itself.
    """
    rows = _contents_rows(provision, ref, code_name, division)
    levels = [row["level"] for row in rows if row["level"]]
    return {
        "contents": rows,
        "contents_total": descendant_count(provision, division),
        "contents_noun": plural(
            max(set(levels), key=levels.count) if levels else "", len(rows)
        ),
    }
