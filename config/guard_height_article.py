"""Which versions the guard-height article walks.

The article asks one question — how high must a guard beside a stair in a
house be — and shows every change that moved the answer.  Two things read this
spine: the view that renders the page, and ``verify_guard_height_article``,
which checks that every version named here still exists and still says what
the prose claims.  The command used to import them out of the view module,
which made a management command depend on a view.  They are data, so they sit
with the data.
"""

from __future__ import annotations

#: One version of the guard-height article, as
#: ``(edition_id, division, provision_id, version)``.
Ref = tuple[str, str, str, int]

#: The oldest text, shown in full because the article starts there.  Everything
#: after it is a change *to* it.
OPENING: Ref = ("1997", "", "9.8.8.2.", 0)

#: Every amendment that produced a new text, oldest first, as
#: ``(slug, earlier, later)``.  The slug is how the template addresses one:
#: each section carries prose about that particular change, so the sections
#: cannot be a loop, and a numeric index would not survive a corpus that grows
#: a version in the middle.
#:
#: The provision *number* moves across the first pair: guard height is 9.8.8.2.
#: in OBC 1997 and 9.8.8.3. from OBC 2006 onward, where 9.8.8.2. becomes "Loads
#: on Guards".  That is the article's sharpest fact, so the pairs are written
#: out rather than derived from a single id — no query could find these six by
#: number.
#:
#: OBC 1997 carries no division letter; the later editions are Division B.
#: ``provision_permalink_url`` and ``core.compare`` both route around the empty
#: one.
TRANSITIONS: tuple[tuple[str, Ref, Ref], ...] = (
    ("renumbered", ("1997", "", "9.8.8.2.", 0), ("2006", "B", "9.8.8.3.", 0)),
    ("measured", ("2006", "B", "9.8.8.3.", 0), ("2006", "B", "9.8.8.3.", 1)),
    ("split", ("2006", "B", "9.8.8.3.", 1), ("2012", "B", "9.8.8.3.", 0)),
    ("exterior", ("2012", "B", "9.8.8.3.", 0), ("2012", "B", "9.8.8.3.", 1)),
    ("resolved", ("2012", "B", "9.8.8.3.", 1), ("2012", "B", "9.8.8.3.", 2)),
)

#: There was briefly an ``ASIDES`` tuple beside this one, carrying OBC 2012
#: B 3.4.6.6. — Part 3's exit-stair guard, where "1 070 mm around landings"
#: had been one sentence about exit stairs since OBC 2006.  It was gathered to
#: argue that 9.8.8.3. (5)(b) carried a narrower meaning than it said.  That
#: argument was wrong: (2) and (5)(b) are both minimums, so they never
#: conflicted, and the higher one simply governs.  The section went, and the
#: machinery went with it.  Do not bring either back.
