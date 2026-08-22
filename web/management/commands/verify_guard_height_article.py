"""Check the guard-height article's claims against the corpus in this database.

The article at ``web:guard_height`` renders its historical texts live, and its
hand-written analysis asserts things about them: that the provision number
moved in 2006, that the 1997 text allows 800 mm and the 2006 text does not,
that OBC 2012 holds three separate texts, that a page scan exists, and that
each amendment did the particular thing the section beside it describes.  The
unit tests build their own corpus, so they prove the *view* surfaces those
facts; only this command can say whether the *shipped* corpus still does.

Run it after ``load_edition``, and before publishing or re-sending the article.
It reads and writes nothing.  A failure means the article's prose and the page
it sits on now disagree.
"""

import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core.models import CodeEditionProvision
from corpus.lineage.compare import REDLINE_FLOOR
from data.guard_height_article import OPENING, TRANSITIONS
from search.formatters.formatters import diff_similarity

_TAG = re.compile(r"<[^>]+>")
_ALLOWANCE = re.compile(r"less than\s+800\s*mm", re.IGNORECASE)


def plain_text(html: str | None) -> str:
    """The version's text with tags gone and whitespace flattened.

    Flattening matters: the stored HTML breaks lines inside a sentence, so
    ``"1 070 mm around landings"`` does not match the raw markup.
    """
    return re.sub(r"\s+", " ", _TAG.sub(" ", html or ""))


def allows_800_mm(html: str | None) -> bool:
    """True when this text permits an 800 mm guard.

    Deliberately not ``"800 mm" in html``.  Every edition carries an
    exterior-guard sentence reading "not more than 1 800 mm above the finished
    ground level", so a substring search finds "800 mm" in all of them and
    reports that the 1997 allowance never went away.  Anchoring on "less than"
    separates the height limit from the height *of the drop*.
    """
    return bool(_ALLOWANCE.search(plain_text(html)))


class Command(BaseCommand):
    help = "Check that the corpus still supports the guard-height article's claims."

    def handle(self, *args: Any, **options: Any) -> None:
        failures: list[str] = []
        versions = {}

        # Every version the article draws: the opening text, plus both sides of
        # every transition.  Read from the article's spine rather than
        # restated, so a transition added there is checked here without a
        # second edit — and the command reads the data the page reads, not the
        # page's module.
        refs = [OPENING]
        for _, earlier, later in TRANSITIONS:
            for ref in (earlier, later):
                if ref not in refs:
                    refs.append(ref)

        for edition_id, division, provision_id, number in refs:
            provision = (
                CodeEditionProvision.objects.select_related("edition__code")
                .filter(
                    edition__code__code="OBC",
                    edition__edition_id=edition_id,
                    division=division,
                    provision_id=provision_id,
                )
                .first()
            )
            if provision is None:
                failures.append(
                    f"OBC {edition_id} {provision_id} (division {division!r}) is not loaded."
                )
                continue
            version = provision.versions.filter(version=number).first()
            if version is None:
                failures.append(f"OBC {edition_id} {provision_id} has no version {number}.")
                continue
            versions[(edition_id, provision_id, number)] = version
            self.stdout.write(
                f"  OBC {edition_id} {provision_id} v{number} "
                f"from {version.effective_date}"
            )

        # "The provision number moved" — the article's sharpest claim.
        numbers: dict[str, set[str]] = {
            edition: set() for edition in ("1997", "2006", "2012")
        }
        for edition_id, provision_id, _ in versions:
            numbers[edition_id].add(provision_id)
        if numbers["1997"] != {"9.8.8.2."}:
            failures.append(f"OBC 1997 guard height is {numbers['1997']}, expected 9.8.8.2.")
        if numbers["2006"] != {"9.8.8.3."} or numbers["2012"] != {"9.8.8.3."}:
            failures.append(
                "OBC 2006/2012 guard height is no longer 9.8.8.3. — the article's "
                "renumbering argument depends on it."
            )

        # "The 1997 code allowed 800 mm" — the opening self-test.
        text_1997 = versions.get(("1997", "9.8.8.2.", 0))
        if text_1997 is not None:
            if not allows_800_mm(text_1997.html):
                failures.append("The OBC 1997 text no longer allows an 800 mm guard.")
            if not text_1997.page_images:
                failures.append("The OBC 1997 version has no page scan; the article shows one.")

        # "...and the 2006 code does not."
        for number in (0, 1):
            text = versions.get(("2006", "9.8.8.3.", number))
            if text is not None and allows_800_mm(text.html):
                failures.append(f"OBC 2006 v{number} now allows an 800 mm guard.")

        # "'The 2012 code says' is not a sentence."
        found_2012 = len([key for key in versions if key[0] == "2012"])
        if found_2012 != 3:
            failures.append(f"OBC 2012 holds {found_2012} guard-height texts, expected 3.")

        # The opening table splits the stair into the flight and the landing.
        # The 1997 sentence carries both numbers, so a landing column that
        # reads 900 mm depends on this exact phrase.
        if text_1997 is not None and "900 mm above landings" not in plain_text(text_1997.html):
            failures.append(
                "The OBC 1997 text no longer sets 900 mm above landings; the "
                "opening table's landing column comes from that phrase."
            )

        # "Where the 2012 code gave two answers" — the whole section rests on
        # sentence (5) existing until 2022 and reading Reserved after it.
        for number in (0, 1):
            text = versions.get(("2012", "9.8.8.3.", number))
            if text is None:
                continue
            body = plain_text(text.html)
            for phrase in ("920 mm for required exit stairs", "1 070 mm around landings"):
                if phrase not in body:
                    failures.append(f"OBC 2012 v{number} no longer says '{phrase}'.")

        # The except-lists.  The 2014 section's answer turns on these two
        # phrases and on nothing else: sentence (1) names (2) to (6), which is
        # what lets sentence (2) lower the general 1 070 mm; and sentence (5)
        # is excepted from sentence (6) alone, which is why it and sentence (2)
        # both apply at a landing and the higher figure governs.  A reload that
        # changed either phrase would leave the page reasoning from words the
        # corpus no longer holds.
        for number in (0, 1):
            text = versions.get(("2012", "9.8.8.3.", number))
            if text is None:
                continue
            body = plain_text(text.html)
            for phrase in (
                "Except as provided in Sentences (2) to (6)",
                "Except as provided in Sentence (6), the height of guards",
            ):
                if phrase not in body:
                    failures.append(
                        f"OBC 2012 v{number} no longer says '{phrase}'; the 2014 "
                        "section reads the landing height off that except-list."
                    )

        text_2022 = versions.get(("2012", "9.8.8.3.", 2))
        if text_2022 is not None:
            body = plain_text(text_2022.html)
            if "Reserved" not in body:
                failures.append(
                    "OBC 2012 v2 no longer reads Reserved; the article says the "
                    "revoked sentence is still numbered in the article."
                )
            if "1 070 mm around landings" in body:
                failures.append(
                    "OBC 2012 v2 still sets 1 070 mm around landings, so the "
                    "landing did not drop to 900 mm on 1 January 2022 as the "
                    "article says."
                )
            if "Sentences (2), (3), (4) and (6)" not in body:
                failures.append(
                    "OBC 2012 v2's sentence (1) no longer drops (5) from its "
                    "except-list; the 2022 section says it stopped naming it."
                )
            if "spiral stairs" not in body:
                failures.append(
                    "OBC 2012 v2 no longer carries the spiral-stair words the "
                    "article quotes from sentence (2)."
                )

        # "The 2024 article has no flights sentence" — the claim needs the 2006
        # and 2012 texts to still carry one.
        for edition_id, number in (("2006", 0), ("2006", 1), ("2012", 2)):
            provision_id = "9.8.8.3."
            text = versions.get((edition_id, provision_id, number))
            if text is None:
                continue
            if "except in required exit stairs" not in plain_text(text.html):
                failures.append(
                    f"OBC {edition_id} v{number} no longer carries the flights "
                    "sentence; the 2025 section says the 2024 code dropped it."
                )

        # "1 July 2017: outside only" — one sentence changed, and it is this one.
        text_2017 = versions.get(("2012", "9.8.8.3.", 1))
        if text_2017 is not None and (
            "a house or an individual dwelling unit" not in plain_text(text_2017.html)
        ):
            failures.append(
                "OBC 2012 v1 no longer carries the 2017 exterior wording the "
                "article quotes."
            )

        # Every comparison is drawn as a redline, and the page applies the same
        # floor /compare/ does.  A pair that fell through it would render as two
        # plain panes under prose that says "changed words stand out".
        for slug, earlier_ref, later_ref in TRANSITIONS:
            before = versions.get((earlier_ref[0], earlier_ref[2], earlier_ref[3]))
            after = versions.get((later_ref[0], later_ref[2], later_ref[3]))
            if before is None or after is None:
                continue
            similarity = diff_similarity(before.html, after.html)
            if similarity < REDLINE_FLOOR:
                failures.append(
                    f"The '{slug}' pair now shares {similarity:.0%} of its words, "
                    f"under the {REDLINE_FLOOR:.0%} redline floor, so that section "
                    "shows two plain panes instead of the redline it describes."
                )

        if failures:
            for failure in failures:
                self.stderr.write(self.style.ERROR(f"  {failure}"))
            raise CommandError(
                f"{len(failures)} of the article's claims no longer hold. "
                "Fix the article at templates/guard_height.html before it ships."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"All {len(versions)} versions present; every claim in the "
                "guard-height article still holds."
            )
        )
