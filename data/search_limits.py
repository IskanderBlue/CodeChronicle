"""Display limits for search results: how many, and how close a match counts.

Lives in ``config`` rather than ``search.engine.engine`` because both the engine
and ``core.models`` need these: the engine trims to them, the ``User`` model
stores the reader's chosen floor as a field.  ``engine`` imports ``core.models``,
so the constants can't live there without a cycle.
"""

#: Hard ceiling on cards rendered for one search.  Not a preference: a page-size
#: control and a relevance floor are two ways of asking how much you see, and
#: two such controls can disagree in public ("10 OF 78" reads as 68 results
#: hidden for no reason the reader chose).  The floor is the one that decides
#: what counts; this only stops a 400-match query rendering 400 cards.  It is
#: mentioned in the UI *only* when it actually binds.
SEARCH_RESULT_CAP = 100

#: Relevance floor below which a match isn't reported as a *close* match.
#:
#: Chosen against the real corpus (2026-07-28) rather than picked round.  Top
#: scores cluster at 1.6-2.6 whatever the keyword count, so an absolute floor is
#: stabler here than "a fraction of the top score" — the latter moves when the
#: LLM expands a query into more keywords, i.e. it moves without the user's
#: intent changing.  At 0.8 a broad query ("fire separation between dwelling
#: units") keeps ~65 of 769 matches, a focused one ("maintenance inspection")
#: keeps 20 of 85, and a query with exactly one good answer ("trimmer joists")
#: keeps 1 of 50.  The tail it cuts runs down to 0.03.
CLOSE_MATCH_THRESHOLD = 0.8

#: Hard ceiling on a stored floor.  Scores are unbounded in principle but top
#: out around 2.2-3.0 in practice; this only exists so a hand-edited post can't
#: store a value the control could never render back.
MAX_MATCH_THRESHOLD = 5.0

#: Width of a score bucket in the distribution the control is drawn over.
#: 0.05 gives ~40 bars across a typical query's range — fine enough to see
#: where the tail ends, coarse enough to stay a readable payload.
SCORE_BUCKET_WIDTH = 0.05


def coerce_match_threshold(value: object) -> float:
    """Clamp ``value`` to a storable floor, or fall back to the default.

    Continuous rather than one of a few named tiers, because named tiers can't
    keep their promise: measured against the real corpus, a fixed 0.8 returns
    20 results on one query, 90 on another and 1 on a third.  The number only
    means something next to the distribution it's cutting, so the control shows
    that distribution and this just has to accept where the reader put the line.

    Takes ``object`` because every caller is handling untrusted input — a form
    post, a session value written by an older release, or an API query param.
    """
    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
        return CLOSE_MATCH_THRESHOLD
    try:
        floor = float(value)
    except ValueError:
        return CLOSE_MATCH_THRESHOLD
    if floor != floor:  # NaN — compares false against every bound below
        return CLOSE_MATCH_THRESHOLD
    return round(min(MAX_MATCH_THRESHOLD, max(0.0, floor)), 2)


def score_buckets(scores: list[float]) -> list[int]:
    """Counts per ``SCORE_BUCKET_WIDTH`` band, index 0 = [0, width).

    The list the control is drawn over.  Free: the engine has already scored
    and sorted every match by the time this runs.
    """
    if not scores:
        return []
    count = int(max(scores) / SCORE_BUCKET_WIDTH) + 1
    buckets = [0] * count
    for score in scores:
        buckets[min(count - 1, int(score / SCORE_BUCKET_WIDTH))] += 1
    return buckets
