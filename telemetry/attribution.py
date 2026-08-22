"""The Crown copyright acknowledgement the reproduction permission requires.

The King's Printer for Ontario permits any person to reproduce Government of
Ontario legislation without charge and without asking first, on three
conditions:

1. the reproduction is accurate;
2. it carries the Crown copyright acknowledgement, in the form
   "© King's Printer for Ontario, ____", with "the year in which the
   statute/regulation was first brought into law" — which this module reads as
   the year it came into force; and
3. it states that it is not an official version.

The first condition is the whole product. The second and third are this
module's job, and they are conditions of the permission rather than good
manners — a surface that reproduces the text without them is reproducing it
outside the permission.

One module owns the sentence because a condition met six different ways on six
surfaces is a condition nobody can check. ``templates/partials/_crown_attribution.html``
is the sentence; this file supplies the one part of it that varies.

The year always comes from a ``Regulation.effective_date``. Nothing here
parses an edition's name, and nothing reads ``filed_date``.

Note what the permission also means for the Terms: it runs to *any person*, so
a reader holds it directly from the King's Printer and not from us. We cannot
narrow it, and the Terms must not read as though we could.

**The permission is not tied to e-Laws, and this sentence must not say it is.**
It covers Government of Ontario legislation, whenever it was made. The King's
Printer confirmed this in writing for the three loaded editions by name — OBC
1997 (O. Reg. 403/97), OBC 2006 (O. Reg. 350/06) and OBC 2012 (O. Reg. 332/12)
— under file C/N 0099/26/C, 2026, and stated that formal permission is not
required at all. All three predate the e-Laws consolidation, so a scope written
around e-Laws would exclude the editions the letter was about.

**It does have one limit.** It does not cover a standard or a model code that a
regulation *adopts by reference* — that document belongs to the body that
publishes it, and reproducing it needs that body's licence. Every edition
loaded today carries its code body as regulation text, so every surface this
module stamps is inside the permission. An edition that ships adopted material
is the case that breaks it, and such an edition needs its own notice rather
than this one.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db.models import Q

from core.models import (
    Regulation,
)

#: The rights holder, named exactly as the acknowledgement requires.
CROWN_HOLDER = "King's Printer for Ontario"


def crown_years_for_provisions(provisions: Iterable[Any]) -> str:
    """The years to name for the provisions a page reproduces.

    The King's Printer asks for "the year in which the statute/regulation was
    **first brought into law**", and ``CodeEditionProvision.origin_regulation``
    is already this codebase's name for the regulation that first enacted a
    provision. So this function is a projection of that property, not a second
    opinion about it.

    Three things follow from the word *first*, and each was got wrong on the
    way here:

    * **Not the amending regulation.** A provision amended in 2024 was still
      first brought into law when it was first enacted. The acknowledgement
      identifies the instrument, and an amendment is not the instrument that
      introduced the text.
    * **Not the edition's base regulation either**, for every provision. A
      provision an amendment *added* was never attested by the edition base —
      OBC 1997 ``3.7.6.3.`` came in with O. Reg. 593/99, not with 403/97. That
      is the case ``origin_regulation`` exists to get right.
    * **Not the edition's name.** An edition is named for the year its base
      regulation was made; this is the year it came into *force*. O. Reg.
      332/12 gives 2014, and OBC 1997's base gives 1998.

    A page reproducing provisions from more than one regulation names each
    year, oldest first. That is the honest answer, not a defect.
    """
    years: set[str] = set()
    for provision in provisions:
        if provision is None:
            continue
        origin = provision.origin_regulation
        if origin is not None:
            _add_year(years, origin.effective_date)
    return ", ".join(sorted(years))


def crown_years_for_regulations(regulations: Iterable[Any]) -> str:
    """The years for a surface that renders regulations rather than provisions.

    The regulation detail page and the amendment chain reproduce a regulation's
    own clause text, so each names itself and no version lookup is needed.
    """
    years: set[str] = set()
    for regulation in regulations:
        if regulation is None:
            continue
        _add_year(years, regulation.effective_date)
    return ", ".join(sorted(years))


def _add_year(years: set[str], stamp: Any) -> None:
    """Add ``stamp``'s year, skipping a missing date rather than inventing one."""
    if stamp is not None:
        years.add(str(stamp.year))


def merge_years(*groups: str) -> str:
    """Combine year strings from different sources into one sorted list.

    A page can learn its years two ways at once — from the versions it renders,
    and from an edition it can only name — and the acknowledgement is one
    sentence, so the two have to arrive as one list rather than two.
    """
    years: set[str] = set()
    for group in groups:
        years.update(part.strip() for part in group.split(",") if part.strip())
    return ", ".join(sorted(years))


def crown_years_for_editions(editions: Iterable[Any]) -> str:
    """The years for a surface that knows an edition and not its versions.

    Used for the free-tier locked previews, which print provision titles for
    editions the reader cannot open and so carry no version to look through.

    Reads each edition's base regulation rather than its name. An edition is
    named for the year its base regulation was *made* — OBC 2012 for
    O. Reg. 332/12 — and this module names the year it came into *force*, which
    for that edition is 2014. Parsing the name would be wrong by two years and
    would look right.
    """
    keys = {getattr(edition, "code_name", edition) for edition in editions}
    matches = Q()
    found = False
    for key in keys:
        code, _, edition_id = str(key or "").partition("_")
        if code and edition_id:
            matches |= Q(edition__code__code=code, edition__edition_id=edition_id)
            found = True
    if not found:
        return ""
    years: set[str] = set()
    for in_force in (
        Regulation.objects.filter(role=Regulation.Role.BASE)
        .filter(matches)
        .values_list("effective_date", flat=True)
    ):
        _add_year(years, in_force)
    return ", ".join(sorted(years))
