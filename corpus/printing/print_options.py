"""What an exhibit repeats, and what it does not.

CCM ships a provision's tables twice over for a scanned edition: once inside
the page images — a scanned page contains whatever was printed on it, tables
included — and again as ``ProvisionVersionTable`` rows carrying the same table
as its own image or as extracted HTML.

On the reading page that is not a problem.  The tables are collapsed behind a
disclosure, so a reader opens one only when they want it.  On paper there is
no disclosure: every table prints, and an exhibit that shows the same table
twice invites the question of which copy is the evidence.

So the printable surfaces decide per version:

* A version rendered **from page images** already shows its tables, inside the
  crops.  Its table rows are suppressed.
* A version rendered **from HTML** does not: ``version.html`` carries the
  provision's text and the tables hang off the version separately, so
  suppressing them would drop content that appears nowhere else.

That default is right for every edition we hold, and it is still only a
default.  A reader who finds a scanned table hard to read wants the extracted
copy beside it, and a reader assembling a short exhibit may want no tables at
all — so ``?tables=on`` and ``?tables=off`` say so explicitly, and the print
page carries the link that sets them.
"""

from __future__ import annotations

from typing import Any

#: The explicit values ``?tables=`` accepts.  Anything else — including a
#: missing parameter — means "decide per version", which is the default.
ON = "on"
OFF = "off"


def resolve_tables_mode(raw: str | None) -> str | None:
    """``"on"``, ``"off"``, or ``None`` for the per-version default."""
    return raw if raw in (ON, OFF) else None


def show_tables_for(version: Any, mode: str | None) -> bool:
    """Should this version print its table rows?

    ``version`` is duck-typed on ``page_images`` so the caller can pass either
    a model instance or anything else carrying the field.
    """
    if mode == ON:
        return True
    if mode == OFF:
        return False
    # The default: a scan already shows its tables, extracted HTML does not.
    return not getattr(version, "page_images", None)


def apply_tables_mode(versions: list[Any], mode: str | None) -> bool:
    """Stamp ``show_tables`` on each version; report what the control shows.

    The returned flag is the *page-level* summary the toggle renders: true when
    every rendered version is printing its tables.  A mixed subtree — a scanned
    provision with an HTML-rendered descendant — reads as "not shown", which is
    the honest label for a page where something was suppressed, and the reader
    can still force either state.
    """
    shown = [show_tables_for(version, mode) for version in versions]
    for version, show in zip(versions, shown, strict=True):
        version.show_tables = show
    return bool(shown) and all(shown)


def toggle_query(params: Any, separate: bool) -> str:
    """The query string that flips the tables option, preserving the rest.

    ``params`` is ``request.GET``.  Built here rather than in a template so
    the comparison's two version references survive the toggle — a link that
    dropped them would turn "show the tables" into "which comparison?".
    """
    query = params.copy()
    query["tables"] = OFF if separate else ON
    return query.urlencode()
