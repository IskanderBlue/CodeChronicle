"""Citation strings a reader pastes into their own document.

The cheapest export, and the only one that travels: a citation lands in a
report we never see, and it has to stand on its own there.  Three formats,
because a factum, a consultant's report and a set of working notes are
different documents and no single string serves them:

* **Legal** follows the McGill Guide, the style Canadian legal writing (and
  the college guides written for construction students) uses for a
  regulation.  The instrument number is the identity, and a point-in-time
  version takes the phrase "as it appeared on <date>" — one date, never a
  range.
* **Report** is how a designer or a code consultant names a provision in the
  body of a report: the edition, the division, the level and number, the
  heading, and the window it governed.  It carries the retrieval line, so the
  URL travels with the sentence somebody actually pastes.
* **Reference** answers a different question from the other two — not "how do
  I cite this" but "why does this text say what it says".  It is the only
  format that names the amending instrument and the amendment still to come,
  which is what a reader reconciling against e-Laws needs.  It is a record
  rather than a sentence, so it stays multi-line and keeps ISO dates beside
  the regulation numbers; it names the provision with the same pinpoint
  Report uses, because one provision with two spellings in one dialog is the
  error this module exists to prevent.

Three rules hold for all of them:

* **Nothing is invented.**  A qualifier we cannot source is dropped, the same
  way ``corpus.seo`` drops an unsourced JSON-LD property.  In particular we do
  not store the instrument's own title ("Building Code"), and the McGill
  guides call the title optional, so the Legal form omits it rather than
  hard-coding a title that would be wrong for the first non-Ontario code.
* **The window is stated in days that were actually governed.**  The stored
  window is half-open — ``effective <= d < ineffective`` — so a citation
  that says "to" must name the day *before* the end date.  Writing the stored
  date claims the text applied on the first day it did not.  See
  :func:`corpus.seo.temporal_coverage`, which documents the same trap.
* **The window closes at the edition's end**, via
  :func:`corpus.seo.effective_window`.  A few provisions outlive their edition
  and carry no end date of their own; reading the version alone reports a
  2006 text as open-ended, which reads as current.

The URL is always the canonical one from :mod:`corpus.seo`, so a citation stays
valid when a reader follows it years later.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from core.code_names import get_code_display_name
from core.models import CodeEdition, CodeEditionProvision, CodeEditionProvisionVersion
from corpus.permalinks import provision_permalink_url
from corpus.seo import base_regulation, effective_window, last_governed_day

#: The three formats, in the order the control offers them.  ``kind`` is what
#: the engagement event records, so the 60-day review can retire one.
LEGAL = "legal"
REPORT = "report"
REFERENCE = "reference"


@dataclass(frozen=True)
class Citation:
    """One ready-to-paste string, with the label its button carries."""

    kind: str
    label: str
    #: What the button's tooltip says the format is for.  A reader who has
    #: never met the McGill Guide needs to be told which button is theirs.
    note: str
    text: str
    #: Whether the string's own line breaks carry meaning.  Legal and Report
    #: are sentences and wrap to the dialog; Reference is a record whose lines
    #: are its structure, so the panel draws it in a ``<pre>``.
    preformatted: bool = False


def _long_date(day: date) -> str:
    """``1 July 2007`` — no leading zero, spelled month.

    ``%-d`` is not portable to Windows, so the zero is stripped rather than
    formatted away.
    """
    return day.strftime("%d %B %Y").lstrip("0")


def _pinpoint(provision: CodeEditionProvision) -> str:
    """``Article 3.2.5.7. of Division B`` — the provision, qualified.

    The bare number is not an identifier: "3.2.5.7." exists in three loaded
    editions and in more than one division.  The level name comes from the
    code's own vocabulary (part, section, subsection, article), which is more
    exact than the McGill ``s`` and is what a reader of the code expects.
    Each qualifier is dropped when it is not known.
    """
    parts: list[str] = []
    if provision.level:
        parts.append(provision.level.capitalize())
    parts.append(provision.provision_id)
    if provision.division:
        parts.append(f"of Division {provision.division}")
    return " ".join(parts)


def _short_pinpoint(provision: CodeEditionProvision) -> str:
    """``Div. B, Article 3.2.5.7.`` — the report-body form of the pinpoint.

    Practice puts the division first and abbreviates it, because a report
    quotes many provisions from one division and the reader scans the number.
    """
    parts: list[str] = []
    if provision.division:
        parts.append(f"Div. {provision.division},")
    if provision.level:
        parts.append(provision.level.capitalize())
    parts.append(provision.provision_id)
    return " ".join(parts)


def _window_phrase(start: date, end: date | None, *, never_in_force: bool) -> str:
    """The in-force window, in the days it actually governed."""
    if never_in_force:
        return "never in force"
    last = last_governed_day(end)
    if last is None:
        return f"in force from {_long_date(start)}"
    if last < start:
        # A zero-length window: a real link in the amendment chain that
        # governed no day.  A range is the wrong shape for it.
        return "never in force"
    return f"in force {_long_date(start)} to {_long_date(last)}"


def in_force_phrase(
    version: CodeEditionProvisionVersion, edition: CodeEdition
) -> str:
    """The window this version governed, in prose, for a surface to print.

    Public so the printable provision and the Report citation state the window
    the same way.  Two spellings of one window on one document is the error
    this prevents — and the half-open end date makes it an easy one.
    """
    start, end = effective_window(version, edition)
    return _window_phrase(start, end, never_in_force=version.never_in_force)


def _headline(
    edition_label: str, provision: CodeEditionProvision, heading: str
) -> str:
    """``OBC 2006, Div. A, Article 1.1.2.4. — Application of Part 9``.

    Report opens with it and Reference opens with it.  One function, because
    the two used to disagree — Reference said ``Div A, S 1.1.2.4.`` for what
    is an Article, which is both a third spelling of one provision and the
    wrong level name.
    """
    head = f"{edition_label}, {_short_pinpoint(provision)}"
    return f"{head} — {heading}" if heading else head


def _retrieval_line(retrieved: date, url: str) -> str:
    """``Retrieved 2026-08-06 from <url>``.

    ISO here, in both formats that carry it, because a retrieval stamp is a
    record of when we looked and not part of the sentence's claim.  Every
    export states one: a historical text with no retrieval date becomes an
    undated claim the moment it leaves the site.
    """
    return f"Retrieved {retrieved.isoformat()} from {url}"


def build_citations(
    provision: CodeEditionProvision,
    version: CodeEditionProvisionVersion,
    *,
    origin: str,
    retrieved: date | None = None,
    provenance_lines: Sequence[str] = (),
) -> list[Citation]:
    """The citation strings for one provision version.

    ``origin`` is ``corpus.seo.site_origin(request)`` — scheme and host, so the
    URL in the citation is absolute.  ``retrieved`` defaults to today; it is a
    parameter so a test can pin it.

    ``provenance_lines`` is the amendment chain from
    ``search.formatters.formatters.provenance_lines`` — base regulation, amending clause,
    next amendment.  It arrives as a parameter rather than being rebuilt here
    because the caller has already loaded that chain, and because a second
    derivation of it would be a second thing to get wrong.  Empty means no
    chain is known, and Reference then carries the heading and the retrieval
    line alone rather than claiming provenance it does not have.

    The URL names **this version**, not the canonical one.  The card asked for
    the canonical URL, and that is right for a crawler: the canonical rule
    concentrates ranking on one page of an amendment chain.  It is wrong for a
    citation.  A citation pins a text to a date — "as it appeared on 1 January
    2014" — and the canonical URL opens the *highest* version, which is a
    different text whenever the reader cited an earlier one.  A reader who
    follows the link would find words the citation does not quote, which is
    the one failure an exhibit cannot survive.  Version permalinks are stable
    in the same way canonical ones are, so nothing is lost by naming the right
    text.
    """
    edition = provision.edition
    retrieved = retrieved or date.today()
    start, end = effective_window(version, edition)
    edition_label = (
        f"{get_code_display_name(edition.code.code)} {edition.edition_id}".strip()
    )

    url = origin + provision_permalink_url(
        edition.code_name,
        provision.division,
        provision.provision_id,
        version.version,
    )

    base_reg = base_regulation(edition)

    # ── Legal (McGill) ──────────────────────────────────────────────────
    # "as it appeared on <date>" takes ONE date, so it names the day the
    # text took this form.  That day is always inside the window, and it is
    # the day a reader checking the citation would look up.
    legal_parts: list[str] = []
    if base_reg:
        legal_parts.append(f"O Reg {base_reg.reg_id}")
    legal_parts.append(_pinpoint(provision))
    if version.never_in_force:
        # No day to name.  Saying "as it appeared on <effective date>" would
        # claim the text stood on a day it did not.
        legal_parts.append("never in force")
    else:
        legal_parts.append(f"as it appeared on {_long_date(start)}")
    legal = ", ".join(legal_parts) + "."

    # ── Report ──────────────────────────────────────────────────────────
    heading = (version.title or "").strip()
    headline = _headline(edition_label, provision, heading)
    report = (
        f"{headline} "
        f"({_window_phrase(start, end, never_in_force=version.never_in_force)}). "
        f"{_retrieval_line(retrieved, url)}"
    )

    # ── Reference ───────────────────────────────────────────────────────
    # The same provision, named the same way, then the chain that produced
    # this text and the stamp that lets somebody else find it again.  The
    # window is deliberately absent: Report states it in prose, and the
    # chain's own dates say when each step took effect, which is the more
    # exact answer to the question this format is for.
    reference = "\n".join([headline, *provenance_lines, _retrieval_line(retrieved, url)])

    return [
        Citation(
            kind=LEGAL,
            label="Legal",
            note="McGill Guide form, for a factum or a legal opinion",
            text=legal,
        ),
        Citation(
            kind=REPORT,
            label="Report",
            note="For the body of a report, with the retrieval line",
            text=report,
        ),
        Citation(
            kind=REFERENCE,
            label="Reference",
            note="The amendment chain, for working notes",
            text=reference,
            preformatted=True,
        ),
    ]
