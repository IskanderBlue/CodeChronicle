"""Tell the people who asked for an edition that it has landed.

The edition-request band promises it in so many words: *tell us the code and
the year you work with, and we will tell you when it lands*. Nothing kept that
promise. The addresses sat in ``edition_requests`` and the first edition to
ship would have found them months old with nobody remembering to write.

This is deliberately **not** a mailing-list system. It is one command, run by
hand when an edition ships, that prints what it would do and only sends when
told to::

    # See who would hear about it, and read the message yourself first.
    python manage.py notify_edition_requests \\
        --about "OBC 1997" \\
        --news "The 1997 Ontario Building Code is now on CodeChronicle." \\
        --search "guards and handrails for a stairway" --date 1999-06-01 \\
        --match 1997

    # Same command with --send appended, once the report reads right.

Four rules, from ``tasks/b-keep-the-promise-to-tell-them.md``:

* **Only write to somebody about the thing they asked for.** A request for the
  BC code is not permission to announce an Ontario edition. The Privacy Policy
  says so, which makes it a promise as well as good manners. This command does
  not decide who matches — a human does, with ``--match`` or ``--ids``, and
  the report prints each reader's own words beside their address so the human
  can check. ``code_text`` is free text and no parser should be trusted to
  read "the 1990 OBC" as an OBC 1997 load.
* **Print, then send.** A dry run is the default. An accidental send to every
  address in the table cannot be taken back.
* **Every send is recorded.** ``notified_about`` collects the labels already
  announced to a row, so a re-run after a failure writes only to the people it
  did not reach, and nobody hears the same news twice.
* **An unsubscribe line, even though this is not a mailing list.** One
  sentence with an address to write to costs nothing.

The message is four sentences, and two of them are yours. The news and the
link change with every edition and are typed on the command line; the last two
never change and live here.
"""

from typing import Any
from urllib.parse import urlencode

from django.contrib.sites.models import Site
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from core.models import EditionRequest

#: Sentence 3 and sentence 4.  Fixed, because they say nothing about the
#: edition — they say what this message is and who sent it.
UNSUBSCRIBE = (
    "You are getting this once, because you asked us for this edition; "
    "reply, or write to privacy@codechronicle.ca, and we will not write again."
)
WHO_WE_ARE = (
    "CodeChronicle publishes historical Canadian building codes, so you can "
    "read the text that was in force on the date that matters."
)


class Command(BaseCommand):
    help = "Tell edition requesters that the edition they asked for has landed."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--about",
            required=True,
            help=(
                "The edition label, e.g. 'OBC 1997'. Recorded against each row "
                "so nobody hears the same news twice, so keep it stable across "
                "re-runs of one announcement."
            ),
        )
        parser.add_argument(
            "--news",
            required=True,
            help="Sentence one: what shipped. Written fresh for each edition.",
        )
        parser.add_argument(
            "--link",
            default="",
            help="Sentence two: a URL to open. Use this, or --search.",
        )
        parser.add_argument(
            "--search",
            default="",
            help=(
                "Build the link from a query instead of typing a URL. The "
                "address runs the search on arrival, so the reader lands on "
                "results rather than an empty box."
            ),
        )
        parser.add_argument(
            "--date",
            default="",
            help="The AS-OF date for --search, e.g. 1999-06-01. Strongly advised: "
                 "without one the search runs at the corpus default date.",
        )
        parser.add_argument(
            "--match",
            default="",
            help="Select rows whose request text contains this, case-insensitively.",
        )
        parser.add_argument(
            "--ids",
            nargs="+",
            type=int,
            default=[],
            help="Select rows by id. Use when --match cannot express the group.",
        )
        parser.add_argument(
            "--send",
            action="store_true",
            help="Actually send. Without it the command only prints.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Write again to rows already told about this label.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        about = options["about"].strip()
        rows = self._select(options)
        body = self._body(options)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Message about {about!r}:"))
        self.stdout.write("")
        for line in body.splitlines():
            self.stdout.write(f"    {line}")
        self.stdout.write("")

        groups, skipped = self._group(rows, about, force=options["force"])

        for reason, entries in skipped.items():
            for entry in entries:
                self.stdout.write(
                    self.style.WARNING(f"  skip  #{entry.id}  {reason}: {entry.code_text!r}")
                )

        if not groups:
            self.stdout.write(self.style.WARNING("Nobody to write to."))
            return

        for address, members in groups.items():
            asked = "; ".join(f"#{r.id} {r.code_text!r}" for r in members)
            self.stdout.write(f"  send  {address}  asked for {asked}")

        self.stdout.write("")
        if not options["send"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run: {len(groups)} would be written to. "
                    "Add --send to write."
                )
            )
            return

        subject = f"{about} is now on CodeChronicle"
        sent = 0
        for address, members in groups.items():
            try:
                send_mail(subject, body, None, [address], fail_silently=False)
            except Exception as exc:  # noqa: BLE001 — one bad address must not
                # stop the rest, and the re-run must not re-write to those the
                # send already reached, which is what the stamp below gives us.
                self.stderr.write(self.style.ERROR(f"  failed {address}: {exc}"))
                continue
            self._stamp(members, about)
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Wrote to {sent}."))

    def _select(self, options: dict[str, Any]) -> list[EditionRequest]:
        """The rows a human chose.  Never rows this command chose by itself."""
        match = options["match"].strip()
        ids = options["ids"]
        if not match and not ids:
            raise CommandError(
                "Give --match or --ids. This command does not decide by itself "
                "which requests an edition answers; free text is free text."
            )
        criteria = Q()
        if match:
            criteria |= Q(code_text__icontains=match)
        if ids:
            criteria |= Q(id__in=ids)
        return list(EditionRequest.objects.filter(criteria).order_by("id"))

    def _body(self, options: dict[str, Any]) -> str:
        """Four sentences.  Two typed on the command line, two from up top."""
        link = options["link"].strip() or self._search_url(options)
        if not link:
            raise CommandError("Give --link or --search: the message needs somewhere to go.")
        return "\n\n".join([options["news"].strip(), link, UNSUBSCRIBE, WHO_WE_ARE])

    def _search_url(self, options: dict[str, Any]) -> str:
        """A search the reader arrives on already run.

        ``/search/?q=…&d=…`` seeds the query box and the AS-OF picker and then
        runs itself, so the link opens results.  The date matters: the picker
        overrides whatever date the parser reads out of the text, so a link
        without one searches at the corpus default and can answer a question
        about 1999 with a later edition.
        """
        query = options["search"].strip()
        if not query:
            return ""

        # Django ships the Site row reading "example.com" and nothing in the
        # app writes to it, so an environment where ``set_site_domain`` has
        # not run builds a dead link.  That failure is silent — the message
        # sends, and the reader finds nothing — so it is refused here rather
        # than left for somebody to notice in their own inbox.
        domain = Site.objects.get_current().domain
        if domain == "example.com":
            raise CommandError(
                "The Site row still reads 'example.com', so --search would build "
                "a dead link. Run set_site_domain first, or pass --link."
            )

        params = {"q": query}
        if options["date"].strip():
            params["d"] = options["date"].strip()
        return f"https://{domain}/search/?{urlencode(params)}"

    def _group(
        self, rows: list[EditionRequest], about: str, *, force: bool
    ) -> tuple[dict[str, list[EditionRequest]], dict[str, list[EditionRequest]]]:
        """One message per address, and the rows each message answers.

        Grouped because two rows can carry one address, and two copies of one
        announcement is exactly the mailing list we said this was not.  Rows
        outside this send are untouched: somebody who also asked for another
        edition is still owed a message about that one.
        """
        groups: dict[str, list[EditionRequest]] = {}
        skipped: dict[str, list[EditionRequest]] = {"no address": [], "already told": []}
        for row in rows:
            address = (row.email or "").strip().lower()
            if not address:
                # The need was the valuable field; the address was optional.
                skipped["no address"].append(row)
                continue
            if about in (row.notified_about or []) and not force:
                skipped["already told"].append(row)
                continue
            groups.setdefault(address, []).append(row)
        return groups, skipped

    def _stamp(self, rows: list[EditionRequest], about: str) -> None:
        now = timezone.now()
        for row in rows:
            told = list(row.notified_about or [])
            if about not in told:
                told.append(about)
            row.notified_about = told
            row.notified_at = now
            row.save(update_fields=["notified_about", "notified_at"])
