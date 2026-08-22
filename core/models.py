"""
Core models for CodeChronicle.
"""

import hashlib
import re
import secrets
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Count, Max, Min
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone
from djstripe.models import Customer, Subscription

from core.provision_notes import GroupedNotes, group_notes
from data.search_limits import CLOSE_MATCH_THRESHOLD


def natural_provision_key(provision_id: str) -> tuple[tuple[int, int, str], ...]:
    """Sort key that orders 'A.1.10.' after 'A.1.9.' (numeric segments).

    Each segment is wrapped as ``(kind, number, text)`` so numeric and word
    segments never compare directly — a subtree can mix shapes like 'Part 3'
    and '3.17.', and a bare ``(int | str)`` tuple would raise ``TypeError`` on
    the cross-type compare.  Lives here rather than in a view because every
    surface that lists provisions needs the same order.
    """
    parts = re.split(r"(\d+)", provision_id or "")
    return tuple(
        (0, int(p), "") if p.isdigit() else (1, 0, p.lower())
        for p in parts if p
    )


class UserManager(BaseUserManager["User"]):
    """
    Custom manager for the email-only User model.
    """

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for CodeChronicle.
    Uses email as the primary identifier and eliminates the username field.
    """

    # Reverse relation — declared for Pyright (no plugin); the append-only log
    # of this user's Terms / Privacy Policy acceptances (see ``TermsAcceptance``).
    terms_acceptances: "models.Manager[TermsAcceptance]"
    #: Reverse relation — the user's direct-API credentials (see ``ApiKey``).
    api_keys: "models.Manager[ApiKey]"
    #: Reverse relation — which provision texts this account has been given,
    #: on either surface (see ``ProvisionFetch``).
    provision_fetches: "models.Manager[ProvisionFetch]"
    #: Reverse relation — this account's seats (see ``Membership``).
    memberships: "models.Manager[Membership]"
    #: Per-instance cache for :attr:`has_active_subscription`.  Not a field.
    _has_active_subscription: "bool | None" = None

    email = models.EmailField(unique=True)

    # Flags
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    pro_courtesy = models.BooleanField(
        default=False, help_text="Grant Pro status without Stripe subscription"
    )
    date_joined = models.DateTimeField(default=timezone.now)

    # Relevance floor for a "close match". Everything a search reports —
    # results, counts, the Pro teaser — is measured above this line.
    # Continuous, not a set of named tiers: a fixed cutoff is not a fixed idea
    # of closeness (0.8 returns 20 results on one query and 1 on another), so
    # the control draws the query's score distribution and the reader puts the
    # line where the tail starts. This just stores where they left it.
    match_threshold = models.FloatField(
        default=CLOSE_MATCH_THRESHOLD,
        help_text="Minimum relevance score for a result to count as a close match.",
    )

    # Explicit annotation so Pyright (no plugin) resolves UserManager methods
    # like create_user, rather than falling back to the base Manager.
    objects: "UserManager" = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.email

    @property
    def has_active_subscription(self) -> bool:
        """Whether this account may read every edition.

        Two reasons, and no third:

        1. The explicit courtesy flag on the user.
        2. A seat: an organization this user belongs to, in a role that grants
           access, holds a subscription that is ``active`` or ``trialing``.

        Every subscription reaches a person through a ``Membership``, the
        buyer's own included — somebody who buys for themselves gets an
        organization of one.  So there is no separate branch for an individual
        subscription, and no way for the two to answer differently.

        The answer is cached on the instance.  This property runs on gated
        page renders, and nearly all traffic here is crawlers, so a repeated
        render must not pay for the join again.  The cache lives as long as
        the instance does, which is one request.
        """
        if self.pro_courtesy:
            return True

        if self._has_active_subscription is not None:
            return self._has_active_subscription

        answer = Subscription.objects.filter(
            customer__subscriber__memberships__user=self,
            customer__subscriber__memberships__role__in=Membership.SEAT_ROLES,
            stripe_data__status__in=["active", "trialing"],
        ).exists()
        self._has_active_subscription = answer
        return answer

    @property
    def latest_terms_acceptance(self) -> "TermsAcceptance | None":
        """The user's most recent Terms / Privacy Policy acceptance, or None.

        ``-id`` breaks the tie, and it is not decoration: ``accepted_at`` is
        ``auto_now_add``, so two acceptances written in the same second sort
        non-deterministically (Postgres heap order), and this property decides
        whether a reader meets the re-acceptance wall.  Without the tiebreak a
        double-submit could leave the newer row invisible and the reader walled
        out of an agreement they had just accepted.  Same reasoning as
        ``CodeEditionProvisionVersion.last_contributing_clause``.
        """
        return self.terms_acceptances.order_by("-accepted_at", "-id").first()

    def has_accepted_terms(self, version: str) -> bool:
        """Whether this user has a recorded acceptance of Terms ``version``."""
        return self.terms_acceptances.filter(terms_version=version).exists()

    def has_accepted_privacy(self, version: str) -> bool:
        """Whether this user has a recorded acceptance of Privacy ``version``.

        Separate from :meth:`has_accepted_terms` because the two documents are
        versioned separately — a user can be current on one and not the other,
        which is the whole reason the stamps were split.
        """
        return self.terms_acceptances.filter(privacy_version=version).exists()


class TermsAcceptance(models.Model):
    """Append-only record of a user's acceptance of the Terms of Service /
    Privacy Policy.

    One immutable row per acceptance event — written at signup (clickwrap) and
    on any future re-acceptance prompt — so the full history (which version,
    when, and from where) is preserved as evidence rather than overwritten. The
    account-audit counterpart to ``AuthEvent``: ``user`` is ``SET_NULL`` so the
    record outlives the account, with ``email`` mirrored so a row stands on its
    own. Written in the signup flow; see ``accounts.forms.CustomSignupForm``.
    """

    # Auto pk, plugin-only — declared for Pyright.
    id: int

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="terms_acceptances",
        null=True,
        blank=True,
    )
    # The email at acceptance time, mirrored so the row reads on its own even
    # after the user is deleted (``user`` goes NULL).
    email = models.CharField(max_length=254, blank=True, default="")
    terms_version = models.CharField(max_length=20)
    #: The Privacy Policy version accepted in the same act.
    #:
    #: Recorded separately because the two documents change independently.
    #: One stamp for both forced a choice with no right answer whenever only
    #: one changed: bump it and the record dates the *other* document falsely,
    #: or leave it and the record points at text that has since changed.  Two
    #: stamps make the record say exactly what the reader saw.
    #:
    #: Blank only on rows written before the split (migration 0047 backfills
    #: them with "2026-06-17", the Privacy Policy version those users actually
    #: accepted).
    privacy_version = models.CharField(max_length=20, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "terms_acceptances"
        verbose_name = "Terms Acceptance"
        verbose_name_plural = "Terms Acceptances"
        ordering = ["-accepted_at"]
        indexes = [
            models.Index(fields=["user", "accepted_at"]),
            models.Index(fields=["terms_version"]),
            models.Index(fields=["privacy_version"]),
        ]

    def __str__(self) -> str:
        who = self.email or (self.user.email if self.user else "?")
        return (
            f"{who} accepted Terms {self.terms_version} / "
            f"Privacy {self.privacy_version or '?'}"
        )


class QueryPrompt(models.Model):
    """
    Store versioned LLM prompts to allow cache invalidation when logic changes.
    """

    prompt_hash = models.CharField(max_length=64, unique=True, db_index=True)
    content = models.TextField()  # Full system prompt + tool definition
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prompt {self.prompt_hash[:8]}"


class QueryCache(models.Model):
    """
    Cache parsed LLM parameters to reduce API costs.
    """

    query_hash = models.CharField(max_length=64, unique=True, db_index=True)
    raw_query = models.TextField()
    parsed_params = models.JSONField()
    llm_model = models.CharField(max_length=50)
    prompt = models.ForeignKey(QueryPrompt, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    hits = models.IntegerField(default=1)
    # True when ``parsed_params["date"]`` was the LLM's "no date mentioned ->
    # use today" default (i.e. equalled today at parse time).  Such a parse is
    # only valid for that day, so the parser treats the row as stale once the
    # date rolls (see ``search.llm.llm_parser.parse_user_query``).  An explicit /
    # historical date is stable and stays cached indefinitely.
    date_is_relative = models.BooleanField(default=False)

    class Meta:
        db_table = "query_cache"
        verbose_name = "Query Cache"
        verbose_name_plural = "Query Caches"


#: What makes two searches **the same question**: the words, and the date the
#: search ran at.  The same words at two dates are two questions — asking what
#: the code said in 2005 and again in 2015 is most of what this product is for.
#:
#: ``query_date`` is an annotation, not a column; see
#: :func:`_with_question_key`.  It carries the same name the rest of the
#: product uses for this value — ``web.views.search`` reads
#: ``parsed_params["date"]`` into a context key of that name, and the
#: templates render it — because it is the same value in a different form.
QUESTION_FIELDS = ("query", "query_date")


def _with_question_key(searches: "models.QuerySet[SearchHistory]") -> "models.QuerySet[SearchHistory]":
    """Annotate the question's date so it can be selected and grouped on.

    The date lives inside the ``parsed_params`` JSON.  ``KeyTextTransform`` is
    used rather than the ``parsed_params__date`` lookup because only an
    expression can join a ``GROUP BY``; on a stored string the two return the
    same value, and a missing key gives ``None`` either way.
    """
    return searches.annotate(query_date=KeyTextTransform("date", "parsed_params"))


def question_keys(searches: "models.QuerySet[SearchHistory]") -> "models.QuerySet":
    """The distinct questions in ``searches``, as ``(words, date)`` pairs.

    ``web.middleware`` charges an anonymous reader per question, and
    ``web.views.history`` shows one card per question.  Both used to spell the
    key by hand, and each said in a comment that it agreed with the other.  If
    one key widens and the other does not, a reader is charged for a search
    they cannot find in their own history.

    **The address key is wider, and stays wider.**
    ``web.views.search._push_search_url`` also writes ``occupancy``,
    ``storeys``, ``area`` and ``area_unit``.  That is correct and must not be
    folded in here: the address has to reproduce the *page*, and the building
    changes the order of the results — but re-ranking one question is not
    asking a second one.
    """
    return _with_question_key(searches).values_list(*QUESTION_FIELDS).distinct()


def grouped_by_question(searches: "models.QuerySet[SearchHistory]") -> "models.QuerySet":
    """One row per question, ready for aggregates such as ``Count`` or ``Max``.

    The caller must finish with an explicit ``order_by``.  ``Meta.ordering`` is
    ``-timestamp``, which would otherwise join the ``GROUP BY`` and split every
    question into one row per run.  See :func:`question_keys` for what a
    question is.
    """
    return _with_question_key(searches).values(*QUESTION_FIELDS)


class SearchHistory(models.Model):
    """
    Track user search history for analytics and rate limiting.
    """

    # Auto pk, plugin-only — declared for Pyright.
    id: int

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="searches",
        null=True,  # Allow anonymous searches
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    query = models.TextField()
    parsed_params = models.JSONField(default=dict)
    result_count = models.IntegerField(default=0)
    top_results = models.JSONField(default=list)  # Store minimal metadata for quick links
    timestamp = models.DateTimeField(auto_now_add=True)

    class Source(models.TextChoices):
        WEB = "web", "Website"
        API = "api", "Direct API"

    # Which surface ran it.  Two jobs: the API's daily quota counts these rows
    # and must not count somebody's reading on the website, and a run of
    # automated searches is only visible as such if the rows say where they
    # came from.  Defaults to the website, so every row written before this
    # field existed reads as what it was.
    source = models.CharField(
        max_length=8, choices=Source.choices, default=Source.WEB, db_index=True
    )

    class Meta:
        db_table = "search_history"
        verbose_name = "Search History"
        verbose_name_plural = "Search History"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["ip_address", "timestamp"]),
            models.Index(fields=["user", "query"]),
            # Serves the API quota: today's API searches for one account.
            models.Index(fields=["user", "source", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.user or self.ip_address}: {self.query[:50]}"


class EngagementEvent(models.Model):
    """Append-only log of what users *do with* results — the engagement
    counterpart to ``SearchHistory`` (which only records search inputs).

    One row per tracked interaction: opening a provision version from the
    search viewer, landing on a regulation or provision permalink, or
    following a result link out (external source, PDF download).  Writes are
    best-effort and must never break the page or the search — see
    ``telemetry.events.record_event``.

    ``object_id`` is intentionally a loose integer, **not** a ``ForeignKey``:
    events outlive the rows they point at (``load_edition`` replaces
    provision/version pks wholesale on reload), and an analytics log should
    not cascade-delete or block deletes.  Resolve targets at report time and
    tolerate misses.
    """

    # Auto pk + FK id-shadow, plugin-only — declared for Pyright.
    id: int
    search_id: int | None

    class EventType(models.TextChoices):
        PROVISION_VERSION_VIEW = "provision_version_view", "Provision version view"
        REGULATION_VIEW = "regulation_view", "Regulation view"
        RESULT_LINK_CLICK = "result_link_click", "Result link click"
        # A free-tier user met the content gate: they asked for something (or
        # were shown that something exists) that their tier can't open.  The
        # conversion signal — every other event type records value delivered,
        # this one records value withheld.  ``context.surface`` distinguishes
        # an explicit attempt on a known target (permalink / regulation_detail
        # / edition_chain / search_viewer) from an impression (search_results,
        # where the user only saw a locked count).
        LOCKED_CONTENT_VIEW = "locked_content_view", "Locked content view"
        # A reader opened /compare/ on two versions that both resolved and
        # both passed the gate.  Recorded separately from
        # PROVISION_VERSION_VIEW because a comparison is not two views: it is
        # the question the product exists to answer, and the one a reader
        # cannot answer with two browser tabs.  ``context.cross_edition`` is
        # the split that matters — a cross-edition comparison needs Pro on at
        # least one side, so it is the value the price buys.
        VERSION_COMPARISON = "version_comparison", "Version comparison"
        # An anonymous visitor asked for a search after spending the day's
        # allowance.  The other gate event (LOCKED_CONTENT_VIEW) records
        # content withheld; this one records the *search* withheld, and it is
        # the only record that the block happened at all — the middleware
        # returns 429 before any SearchHistory row is written, so without this
        # row a blocked visitor is indistinguishable from one who left.
        RATE_LIMIT_BLOCK = "rate_limit_block", "Rate limit block"
        # A reader took something out of the product and put it in their own
        # work.  ``context.kind`` is one of citation / provision_pdf /
        # results_csv / comparison_pdf, and the citation kind also carries
        # ``context.format``.  All four exports were built at once because we
        # could not guess which one a consultant reaches for, and asking
        # produces an opinion rather than a measurement — so the kind is the
        # measurement, and an export nobody uses is removed rather than
        # defended (``tasks/b-provision-exports.md``).
        EXPORT = "export", "Export"
        # An API account ran past its daily search allowance and was made
        # to wait.  Nothing was refused — the allowance is a throttle, not
        # a wall (web.api.auth) — so this is not a gate event and must not
        # join RATE_LIMIT_BLOCK's conversion denominator, which counts
        # value withheld.  It records that the line was crossed, and it is
        # what makes the operator notice fire once a day rather than once
        # a search.  ``context`` carries searches_today and delay_seconds.
        API_THROTTLE = "api_throttle", "API throttle"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="engagement_events",
        null=True,  # Anonymous engagement
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    event_type = models.CharField(max_length=40, choices=EventType.choices)
    # Model label of the target (e.g. "CodeEditionProvisionVersion"), kept as
    # a plain string so the table stays generic across target types.
    object_type = models.CharField(max_length=50, blank=True, default="")
    object_id = models.BigIntegerField(null=True, blank=True)
    # The search this engagement came from, when known — lets us compute
    # click-through rate per query.  SET_NULL so pruning history never drops
    # the engagement record.
    search = models.ForeignKey(
        SearchHistory,
        on_delete=models.SET_NULL,
        related_name="engagement_events",
        null=True,
        blank=True,
    )
    # Free-form target detail (provision_id, division, reg_id, query_date,
    # source surface, …) so reports don't need to re-resolve object_id.
    context = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "engagement_events"
        verbose_name = "Engagement Event"
        verbose_name_plural = "Engagement Events"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["event_type", "timestamp"]),
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["search"]),
        ]

    def __str__(self):
        who = self.user or self.ip_address or "anon"
        return f"{who}: {self.event_type} {self.object_type}#{self.object_id}"


class EditionRequest(models.Model):
    """A visitor telling us which code or edition they need.

    The demand log.  Every other table here records what the corpus *has*;
    this one records what a real reader came looking for and did not find,
    which is the only evidence we have for what to ingest next.

    ``code_text`` is deliberately free text, not a choice list.  A visitor who
    types "Alberta 2014" or "the 1990 OBC" has told us the useful thing, and a
    dropdown of what we already carry cannot capture a request for what we do
    not.  Normalising it is a reporting problem, not an input problem — see
    [[feedback_clean_data]] for why we still do not transform it on the way in.

    ``email`` is optional on purpose.  The need is the valuable field; the
    address is a bonus.  Requiring it would lose the visitor who will not give
    one, and with them the only signal that the edition matters at all.
    """

    # Auto pk + FK id-shadow, plugin-only — declared for Pyright.
    id: int
    search_id: int | None

    class Surface(models.TextChoices):
        LANDING = "landing", "Landing page"
        RATE_LIMIT = "rate_limit", "Rate-limit teaser"
        SEARCH = "search", "Search page"

    #: What they asked for, in their own words.
    code_text = models.CharField(max_length=200)
    email = models.EmailField(blank=True, default="")
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="edition_requests",
        null=True,
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    #: Which page the ask came from — a request typed after a search was
    #: withheld means something different from one typed on the front page.
    surface = models.CharField(
        max_length=20, choices=Surface.choices, default=Surface.LANDING
    )
    #: The search that preceded the ask, when there was one.  SET_NULL so
    #: pruning history never drops the demand record.
    search = models.ForeignKey(
        SearchHistory,
        on_delete=models.SET_NULL,
        related_name="edition_requests",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    #: When we last wrote to this address about this request.  Null means we
    #: never have.
    notified_at = models.DateTimeField(null=True, blank=True)
    #: Every edition we have announced to this row, by the label the sender
    #: typed.  A **list**, not one label: ``code_text`` is free text and a
    #: reader may name two editions in it, so a single stamp would spend the
    #: row on the first one and the second would never be announced.  It is
    #: also what makes a re-run safe — the send skips a row that already holds
    #: the label, so a failure part-way through can be re-run without writing
    #: to the people it already reached.
    notified_about = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "edition_requests"
        verbose_name = "Edition Request"
        verbose_name_plural = "Edition Requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["surface", "created_at"]),
        ]

    def __str__(self) -> str:
        who = self.email or (self.user.email if self.user else self.ip_address or "anon")
        return f"{who} wants {self.code_text}"


class ProvisionFeedback(models.Model):
    """A reader telling us that a specific text on this site is wrong.

    Free for everybody — anonymous, free and Pro alike.  A reader who reports a
    discrepancy is doing our verification for us, and a product that invites
    correction reads as more trustworthy than one that does not.  That is the
    same argument the Sources page and the verification-rail guide already make.

    **The target is text, never a ForeignKey.**  ``load_edition`` replaces
    provision and version primary keys wholesale on reload, so a report keyed
    on a pk would point at a different provision — or nothing — after the next
    load.  The natural key (edition, division, provision id, version) survives
    that, and is also what a permalink is built from, so the triage queue can
    link straight back to what the reader was looking at.  This is the same
    reasoning ``EngagementEvent.object_id`` already uses.

    Two target shapes, because two kinds of page carry a claim a reader can
    dispute.  A provision report names the provision and its version.  A
    regulation report names ``reg_id`` instead, since a regulation page shows
    a whole instrument and no single provision.  Exactly one shape is filled;
    ``web.views.feedback`` refuses a submission with neither.
    """

    # Auto pk + FK id-shadow, plugin-only — declared for Pyright.
    id: int
    user_id: int | None

    class Surface(models.TextChoices):
        PERMALINK = "permalink", "Provision permalink"
        SEARCH = "search", "Search result"
        REGULATION = "regulation", "Regulation detail"

    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWED = "reviewed", "Reviewed"
        FIXED = "fixed", "Fixed"
        NOT_A_DEFECT = "not_a_defect", "Not a defect"

    #: Edition name in the permalink's own form, e.g. "OBC_2006".
    code_edition = models.CharField(max_length=50)
    #: Bare division letter, "" for a division-less code.  Same convention as
    #: everywhere else in the corpus.
    division = models.CharField(max_length=10, blank=True, default="")
    provision_id = models.CharField(max_length=50, blank=True, default="")
    version = models.IntegerField(null=True, blank=True)
    #: Regulation number ("350/06") for a regulation-page report.  The number,
    #: not the row pk, for the reload reason above.
    reg_id = models.CharField(max_length=50, blank=True, default="")

    #: What the reader says is wrong.  The whole point of the record.
    note = models.TextField()
    #: Optional.  A report we cannot answer is still a useful report, and
    #: requiring an address would lose the reader who will not give one.
    email = models.EmailField(blank=True, default="")
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="provision_feedback",
        null=True,
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    surface = models.CharField(
        max_length=20, choices=Surface.choices, default=Surface.PERMALINK
    )
    created_at = models.DateTimeField(auto_now_add=True)

    #: Triage state.  A report with no queue becomes a table nobody opens, so
    #: the status is part of the feature, not a later addition.
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NEW
    )
    #: Our note back to ourselves — what we found, what we changed.
    resolution = models.TextField(blank=True, default="")

    class Meta:
        db_table = "provision_feedback"
        verbose_name = "Provision Feedback"
        verbose_name_plural = "Provision Feedback"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["code_edition", "provision_id"]),
        ]

    def __str__(self) -> str:
        who = self.email or (self.user.email if self.user else self.ip_address or "anon")
        return f"{who}: {self.target_ref} looks wrong"

    @property
    def target_ref(self) -> str:
        """The target as a reader would name it."""
        if self.reg_id:
            return f"{self.code_edition} · O. Reg. {self.reg_id}"
        parts = [self.code_edition]
        if self.division:
            parts.append(f"Div {self.division}")
        parts.append(self.provision_id)
        if self.version is not None:
            parts.append(f"v{self.version}")
        return " · ".join(parts)


class AuthEvent(models.Model):
    """Append-only security audit log of authentication outcomes.

    The security counterpart to ``SearchHistory``/``EngagementEvent`` (which
    record *content* access): one row per login, logout, or failed login, so a
    credential-stuffing run or a successful break-in leaves a queryable trail
    (failed-attempt rate per IP/email, last successful login per user).  This is
    the application-layer access log; it does **not** see direct database access
    that bypasses Django — see ``docs/security/breach-response-plan.md``.

    Writes are best-effort and must never block authentication — see
    ``accounts.signals.auth_audit``.  ``user`` is ``SET_NULL`` so the trail outlives the
    account, and a failed attempt has no user at all, so the attempted
    identifier is kept separately in ``email``.
    """

    # Auto pk, plugin-only — declared for Pyright.
    id: int

    class EventType(models.TextChoices):
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        LOGIN_FAILED = "login_failed", "Login failed"

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="auth_events",
        null=True,
        blank=True,
    )
    # The identifier presented at the attempt — always set for failures (where
    # there is no user) and mirrored for successes so a row reads on its own.
    email = models.CharField(max_length=254, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_events"
        verbose_name = "Auth Event"
        verbose_name_plural = "Auth Events"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["event_type", "timestamp"]),
            models.Index(fields=["ip_address", "timestamp"]),
            models.Index(fields=["email", "timestamp"]),
        ]

    def __str__(self):
        who = self.email or (self.user.email if self.user else "?")
        return f"{who}: {self.event_type}"


class ApiKey(models.Model):
    """A credential for the direct API, belonging to one subscriber.

    The paid endpoints take a key and nothing else.  A signed-in browser
    session is not a credential there, for two reasons.  It is what makes
    "direct API access" a thing to sell rather than a cookie somebody replays
    out of their browser.  And the API is exempt from Django's CSRF check, so
    an endpoint that trusted the cookie could be driven from another site's
    page; a browser never sends a bearer token on its own.

    **Only the hash is stored.**  :meth:`generate` returns the plain token
    once and nothing keeps a copy, so a lost token is replaced rather than
    recovered.  The hash is a plain SHA-256, not a password hasher: the token
    is 32 random bytes, so there is no guessable input for a slow hash to
    protect, and every request would pay that deliberate cost.

    ``lookup`` holds the first characters of the token in clear.  It does two
    jobs: it finds the row in one indexed query, and it is what the settings
    page prints so the holder can tell two keys apart.  It is indexed but not
    unique — two keys can share it, and the hash comparison still picks the
    right one, which is better than a create that fails on a collision.
    """

    # Auto pk, plugin-only — declared for Pyright.
    id: int

    #: Every token starts with this.  A fixed prefix makes a leaked key
    #: recognisable in a log or a paste, and is what a secret scanner matches.
    TOKEN_PREFIX = "cc_"
    #: How much of the token is kept in clear: the prefix and 8 characters.
    LOOKUP_LENGTH = 11

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    # What the key is for, in the holder's own words.  A key nobody can name
    # is a key nobody dares revoke.
    name = models.CharField(max_length=100)
    lookup = models.CharField(max_length=16, db_index=True)
    hashed_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)
    # Answers "is anything still calling with this?" before somebody revokes.
    last_used_at = models.DateTimeField(null=True, blank=True)
    # Revoked, never deleted: the row is the record that the key existed, and
    # a deleted row cannot explain a request in yesterday's log.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_keys"
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self) -> str:
        return f"{self.user.email}: {self.name}"

    @staticmethod
    def hash_token(token: str) -> str:
        """The stored form of a token.  See the class docstring for SHA-256."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def generate(cls, user: "User", name: str) -> tuple["ApiKey", str]:
        """Create a key, and return it with the one copy of its token."""
        token = cls.TOKEN_PREFIX + secrets.token_urlsafe(32)
        key = cls.objects.create(
            user=user,
            name=name.strip()[:100] or "API key",
            lookup=token[: cls.LOOKUP_LENGTH],
            hashed_key=cls.hash_token(token),
        )
        return key, token

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def revoke(self) -> None:
        """Stop the key working.

        A key already revoked is left alone, so a double-submitted form does
        not move the date that says when access ended.
        """
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class ProvisionFetch(models.Model):
    """One row per (account, provision version) ever delivered to that account.

    Both surfaces write here: ``/api/provision`` and every website page that
    renders a body.  ``source`` says which one first delivered it.

    A ledger of *coverage*, not of traffic.  Volume cannot tell a busy
    subscriber from somebody copying the corpus — a heavy working day and the
    whole corpus are the same order of magnitude.  What separates them is
    novelty.  Somebody recording the corpus almost never fetches the same
    provision twice, and their share of it climbs in a straight line.  A
    consultant returns again and again to the provisions their practice turns
    on, so most of their fetches are repeats and their coverage flattens out
    at a few percent.

    That signal only exists because the text leaves in countable pieces.  While
    a search answered with a hundred texts at once, nothing here could say
    which provisions an account had taken.

    **The target is text, never a ForeignKey**, for the reason
    ``ProvisionFeedback`` gives: ``load_edition`` replaces every provision and
    version primary key on reload, and a ledger that reset on a data load would
    report every returning reader as a new recorder.

    This is a record to read, not an alarm and not a limit.  Nothing here
    refuses a request.
    """

    # Auto pk + FK id-shadow, plugin-only — declared for Pyright.
    id: int
    user_id: int

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="provision_fetches")
    #: Edition name in the permalink's own form, e.g. "OBC_2006".
    code_edition = models.CharField(max_length=50)
    #: Bare division letter, "" for a division-less code.
    division = models.CharField(max_length=10, blank=True, default="")
    provision_id = models.CharField(max_length=50)
    version = models.IntegerField()

    class Source(models.TextChoices):
        WEB = "web", "Website"
        API = "api", "Direct API"

    # Which surface **first** delivered this text to this account.
    #
    # First, not latest, because the row's identity is the text and its date is
    # ``first_fetched_at`` — the surface belongs with the moment the account
    # acquired it.  Overwriting it on every repeat would make the field mean
    # "where was this account last seen", which no reading here asks for.
    #
    # **No default, and the database enforces it** (see the check constraint
    # below).  Every write site names the surface.  A default is how a website
    # read gets filed as an API read and nobody notices; the two populations
    # behave differently enough that a curve drawn across both is a curve over
    # a population that does not exist.  Website rows arrive in bulk from one
    # page render, so read *coverage* for them and never ``new_share``.
    #
    # Leaving the default off is **not** sufficient on its own.  Django gives a
    # non-null CharField an implicit ``""``, so a caller that forgets this field
    # writes an empty string and the row then counts as neither surface — the
    # silent miscount the rule exists to prevent, arriving by another door.
    # ``choices`` does not help either: it is checked by ``full_clean``, which
    # ``save`` does not call.  The constraint is the part that holds.
    source = models.CharField(max_length=8, choices=Source.choices, db_index=True)

    #: How many times this account has been given this exact text.  A high
    #: number is the ordinary shape of real use.
    fetch_count = models.PositiveIntegerField(default=1)
    #: When it first became new to this account.  Counting these per day is
    #: what makes a straight line visible.
    first_fetched_at = models.DateTimeField(default=timezone.now)
    last_fetched_at = models.DateTimeField(default=timezone.now)


    class Meta:
        db_table = "provision_fetches"
        verbose_name = "Provision Fetch"
        verbose_name_plural = "Provision Fetches"
        ordering = ["-last_fetched_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code_edition", "division", "provision_id", "version"],
                name="unique_provision_fetch_per_user",
            ),
            # A row must say which surface delivered it.  Without this the
            # implicit empty string passes, and the row is counted by neither
            # ``web_held`` nor ``api_held`` — a loss that shows up as an
            # account reading less than it did.
            models.CheckConstraint(
                condition=models.Q(source__in=["web", "api"]),
                name="provision_fetch_names_its_surface",
            ),
        ]
        indexes = [
            # Serves both readings: what an account has taken in total, and
            # what became new to it in a period.
            models.Index(fields=["user", "first_fetched_at"]),
            models.Index(fields=["user", "last_fetched_at"]),
            # The per-surface readings, which are the only correct ones now
            # that both surfaces write here.
            models.Index(fields=["user", "source", "first_fetched_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.email}: {self.code_edition} {self.provision_id} v{self.version}"


class BackupRun(models.Model):
    """One row per ``manage.py backup_userdata`` run, successful or not.

    The backup runs unattended on a timer, and a backup nobody looks at is a
    backup nobody knows is broken.  Two failures are possible and they need
    different detectors: a run that *fails* exits non-zero, and a run that
    *never happens* produces no signal at all.  A row here answers the first
    directly and the second by its absence — ``/insights/`` reads the newest
    row's age, so silence shows as a stale timestamp rather than as nothing.

    This is the record, not the alarm.  The alarm is the dead-man's switch
    (``BACKUP_HEALTHCHECK_URL``), which lives off this machine and so still
    fires when the database this table is in cannot be reached at all.

    ``kind`` matters: a ``--dest`` drill writes a local file and uploads
    nothing, so counting it as a backup would let a run of drills hide the fact
    that no off-host copy exists.

    Rows are tiny and this table is *not* in ``CORPUS_TABLES``, so the backup
    backs up its own history.
    """

    # Auto pk, plugin-only — declared for Pyright.
    id: int

    class Kind(models.TextChoices):
        UPLOAD = "upload", "Uploaded off-host"
        LOCAL = "local", "Local drill"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.UPLOAD)
    succeeded = models.BooleanField(default=False)
    # The R2 key, or the local path for a drill.  Text, never a reference to
    # anything: the object it names is deliberately outside this database.
    location = models.TextField(blank=True, default="")
    size_bytes = models.BigIntegerField(null=True, blank=True)
    # Empty on success.  Holds the CommandError text otherwise, which is what
    # tells you whether pg_dump, age or the upload was the step that broke.
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "backup_runs"
        verbose_name = "Backup Run"
        verbose_name_plural = "Backup Runs"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["kind", "succeeded", "-started_at"]),
        ]

    def __str__(self):
        state = "ok" if self.succeeded else "FAILED"
        return f"{self.started_at:%Y-%m-%d %H:%M}Z {self.kind} {state}"


class Code(models.Model):
    """
    A building code system (e.g., OBC, NBC).
    """

    code = models.CharField(max_length=20, unique=True)
    display_name = models.CharField(max_length=200, blank=True, default="")
    is_national = models.BooleanField(default=False)
    document_type = models.CharField(
        max_length=20,
        default="code",
        choices=[("code", "code"), ("guide", "guide")],
    )
    #: Real-world in-force date of the code's *first edition ever* (OBC:
    #: 1975-12-31) — a seeded fact, not derivable from loaded data, since
    #: real edition history extends before our corpus window.  Lets the
    #: lineage resolver tell "this is the first edition" (predecessor
    #: endpoint) from "earlier editions exist but aren't covered" (no data
    #: yet).  Null = unknown → the resolver defaults to "no data yet".
    #: Seeded by ``load_edition`` (so it survives a codes wipe + reload).
    first_edition_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "codes"
        verbose_name = "Code"
        verbose_name_plural = "Codes"

    def __str__(self):
        return self.code


class CodeEdition(models.Model):
    """
    A specific edition/version of a code system.
    """

    # Reverse relations — declared for Pyright (no plugin); the mypy
    # django-stubs plugin infers these from the related_name on the FK side.
    regulations: "models.Manager[Regulation]"
    provisions: "models.Manager[CodeEditionProvision]"
    consolidations: "models.Manager[Consolidation]"
    # FK id-shadow, plugin-only — declared for Pyright.
    code_id: int

    code = models.ForeignKey(Code, on_delete=models.CASCADE, related_name="editions")
    edition_id = models.CharField(max_length=50)
    year = models.IntegerField()
    effective_date = models.DateField()
    ineffective_date = models.DateField(null=True, blank=True)
    amendment_chain_complete = models.BooleanField(default=False)
    #: CCM publish gate.  ``amendment_chain_complete`` only means every
    #: amending regulation was processed; ``verified`` means the resulting
    #: reconstruction's discrepancies against the consolidation record have
    #: also been reviewed.  Public surfaces (the Sources page) list only
    #: verified editions.
    verified = models.BooleanField(default=False)
    version_number = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default="")
    is_guide = models.BooleanField(default=False)

    class Meta:
        db_table = "code_editions"
        verbose_name = "Code Edition"
        verbose_name_plural = "Code Editions"
        constraints = [
            models.UniqueConstraint(
                fields=["code", "edition_id"], name="code_edition_code_edition_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["code", "effective_date"], name="code_edition_effective_idx"),
        ]

    def __str__(self):
        return f"{self.code.code}_{self.edition_id}"

    @property
    def code_name(self) -> str:
        return f"{self.code.code}_{self.edition_id}"


class ConsolidationManager(models.Manager["Consolidation"]):
    def resolve(
        self, edition_id: int, on_date: date | None
    ) -> "Consolidation | None":
        """The consolidation snapshot covering ``on_date`` for an edition.

        ``effective_to`` is the inclusive last day of the period (a zero-range
        point ``[d, d]`` for the current consolidation), so coverage is the closed
        interval ``effective_from <= on_date <= effective_to``. A date past the
        current point is therefore *not* covered — it rests on reconstruction
        (verification-coverage decision 4), and source-link callers query with the
        version's own ``effective_date`` (== the current row's ``effective_from``),
        which the point still covers. Overlaps (the brief windows where two
        editions' consolidated regs coexist) are broken by the latest-starting
        period. Returns None when no period covers the date — pre-e-Laws spans get
        no link, never a guess.
        """
        if on_date is None:
            return None
        return (
            self.filter(
                edition_id=edition_id,
                effective_from__lte=on_date,
                effective_to__gte=on_date,
            )
            .order_by("-effective_from")
            .first()
        )


class Consolidation(models.Model):
    """A point-in-time e-Laws consolidation of an edition's consolidated reg.

    NOT a source (the regulation is the source) — a formatted, assembled view of
    the code we link to so a provision can be read "as it stood" on a date.
    e-Laws republishes one per amendment commencement, each covering a date
    range; rows are built from the cached consolidation pages' own period banners
    by ``scripts/build_elaws_consolidations.py`` and loaded by
    ``load_consolidations``. ``version`` is the e-Laws version number (the
    ``/v38`` in the URL), distinct from CCM's internal version index.
    """

    # FK id-shadow, plugin-only — declared for Pyright.
    edition_id: int

    edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="consolidations"
    )
    version = models.PositiveSmallIntegerField()
    url = models.URLField(max_length=500)
    effective_from = models.DateField()
    #: Inclusive last day e-Laws states for the period. A closed historical period
    #: is genuinely ``[from, to]`` (e-Laws republished at its end, proving the text
    #: held). The *current* consolidation has no closing republication, so it is a
    #: zero-range point ``[d, d]`` (``effective_to == effective_from``): attested at
    #: the instant, no forward promise. NULL is not used — a date past the current
    #: point falls into the open, reconstruction-only tail (verification-coverage
    #: decision 4), it is not "covered" by the current row.
    effective_to = models.DateField()

    # Explicit annotation so Pyright (no plugin) resolves the manager's
    # ``resolve`` method rather than falling back to the base Manager.
    objects: "ConsolidationManager" = ConsolidationManager()

    class Meta:
        db_table = "consolidations"
        ordering = ["edition", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["edition", "version"], name="elaws_consolidation_edition_version_unique"
            ),
        ]
        indexes = [
            models.Index(
                fields=["edition", "effective_from", "effective_to"],
                name="elaws_consolidation_window_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.edition} consolidation v{self.version}"


class ProvinceCode(models.Model):
    """
    Map a province abbreviation to its primary code system.
    """

    province = models.CharField(max_length=2, unique=True)
    code = models.ForeignKey(Code, on_delete=models.CASCADE, related_name="provinces")

    class Meta:
        db_table = "province_codes"
        verbose_name = "Province Code"
        verbose_name_plural = "Province Codes"

    def __str__(self):
        return f"{self.province} -> {self.code.code}"


class Regulation(models.Model):
    """An Ontario regulation — base code enactment or amendment."""

    # Reverse relations (see note on CodeEdition).
    clauses: "models.Manager[RegulationClause]"
    assets: "models.Manager[RegulationAsset]"

    class Role(models.TextChoices):
        BASE = "base", "Base"
        AMENDMENT = "amendment", "Amendment"

    class SourceKind(models.TextChoices):
        # Where the regulation-as-enacted can be read online. NOT the e-Laws
        # consolidation snapshot (that is a point-in-time view of the assembled
        # code, modelled separately) — this is the authoritative published
        # instrument: an e-Laws regulation page, a gazette scan, etc.
        ELAWS = "elaws", "e-Laws"
        ARCHIVE_GAZETTE = "archive_gazette", "Gazette (archive.org)"
        ONTARIO_CA = "ontario_ca", "Ontario.ca"
        OTHER = "other", "Other"

    reg_id = models.CharField(max_length=50, unique=True)
    edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="regulations"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    amends = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="amended_by",
    )
    filed_date = models.DateField(null=True, blank=True)
    effective_date = models.DateField()
    source_pdf = models.CharField(max_length=200, blank=True, default="")
    source_pages = models.JSONField(null=True, blank=True)
    source_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text=(
            "Authoritative online location of the regulation as enacted "
            "(e.g. its e-Laws regulation page or an archive.org gazette scan). "
            "Supplied by CCM; absent → no source link is shown, never a guess."
        ),
    )
    source_kind = models.CharField(
        max_length=30,
        choices=SourceKind.choices,
        blank=True,
        default="",
        help_text="Which kind of source `source_url` points at, for labelling.",
    )
    commencement = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "CCM-parsed commencement records: the regulation's default "
            "'comes into force on …' clause plus any staggered exceptions. "
            "Each record carries {clause, is_default, commencement_clause, "
            "effective_date, resolved_provisions, …}. The default record's "
            "date mirrors ``effective_date``; non-default records pin "
            "later in-force dates for the provisions they name."
        ),
    )

    class Meta:
        db_table = "regulations"
        indexes = [
            models.Index(fields=["edition", "effective_date"]),
        ]

    def __str__(self):
        return f"{self.citation} ({self.role})"

    @property
    def citation(self) -> str:
        """The instrument as a reader cites it: ``O. Reg. 350/06``.

        ``reg_id`` is the bare number.  On its own it names nothing — a reader
        cannot tell "350/06" from a date or a docket, and a machine reading it
        out of a structured block has no way to learn what it is.  The prefix
        is the part that makes it a citation, so it belongs to the model and
        not to each surface that prints one.

        Ontario's form, because Ontario is the only jurisdiction loaded.  A
        national or another province's instrument takes a different prefix; it
        is spelled once, here, so there is one place to widen it.
        """
        return f"O. Reg. {self.reg_id}"

    @property
    def source_link_label(self) -> str:
        """Call-to-action for the source link, phrased per ``source_kind``.

        Not a generic "View on <display>": the gazette display carries a
        parenthetical ("Gazette (archive.org)") that reads badly in that mould,
        so each kind names its own verb phrase here. Mixed-case; the template
        upper-cases to match the header's mono style. Empty kind (url but no
        kind) falls back to the neutral "View source".
        """
        labels: dict[str, str] = {
            self.SourceKind.ELAWS.value: "View on e-Laws",
            self.SourceKind.ARCHIVE_GAZETTE.value: "View Gazette on archive.org",
            self.SourceKind.ONTARIO_CA.value: "View on Ontario.ca",
            self.SourceKind.OTHER.value: "View source",
        }
        return labels.get(self.source_kind, "View source")


class RegulationClause(models.Model):
    """A single amendment directive within a regulation."""

    # Reverse relations (see note on CodeEdition).  The M2M back-accessor of
    # CodeEditionProvisionVersion.contributing_clauses (related_name).
    contributed_to_versions: "models.Manager[CodeEditionProvisionVersion]"

    if TYPE_CHECKING:
        # Choice-field display methods Django generates at class creation.
        # The mypy plugin synthesises these; plain Pyright (editor) can't see
        # them, so declare the ones we call.  Guarded by TYPE_CHECKING so the
        # real generated methods are used at runtime.
        def get_action_display(self) -> str: ...
        def get_target_level_display(self) -> str: ...

    class Action(models.TextChoices):
        REVOKE_AND_SUBSTITUTE = "revoke_and_substitute", "Revoke and substitute"
        AMEND_ADD = "amend_add", "Amend by adding"
        AMEND_STRIKE_SUB = "amend_strike_sub", "Amend by striking and substituting"
        REVOKE = "revoke", "Revoke"
        RENUMBER = "renumber", "Renumber"

    class TargetLevel(models.TextChoices):
        ARTICLE = "article", "Article"
        SENTENCE = "sentence", "Sentence"
        CLAUSE = "clause", "Clause"
        SUBCLAUSE = "subclause", "Subclause"
        SUBSECTION = "subsection", "Subsection"
        SECTION = "section", "Section"
        PART = "part", "Part"
        TABLE = "table", "Table"

    regulation = models.ForeignKey(
        Regulation, on_delete=models.CASCADE, related_name="clauses"
    )
    clause_id = models.CharField(max_length=50)
    parent_clause = models.CharField(max_length=50, blank=True, default="")
    action = models.CharField(
        max_length=50, choices=Action.choices, blank=True, default=""
    )
    target_level = models.CharField(
        max_length=50, choices=TargetLevel.choices, blank=True, default=""
    )
    target_id = models.CharField(max_length=200, blank=True, default="")
    target_division = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text=(
            "Division the target provision lives in, as a bare letter "
            "('A'/'B'/'C') matching CodeEditionProvision.division. Empty for "
            "division-less editions (OBC 1997) or clauses with no single "
            "division (meta-amendments)."
        ),
    )
    target_reg = models.CharField(max_length=50, blank=True, default="")
    effective_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "The clause's own commencement date — when this amending "
            "directive comes into force. Usually equal to the regulation's "
            "blanket effective_date, but Ontario regs routinely stagger "
            "commencement so a clause can come into force later (its date "
            "resolved by CCM from the regulation's commencement records)."
        ),
    )
    clause_text = models.TextField(blank=True, default="")
    strike_text = models.TextField(null=True, blank=True)
    sub_text = models.TextField(null=True, blank=True)
    add_text = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Text inserted by an 'amend by adding' directive, anchored at "
            "``add_anchor``. Part of recording commencement at provision "
            "granularity: this is the content the clause brings into force "
            "on ``effective_date``."
        ),
    )
    add_anchor = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Where ``add_text`` is inserted, e.g. "
            "'after:CSA C22.2 No. 0.3, …'. The primary directive's anchor "
            "for a single-directive clause."
        ),
    )
    directives = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Full decomposition of a clause that amends several targets — "
            "the list of {action, target_level, target_id, target_division, "
            "strike_text, sub_text, add_text, add_anchor, …} directives. The "
            "flat target_*/strike_*/sub_*/add_* fields mirror the primary "
            "(first) directive; this list carries them all so the clause's "
            "``effective_date`` (commencement) can be pinned onto every "
            "provision it touches, not just the primary target."
        ),
    )
    commencement = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "The single CommencementProvenance record that set this clause's "
            "``effective_date`` — the *why* behind the date: the verbatim "
            "commencement subsection, its ``source`` (parsed / "
            "commencement-input / regulations-act-default / catalog), and for "
            "derived dates the ``depends_on`` statute and ``computation``. "
            "Resolved at load from the regulation's commencement schedule via "
            "``resolved_clauses`` (with the default entry as fallback); see "
            "load_edition._resolve_clause_commencement. Mirrors one entry of "
            "``Regulation.commencement``."
        ),
    )
    amended_by = models.JSONField(null=True, blank=True)
    page = models.IntegerField(null=True, blank=True)
    bbox = models.JSONField(null=True, blank=True)
    overlay = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "regulation_clauses"
        indexes = [
            models.Index(fields=["regulation"]),
            models.Index(fields=["target_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["regulation", "clause_id"],
                name="clause_regulation_clause_id_unique",
            ),
        ]

    def __str__(self):
        return f"{self.regulation.reg_id} cl. {self.clause_id}"


class AssetManifestEntry(models.Model):
    """One mirrored binary that an e-Laws-derived HTML body references.

    Stored as a manifest only — the bytes live under the asset root at
    ``path`` (e.g. ``laws/images/en/R19088_e_files/image007.gif``), which
    ``sync_images`` publishes.  The same relative path is the URL path served
    at host root, so the inline ``<img src="/laws/images/...">`` references in
    ``versions[].html`` resolve without HTML rewriting.

    CCM emits the same five keys at two scopes, so this base holds them once
    and the two concrete models add only their owner.  See
    :class:`RegulationAsset` and :class:`ProvisionVersionAsset` for which
    scope answers which question.
    """

    path = models.CharField(max_length=500)
    original_url = models.CharField(max_length=500, blank=True, default="")
    sha256 = models.CharField(max_length=64, blank=True, default="")
    byte_size = models.BigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        abstract = True


class RegulationAsset(AssetManifestEntry):
    """An inline asset a regulation's own filing carried.

    Mirrors ``regulations[].assets[]``.  This is the *source-filing* set: what
    the amending regulation shipped.  It is not the set a reader needs — the
    consolidated HTML a version stores names assets no single filing carried
    (:class:`ProvisionVersionAsset`).
    """

    regulation = models.ForeignKey(
        Regulation, on_delete=models.CASCADE, related_name="assets",
    )

    class Meta:
        db_table = "regulation_assets"
        constraints = [
            models.UniqueConstraint(
                fields=["regulation", "path"],
                name="regulation_asset_path_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["path"]),
        ]

    def __str__(self):
        return f"{self.regulation.reg_id} :: {self.path}"


class CodeEditionProvision(models.Model):
    """Structural identity of a provision within an edition. No content."""

    # Reverse relations (see note on CodeEdition).
    versions: "models.Manager[CodeEditionProvisionVersion]"
    children: "models.Manager[CodeEditionProvision]"
    cited_by: "models.Manager[ProvisionCrossReference]"
    # FK id-shadows, plugin-only — declared for Pyright.
    edition_id: int
    parent_id: int | None

    if TYPE_CHECKING:
        # Choice-field display method (see RegulationClause): synthesised by
        # the mypy plugin, invisible to plain Pyright — declared so the call
        # in views.regulation._clause_targets type-checks under both.
        def get_level_display(self) -> str: ...

    class Level(models.TextChoices):
        DIVISION = "division", "Division"
        PART = "part", "Part"
        SECTION = "section", "Section"
        SUBSECTION = "subsection", "Subsection"
        ARTICLE = "article", "Article"
        SENTENCE = "sentence", "Sentence"
        CLAUSE = "clause", "Clause"

    edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="provisions"
    )
    provision_id = models.CharField(max_length=200)
    level = models.CharField(max_length=20, choices=Level.choices)
    division = models.CharField(max_length=50, blank=True, default="")
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.CASCADE, related_name="children",
    )
    appendix_of = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="appendix_entries",
    )
    version_count = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "code_edition_provisions"
        constraints = [
            models.UniqueConstraint(
                fields=["edition", "provision_id", "division"],
                name="provision_edition_id_division_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["edition", "division", "provision_id"]),
            models.Index(fields=["parent"]),
        ]

    def __str__(self):
        prefix = f"{self.division} " if self.division else ""
        return f"{prefix}{self.provision_id}"

    @property
    def base_version(self) -> "CodeEditionProvisionVersion | None":
        """The chain root — the lowest-numbered (v0) version, or None if empty.

        Reads ``versions.all()`` (warmed by the search prefetch and
        ``CodeEditionProvisionVersion.Meta.ordering``) and takes the minimum by
        version number so a reordered prefetch can't pick the wrong root.
        """
        versions = list(self.versions.all())
        return min(versions, key=lambda v: v.version) if versions else None

    @property
    def origin_regulation(self) -> "Regulation | None":
        """The regulation that first enacted *this provision*.

        For a provision present since the edition's enactment this is the
        edition's ``role="base"`` regulation.  For a provision **added by a later
        amending regulation** — an ``amend_add``-created v0, whose ``clauses`` are
        non-empty (CCM contract) — it is that amending regulation: the base *for
        this provision*, not the edition's base reg.  The edition base reg never
        attested an added provision (it didn't exist at enactment), so showing it
        as the provision's base is the bug this avoids — e.g. OBC 1997 ``3.7.6.3.``
        was introduced by O. Reg. 593/99, not the edition base 403/97.
        """
        root = self.base_version
        if root is not None:
            origin_clause = root.first_contributing_clause
            if origin_clause is not None:
                return origin_clause.regulation
        # Genuine base original (v0 emits no clauses): the edition's base reg.
        for reg in self.edition.regulations.all():
            if reg.role == Regulation.Role.BASE:
                return reg
        return None


class CodeEditionProvisionVersion(models.Model):
    """A frozen snapshot of a provision's content at a point in the amendment chain.

    Version-level kind-of-change is derived, not stored — see
    ``tasks/provenance/drop-version-action.md``.  A version may aggregate
    multiple clauses of different actions on the same effective date; any
    consumer that needs a kind label should project from
    ``contributing_clauses``.
    """

    # Reverse relations (see note on CodeEdition).
    tables: "models.Manager[ProvisionVersionTable]"
    assets: "models.Manager[ProvisionVersionAsset]"
    cross_references: "models.Manager[ProvisionCrossReference]"
    # Render-time annotations, not DB fields: the body with within-edition
    # citations linked, and the list form of the same records
    # (``corpus.cross_refs.annotate_versions``).
    linked_html: str
    cross_ref_cites: list[dict[str, Any]]
    # The page images cropped to this provision, for the printable surfaces
    # only (``corpus.printing.page_crops.build_crops``).  Not on the reading page: there
    # a scan is shown whole with the region highlighted, because the reader
    # wants to see the provision in its setting.
    crops: list[dict[str, Any]]
    # Whether the printable surfaces repeat this version's tables as their own
    # figures (``corpus.printing.print_options``).  False for an image-rendered version,
    # whose scan already shows them.
    show_tables: bool
    codeeditionprovisionversionclause_set: (
        "models.Manager[CodeEditionProvisionVersionClause]"
    )
    # FK id-shadow, plugin-only — declared for Pyright.
    provision_id: int

    provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE, related_name="versions",
    )
    version = models.PositiveSmallIntegerField(default=0)
    # String annotation (not evaluated at runtime — ManyToManyField is not
    # subscriptable at runtime, unlike ForeignKey) so mypy learns the target
    # and through models without breaking Django's model import.
    contributing_clauses: "models.ManyToManyField[RegulationClause, CodeEditionProvisionVersionClause]" = (
        models.ManyToManyField(
            RegulationClause,
            through="CodeEditionProvisionVersionClause",
            related_name="contributed_to_versions",
            blank=True,
        )
    )
    effective_date = models.DateField()
    ineffective_date = models.DateField(null=True, blank=True)
    transition_provision = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="transition_targets",
    )

    title = models.CharField(max_length=500, blank=True, default="")
    html = models.TextField(blank=True, default="")
    page_images = models.JSONField(null=True, blank=True)
    keyword_counts = models.JSONField(null=True, blank=True)
    # Counts over the title *alone*, tokenized by CCM with the same function
    # that produced ``keyword_counts`` (which is the title + body + table-text
    # union).  The scorer scores title and body as separate BM25F fields and
    # recovers the body counts by subtracting these — see ``search.engine.engine``.
    # NULL for editions loaded before CCM began emitting the field; the scorer
    # then contributes nothing from the title, which is exactly single-field
    # BM25 — so an un-reloaded edition ranks as it did before, rather than
    # ranking wrongly.
    title_keyword_counts = models.JSONField(null=True, blank=True)
    # Provenance/annotation notes, shipped by CCM already tagged as
    # ``[{"kind": ..., "text": ...}]`` (CCM owns the kind taxonomy) and stored
    # verbatim — see ``core.provision_notes`` for the kind→display-tier map and
    # the ``grouped_notes`` property.
    notes = models.JSONField(default=list, blank=True)
    # Whole-provision revocation tombstone, derived once by CCM from the
    # e-Laws "Revoked: O. Reg. …" title marker (clause action can't tell a
    # full revoke from a substitution).  Absent in the source JSON for the
    # ~99% of versions that aren't revoked → defaults False on ingest.
    revoked = models.BooleanField(default=False)

    class Meta:
        db_table = "code_edition_provision_versions"
        ordering = ["version"]
        constraints = [
            models.UniqueConstraint(
                fields=["provision", "version"],
                name="version_provision_version_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["provision", "effective_date"]),
            models.Index(fields=["effective_date", "ineffective_date"]),
        ]

    def __str__(self):
        return f"{self.provision} v{self.version}"

    def in_force_on(self, day: "date") -> bool:
        """Is ``day`` within this version's half-open window ``[effective, ineffective)``?

        A zero-duration version (``ineffective_date == effective_date`` — see
        ``never_in_force``) contains no day, so this returns ``False`` for it.
        """
        return self.effective_date <= day and (
            self.ineffective_date is None or day < self.ineffective_date
        )

    def overlaps(self, other: "CodeEditionProvisionVersion") -> bool:
        """Do this version's in-force window and ``other``'s overlap?

        Half-open ``[effective, ineffective)``; ``None`` is an open end.  A
        *zero-duration* version (effective == ineffective, see
        :attr:`never_in_force`) is a window of length zero — it overlaps
        nothing under the plain test, so such a version would silently drop
        out of any overlap-driven surface.  These do occur: a base-edition v0
        superseded on the edition's own start date (e.g. OBC 2012 B 1.3.1.2.
        v0, 2014-01-01 → 2014-01-01).  Treat it as the instant {effective} and
        ask whether the other window contains it, so the base version still
        appears alongside its later siblings.

        Used by the permalink hierarchy nav (``views.regulation._related_links``)
        and the cross-reference "cited by" panel (``corpus.cross_refs``) — both
        answer "could a reader of this version have been looking at that one".
        """
        self_point = (
            self.ineffective_date is not None
            and self.ineffective_date == self.effective_date
        )
        other_point = (
            other.ineffective_date is not None
            and other.ineffective_date == other.effective_date
        )
        if self_point and other_point:
            return self.effective_date == other.effective_date
        if self_point:
            return other.in_force_on(self.effective_date)
        if other_point:
            return self.in_force_on(other.effective_date)
        self_before = (
            self.ineffective_date is not None
            and self.ineffective_date <= other.effective_date
        )
        other_before = (
            other.ineffective_date is not None
            and other.ineffective_date <= self.effective_date
        )
        return not self_before and not other_before

    @property
    def never_in_force(self) -> bool:
        """This version never governed a single day.

        In-force windows are half-open ``[effective, ineffective)``, so a
        zero-duration window (superseded the day it was to commence — common
        for base v0s amended on the edition's own start date) or an inverted
        one (revoked before its deferred commencement arrived, e.g. OBC 2006
        1.10.2.4. v1: due 2016-01-01, edition replaced 2014-01-01) is empty.
        Both are emitted deliberately — the version is still a link in the
        amendment chain; it just never operated.  Surfaces must say "never
        in force" rather than rendering the dates as an in-force period.
        """
        return (
            self.ineffective_date is not None
            and self.ineffective_date <= self.effective_date
        )

    @property
    def force_state(self) -> str:
        """Whether this version governs today, governed once, or never did.

        One of ``"current"``, ``"past"``, ``"future"`` or ``"never"``.  The
        provenance band names the state and draws its period mark from it, so
        that a badge cannot say "in force" about a text that stopped governing
        in 2012.  Measured against **today**, not against the reader's query
        date: the badge carries no date of its own, so a reader resolves it
        against now, and the attestation rail beside it is what answers the
        query date.

        Every surface asks this property rather than comparing the dates
        itself.  Two private copies of the half-open rule would eventually
        disagree, and the disagreement would be a false statement about what
        the law is — the same reason ``corpus.seo.last_governed_day`` exists.

        Note that today no loaded version is ``"current"``: the corpus ends on
        31 March 2025, because the code in force now is Licensed Material this
        product does not host.  So the caching this enables is safe — a page
        cannot change its badge without a data load, and a load moves
        ``CorpusCurrency.refreshed_at``, which is the ``Last-Modified`` the
        read surfaces answer 304 against.  **Loading a version with an open
        end breaks that**, because such a page would then go stale on a date
        no load touches.
        """
        if self.never_in_force:
            return "never"
        today = timezone.localdate()
        if self.in_force_on(today):
            return "current"
        return "future" if self.effective_date > today else "past"

    @property
    def last_contributing_clause(self) -> "RegulationClause | None":
        """The final clause applied to produce this version, in apply order.

        ``contributing_clauses.all()`` orders by ``RegulationClause``'s
        (empty) ``Meta.ordering`` and so is non-deterministic — ``[-1]`` and
        ``.last()`` can disagree across queries (Postgres heap order vs.
        ``ORDER BY pk``).  The canonical order lives on the through model
        ``CodeEditionProvisionVersionClause.apply_order`` (its ``Meta.ordering``),
        so the last row of its reverse set is the last-applied clause —
        consistent across the header, amendment chain, and next-version rows.

        Reads ``.all()`` and takes the last element in Python rather than
        ``.last()``: ``.last()`` reverses the queryset, which discards any
        prefetched cache and fires a fresh ``ORDER BY apply_order DESC LIMIT 1``
        per call — an N+1 across the amendment chain (``_provenance_rail.html``
        renders one row per version).  The search path prefetches this reverse
        set with ``clause__regulation`` (see ``search.engine.orchestration``), so
        the list access below hits the cache and the ``.clause`` joins are warm.
        """
        rows = list(self.codeeditionprovisionversionclause_set.all())
        return rows[-1].clause if rows else None

    @property
    def first_contributing_clause(self) -> "RegulationClause | None":
        """The first clause applied to produce this version, in apply order.

        Symmetric to :attr:`last_contributing_clause`.  ``apply_order`` on the
        through model is the 0-indexed position within the contract ordering
        ``(regulation.filed_date, clause_id)`` (see
        ``CodeEditionProvisionVersionClause`` and ``load_edition``'s
        ``_load_version_clause_links``), so the first row is the
        earliest-*filed* contributing regulation's clause — the right "this is
        what next brings in" anchor for the copy-reference line, and stable
        rather than the heap-order ``contributing_clauses.all()[0]`` it
        replaces.  Uses ``.all()[0]`` (not ``.first()``) so a prefetched
        through set is reused instead of firing a query per call.
        """
        rows = list(self.codeeditionprovisionversionclause_set.all())
        return rows[0].clause if rows else None

    @property
    def is_added_origin(self) -> bool:
        """True when this v0 was *created* by an ``amend_add`` clause.

        The CCM contract's "added" derivation: ``version == 0`` whose single
        contributing clause is an ``amend_add`` that first materialises the
        provision (base originals emit no clauses; ``amend_add`` on a *later*
        version merely adds content to an existing provision, which is an
        amendment, not an enactment).  Lets surfaces label the creating clause
        "added" rather than "amended" — it enacted the provision; there was no
        predecessor to amend.  Pairs with
        :attr:`CodeEditionProvision.origin_regulation`.
        """
        if self.version != 0:
            return False
        clause = self.first_contributing_clause
        return clause is not None and clause.action == RegulationClause.Action.AMEND_ADD

    @property
    def grouped_notes(self) -> GroupedNotes:
        """Notes bucketed into display tiers for ``_version_notes.html``.

        Cheap derivation over the small, pre-parsed ``notes`` list — the prefix
        parsing itself ran once at load time (see ``core.provision_notes``), so
        this only fans the tagged entries into annotation / integrity / record
        / sourcing for rendering.
        """
        return group_notes(self.notes)


class CodeEditionProvisionVersionClause(models.Model):
    """Through model for ``CodeEditionProvisionVersion.contributing_clauses``.

    The contract orders contributing clauses by
    ``(regulation.filed_date, clause_id)`` — the order the applicator
    actually processed them.  ``apply_order`` is the 0-indexed position
    within that ordering so consumers can reconstruct it without joining
    against ``Regulation.filed_date``.
    """

    version = models.ForeignKey(
        CodeEditionProvisionVersion, on_delete=models.CASCADE,
    )
    clause = models.ForeignKey(
        RegulationClause, on_delete=models.CASCADE,
    )
    apply_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "code_edition_provision_version_clauses"
        ordering = ["apply_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "clause"],
                name="version_clause_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["clause"]),
        ]

    def __str__(self):
        return f"{self.version} ← {self.clause} (#{self.apply_order})"


class ProvisionVersionTable(models.Model):
    """Table content associated with a provision version."""

    # Render-time annotations, not DB fields: the same strings with
    # within-edition citations linked (``corpus.cross_refs.annotate_tables``).
    linked_html: str
    linked_notes: str
    # This table's images, cropped, on the printable surfaces only.
    crops: list[dict[str, Any]]

    version = models.ForeignKey(
        CodeEditionProvisionVersion, on_delete=models.CASCADE, related_name="tables",
    )
    table_id = models.CharField(max_length=200)
    caption = models.CharField(max_length=500, blank=True, default="")
    images = models.JSONField(default=list)
    html = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "provision_version_tables"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "table_id"],
                name="table_version_table_id_unique",
            ),
        ]

    def __str__(self):
        return f"{self.version} — {self.table_id}"


class ProvisionVersionAsset(AssetManifestEntry):
    """An inline asset that one provision version's HTML names.

    Mirrors ``provisions[].versions[].assets[]``.  The scope is the version,
    not the regulation, because e-Laws names an asset per consolidation
    version: OBC 2012 puts the version in the directory
    (``120332_eV020_files/image001.gif``) and OBC 2006 puts it in the filename
    (``elaws_regs_060350_ev003-14.gif``).  The same figure is a different path
    in every version, so a regulation-scoped union can hold the paths but
    cannot say which version needs which.

    CCM derives this array from the HTML it writes, so an asset the HTML names
    cannot be absent from the manifest.  That closes the hole this model
    exists for: the three OBC editions declared 45 regulation-scoped entries
    while their HTML named 157 images, and nothing could see the difference
    because no manifest described it.
    """

    version = models.ForeignKey(
        CodeEditionProvisionVersion, on_delete=models.CASCADE,
        related_name="assets",
    )

    class Meta:
        db_table = "provision_version_assets"
        constraints = [
            models.UniqueConstraint(
                fields=["version", "path"],
                name="provision_version_asset_path_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["path"]),
        ]

    def __str__(self):
        return f"{self.version} :: {self.path}"


class ProvisionCrossReference(models.Model):
    """One internal citation in a provision version's body, resolved upstream.

    A provision's text cites others of the same code ("Sentence 3.2.1.1.(2)",
    "Table 9.10.14.4.", "Subsection 3.2.6.").  CCM detects each citation and —
    with the whole edition's version timeline in hand at assembly — resolves it
    to the *specific target version(s) in force while the citing version stood*
    (contract §"Top-level: ``cross_references[]``").

    ``targets`` is that resolution, stored exactly as shipped: a list of
    ``{"version": int, "effective_date": iso, "ineffective_date": iso|""}``
    already clipped to the citing version's window.  It is **not** re-derived
    here — the producer answered it once, authoritatively, and a second
    derivation is the divergence :class:`EditionTransition`'s ``pair_key`` rule
    exists to prevent.  Several entries mean the referent was amended while the
    citing version stood still (39% of OBC 2012 records); the surface picks the
    one in force on the date on screen.

    ``to_provision`` is **what the Code printed** — the citation's literal id,
    resolved.  On a record carrying a curator ``note`` this used to be our
    corrected reading; the producer moved that reading into ``alternates`` and
    leads with the printed id (contract §``cross_references[]``), because the
    Crown's words outrank our reading of them and the reader should see both.
    It is null only for a **no-link** correction: the printed id was never
    enacted, so there is nothing to point at, but ``surface_text`` and ``note``
    still ship so the citation is disclosed rather than silently dropped.

    ``alternates`` (reverse of :class:`ProvisionCrossReferenceAlternate`) holds
    the curator's *intended* reading when the printed id resolves but a human
    judged a different provision was meant — a transposed standard reference, a
    renumber the row never caught up with.  The renderer links the printed id
    as the primary anchor and hangs each alternate off it as a chip, the
    ``note`` explaining the divergence; ignoring it would silently link ~150
    corrected citations to the uncorrected provision, with no error to catch it.

    ``container`` names which emitted string the citation sits in — the
    version's own ``html``, or a table's ``html`` / ``notes`` (``table_id``
    identifies which).  ``start``/``end`` are character offsets into that
    string, shipped by the producer, which is what makes the anchor exact: a
    span may legitimately contain markup when the printed citation straddles a
    block boundary (``Section</p><p>9.38.``), and the renderer splits the
    anchor across the runs rather than dropping the link.

    ``occurrence`` is the pre-span fallback: for a payload built before CCM
    shipped spans, the load derives which literal occurrence of
    ``surface_text`` this record anchors to (:func:`corpus.cross_refs.assign_occurrences`).
    ``None`` there means the text could not be located — the citation still
    counts for the "cites"/"cited by" lists but is not linked inline.  Records
    carrying ``start``/``end`` never consult it.
    """

    # FK id-shadows, plugin-only — declared for Pyright.
    from_version_id: int
    to_provision_id: int | None
    # Reverse relation — declared for Pyright.
    alternates: "models.Manager[ProvisionCrossReferenceAlternate]"

    class Container(models.TextChoices):
        BODY = "body", "Body"
        TABLE = "table", "Table"
        NOTE = "note", "Table note"

    from_version = models.ForeignKey(
        CodeEditionProvisionVersion,
        on_delete=models.CASCADE,
        related_name="cross_references",
    )
    to_provision = models.ForeignKey(
        CodeEditionProvision,
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="cited_by",
    )
    surface_text = models.CharField(max_length=200)
    container = models.CharField(
        max_length=10, choices=Container.choices, default=Container.BODY,
    )
    #: Owning table for a ``table``/``note`` record, in the shipped
    #: ``Table-4.1.8.6.`` form (matches ``ProvisionVersionTable.table_id``).
    table_id = models.CharField(max_length=200, blank=True, default="")
    start = models.PositiveIntegerField(null=True, blank=True)
    end = models.PositiveIntegerField(null=True, blank=True)
    occurrence = models.PositiveSmallIntegerField(null=True, blank=True)
    targets = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True, default="")
    #: Emission order within the citing version — a stable render order for
    #: the "cites" list, and the tiebreak when two records share a surface.
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "provision_cross_references"
        ordering = ["order"]
        indexes = [
            models.Index(fields=["to_provision"]),
            models.Index(fields=["from_version"]),
        ]

    def __str__(self):
        target = self.to_provision or "(no link)"
        return f"{self.from_version} → {target} ({self.surface_text})"


class ProvisionCrossReferenceAlternate(models.Model):
    """A curator's *intended* reading of a citation whose printed id resolves.

    The parent :class:`ProvisionCrossReference` leads with what the Code
    printed; when a human judged a different provision was actually meant — and
    the printed id nonetheless resolves, so a redirect would break a link that
    was never wrong and a no-link would drop one that resolves fine — the
    intended reading rides here instead of replacing the primary.  The reader
    gets both: printed target as the anchor, this as a chip, the parent's
    ``note`` saying why two appear (contract §``cross_references[]`` →
    ``alternates[]``).

    ``targets`` is stored verbatim, exactly as the primary's is — the producer
    date-sliced it against the citing version's window with the same code path,
    so it is never re-derived here.  ``to_provision`` may be null on the same
    terms as the primary (an intended id that does not itself resolve), though
    in practice the intended reading is the one that does.  The field is a list
    because "printed vs intended" is unlikely to be the only case, but nothing
    yet emits more than one (``len(alternates) <= 1`` today).
    """

    # FK id-shadows, plugin-only — declared for Pyright.
    cross_reference_id: int
    to_provision_id: int | None

    cross_reference = models.ForeignKey(
        ProvisionCrossReference,
        on_delete=models.CASCADE,
        related_name="alternates",
    )
    to_provision = models.ForeignKey(
        CodeEditionProvision,
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="cited_as_alternate",
    )
    targets = models.JSONField(default=list, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "provision_cross_reference_alternates"
        ordering = ["order"]
        indexes = [models.Index(fields=["cross_reference"])]

    def __str__(self):
        return f"{self.cross_reference_id} alt→ {self.to_provision or '(no link)'}"


class ProvisionMapping(models.Model):
    """Old↔new provision identity mapping.

    The two endpoints may share an edition (intra-edition renumber
    triggered by a gazette amendment) or differ (cross-edition migration
    produced by CCM's edition matcher).  ``introduced_by_version`` is
    populated only for intra-edition rows — the version whose
    ``action == "renumbered"`` is the structural origin of the mapping.
    """

    # FK id-shadows, plugin-only — declared for Pyright.
    old_provision_id: int
    new_provision_id: int

    class MappingType(models.TextChoices):
        RENUMBERED = "renumbered", "Renumbered"
        SPLIT = "split", "Split"
        MERGED = "merged", "Merged"
        REPLACED = "replaced", "Replaced"

    old_provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE, related_name="mapped_forward",
    )
    new_provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE, related_name="mapped_back",
    )
    mapping_type = models.CharField(max_length=20, choices=MappingType.choices)
    introduced_by_version = models.ForeignKey(
        CodeEditionProvisionVersion,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="introduced_mappings",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "provision_mappings"
        constraints = [
            models.UniqueConstraint(
                fields=["old_provision", "new_provision"],
                name="provision_mapping_unique",
            ),
        ]

    def __str__(self):
        return f"{self.old_provision} → {self.new_provision} ({self.mapping_type})"


class ProvisionDisposition(models.Model):
    """Per-provision override of the covered-transition default.

    On a covered transition the absence of a mapping row already reads
    "no successor" (CCM emits a total mapping; see ``EditionTransition``).
    A disposition says more than absence can:

    - ``discontinued`` — an authoritative tombstone with provenance
      (``source``/``reasoning``), valuable where a reader might assume
      continuity (id reuse: 2006 C 1.3.5.4. is an edition-specific
      transition rule; the 2012 article at the same number is unrelated
      content).
    - ``not_processed`` — the content's fate lies outside our corpus
      (e.g. OBC 2006 Part 12 delegated to Supplementary Standard SB-12);
      rendered as the existing "not yet covered" marker, not a new state.

    Ingested by ``load_edition`` from the payload's
    ``provision_discontinuations`` key and from ``provision_mappings``
    rows carrying the ``"not_processed"`` sentinel.  The lineage resolver
    (``corpus.lineage.provision_lineage``) uses these to refine the covered-no-row
    marker; a ``not_processed`` record coexisting with mapping rows is a
    multi-leg verdict (e.g. a split with one leg outside the corpus), not
    a contradiction — the resolver surfaces it as an extra leg row.
    """

    # FK id-shadows, plugin-only — declared for Pyright.
    provision_id: int
    new_edition_id: int

    class Status(models.TextChoices):
        DISCONTINUED = "discontinued", "Discontinued"
        NOT_PROCESSED = "not_processed", "Not processed"

    provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE, related_name="dispositions",
    )
    new_edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="incoming_dispositions",
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    #: Where the content went, when known and outside the corpus — a
    #: document reference like "SB-10" ("" when unknown).  Sentinel
    #: mapping rows carry it in ``new_division`` (the field is document
    #: abuse there, never a real division); explicit entries in an
    #: optional ``target_reference`` key.  Named in the not-yet-covered
    #: lineage markers ("Some content moved to SB-10, not yet covered").
    target_reference = models.CharField(max_length=50, blank=True, default="")
    source = models.CharField(max_length=50, blank=True, default="")
    reasoning = models.TextField(blank=True, default="")

    class Meta:
        db_table = "provision_dispositions"
        constraints = [
            models.UniqueConstraint(
                fields=["provision", "new_edition"],
                name="provision_disposition_unique",
            ),
        ]

    def __str__(self):
        return f"{self.provision} -> {self.new_edition}: {self.status}"


class EditionTransition(models.Model):
    """Declares that an old→new edition transition's provision mapping is covered.

    Written by ``load_edition`` from the CCM payload's ``mapping_coverage``
    key.  CCM emits a **total** mapping for a covered transition — every
    carried-forward provision gets a row, identity carries included — so
    the absence of a row, tombstone, and sentinel positively asserts "no
    successor".  But only if we know the transition was mapped at all;
    this row is that knowledge: it lets the lineage resolver
    (``corpus.lineage.provision_lineage``) distinguish **discontinued** (covered, no
    row) from **no data yet** (transition never mapped).

    Coverage is declared explicitly rather than inferred from mapping-row
    existence: inference conflates "not mapped yet" with "mapped, zero
    identity changes", and a partial/failed load would silently read as
    covered.
    """

    # FK id-shadow, plugin-only — declared for Pyright (see CodeEdition).
    new_edition_id: int

    old_edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="transitions_forward",
    )
    new_edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="transitions_back",
    )
    loaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "edition_transitions"
        verbose_name = "Edition Transition"
        verbose_name_plural = "Edition Transitions"
        constraints = [
            models.UniqueConstraint(
                fields=["old_edition", "new_edition"],
                name="edition_transition_unique",
            ),
        ]

    def __str__(self):
        return f"{self.old_edition} → {self.new_edition}"


class CorpusCurrency(models.Model):
    """Precomputed masthead provenance stamp — one row (a singleton).

    The masthead's job is to say *what corpus you're querying* (left) and
    *how current the consolidation is* (right).  The currency date is a real
    selling point for a forensic tool, so it must be genuine — never faked or
    hardcoded (design handoff README §"Masthead fix").  Deriving it means a
    ``MAX(effective_date)`` aggregate over the whole corpus; running that on
    every request would be wasteful, so we snapshot it whenever data is
    (re)loaded via :meth:`refresh` (called at the end of ``load_edition``).
    The context processor then serves it with a single PK read.
    """

    #: This model only ever holds one row; we pin it to this PK.
    SINGLETON_PK = 1

    corpus_label = models.CharField(max_length=200, default="Ontario Building Code")
    corpus_span = models.CharField(max_length=50, blank=True, default="")
    data_current_to = models.DateField(null=True, blank=True)
    #: The corpus's first covered date as a real date — the start of
    #: ``corpus_span`` (``MIN(effective_date)`` over the provenance corpus).
    #: Backs the search "as-of" picker's lower bound and the out-of-coverage
    #: date notice, so neither has to re-parse the formatted span string.
    coverage_start = models.DateField(null=True, blank=True)
    #: The corpus's last covered date as a real date — the end of
    #: ``corpus_span`` (last in-force day for a closed corpus, else the most
    #: recent amendment).  Backs the search "as-of" default so it matches the
    #: masthead end date without re-parsing the formatted span string.
    coverage_end = models.DateField(null=True, blank=True)
    refreshed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "corpus_currency"
        verbose_name = "Corpus Currency"
        verbose_name_plural = "Corpus Currency"

    def __str__(self) -> str:
        return f"{self.corpus_label} (current to {self.data_current_to})"

    @classmethod
    def get_solo(cls) -> "CorpusCurrency | None":
        """Return the singleton row, or ``None`` before the first load."""
        return cls.objects.filter(pk=cls.SINGLETON_PK).first()

    @classmethod
    def refresh(cls) -> "CorpusCurrency":
        """Recompute the masthead stamp from the *provenance* corpus and persist it.

        Scope is editions that actually carry regulation data — the
        version-tracked provenance system (currently OBC only).  The shared
        ``code_editions`` table also holds search-metadata-only editions for
        other codes (NBC, Quebec, …, back to 1997); those have no regulations
        and must NOT widen the corpus the regulation/provenance pages describe.

        - ``corpus_span`` = the precise window we cover: first in-force date →
          last covered date (``ineffective``/``superseded`` is exclusive, so we
          step back a day), or ``… – present`` if still current.  Full dates,
          derived from ``effective_date`` — not the edition-label ``year``.
        - ``data_current_to`` = how current the consolidation is.  Only set
          while the corpus is still in force (the most recent amendment we've
          ingested); for a closed/superseded corpus the span already states the
          end date, so this stays None and the masthead drops the redundant
          "current to" endpoint.
        - ``corpus_label`` = a provenance code's display name, else the Ontario
          default.
        """
        def _fmt(d: date) -> str:
            # ISO 8601 calendar date (e.g. "2014-01-01").
            return d.isoformat()

        prov_editions = CodeEdition.objects.annotate(
            _reg_count=Count("regulations")
        ).filter(_reg_count__gt=0)

        agg = prov_editions.aggregate(
            first_eff=Min("effective_date"),
            last_end=Max("ineffective_date"),
        )
        first_eff = agg["first_eff"]

        span = ""
        data_current_to = None
        coverage_end = None
        if first_eff:
            # The corpus's coverage closes when its latest edition ceased to be
            # in force; None on both means it's still the current edition.
            # ``Max`` ignores NULLs, so an open-ended current edition
            # (ineffective_date IS NULL) sitting alongside older, closed
            # editions would otherwise report the older end date and mark the
            # corpus closed — check for any still-open edition first.
            has_open_edition = prov_editions.filter(
                ineffective_date__isnull=True
            ).exists()
            end = None if has_open_edition else agg["last_end"]
            if end:
                last_covered = end - timedelta(days=1)  # exclusive boundary
                span = f"{_fmt(first_eff)} – {_fmt(last_covered)}"
                coverage_end = last_covered
            else:
                span = f"{_fmt(first_eff)} – present"
                data_current_to = Regulation.objects.filter(
                    edition__in=prov_editions
                ).aggregate(mx=Max("effective_date"))["mx"]
                coverage_end = data_current_to

        label = "Ontario Building Code"
        code = (
            Code.objects.filter(editions__in=prov_editions)
            .exclude(display_name="")
            .order_by("id")
            .distinct()
            .first()
        )
        if code:
            label = code.display_name

        obj, _ = cls.objects.update_or_create(
            pk=cls.SINGLETON_PK,
            defaults={
                "corpus_label": label,
                "corpus_span": span,
                "data_current_to": data_current_to,
                # ``first_eff`` is the same MIN that opens ``corpus_span``;
                # store it discretely so the search picker/notice never has to
                # parse it back out of the display string.
                "coverage_start": first_eff,
                "coverage_end": coverage_end,
            },
        )
        return obj


class Organization(models.Model):
    """The billing entity: a firm, or one person who bought for themselves.

    This is dj-stripe's subscriber model (``DJSTRIPE_SUBSCRIBER_MODEL``), so
    every subscription in the product hangs here and a person reaches it
    through a :class:`Membership`.  There is one billing path, not two.  A
    reader who buys for themselves gets an organization of one, named after
    them, and never meets the word "organization" anywhere on screen.

    Two fields are deliberately absent:

    * **No ``stripe_customer_id``.**  dj-stripe's ``Customer.subscriber``
      points here, and that is the one link.  A second copy can disagree with
      the first.
    * **No seat count.**  The seat count is the ``quantity`` on the mirrored
      Stripe subscription, so a change made in Stripe needs no deploy and
      cannot disagree with what was charged.

    ``email`` is not decoration: dj-stripe refuses a subscriber model with no
    ``email`` attribute, and the invoice needs an address in any case.
    """

    # Auto pk, plugin-only — declared for Pyright.
    id: int
    #: Reverse relation — the people here (see ``Membership``).
    memberships: "models.Manager[Membership]"
    #: Reverse relation — invitations sent, accepted or not (see ``Invite``).
    invites: "models.Manager[Invite]"
    #: Reverse relation — dj-stripe's own, from ``Customer.subscriber``.
    djstripe_customers: "models.Manager[Customer]"

    name = models.CharField(max_length=200)
    # Where the invoice goes.  For an organization of one this is the buyer's
    # own address, which is what Stripe already had.
    email = models.EmailField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "organizations"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def active_subscription(self) -> "Subscription | None":
        """The live subscription, or ``None``.

        "Live" is the test the individual gate has always made: ``active`` or
        ``trialing``.  Any other state buys nothing, ``past_due`` included —
        Stripe moves a payer back to ``active`` by itself once money lands.
        """
        return Subscription.objects.filter(
            customer__subscriber=self,
            stripe_data__status__in=["active", "trialing"],
        ).first()

    @property
    def has_active_subscription(self) -> bool:
        return self.active_subscription is not None

    @property
    def seats_bought(self) -> int:
        """How many seats this organization pays for, straight from Stripe.

        Read from the mirrored subscription rather than stored, so the number
        on screen is the number on the invoice.  Stripe writes the quantity on
        the subscription item; older payloads also carry a top-level
        ``quantity``.  Both shapes are read, so no upgrade of dj-stripe can
        quietly make this answer zero.
        """
        subscription = self.active_subscription
        if subscription is None:
            return 0
        data: dict[str, Any] = subscription.stripe_data or {}
        quantity = data.get("quantity")
        if quantity is None:
            items = (data.get("items") or {}).get("data") or []
            quantity = sum(int(item.get("quantity") or 0) for item in items)
        return int(quantity or 0)

    @property
    def seats_used(self) -> int:
        """Memberships that consume a seat.  See :class:`Membership`."""
        return self.memberships.filter(role__in=Membership.SEAT_ROLES).count()

    @property
    def seats_free(self) -> int:
        """Seats bought and not yet used.  Never negative.

        The seat count can fall below the people already here — an admin lowers
        the quantity in the Stripe portal, or a payment fails.  Nobody is
        removed for that, because a gate that acts on an existing member locks
        out somebody who did nothing wrong.  It only means that no new person
        can join until the two numbers agree again.
        """
        return max(0, self.seats_bought - self.seats_used)

    @property
    def is_personal(self) -> bool:
        """True when this organization is one person who bought for themselves.

        What the interface asks before it says the word "organization" out
        loud.  A reader who bought alone never meets the concept.

        **The seat count is part of the test, not just the head count.**  A
        firm that buys five seats has one member for as long as it takes to
        send the first invitation, and judging by members alone would call
        that firm personal — which hides the invitation form from the only
        person who can use it, and leaves the four paid seats unreachable.
        Buying more than one seat is the act that says this is a firm.
        """
        return (
            self.seats_bought <= 1
            and self.memberships.count() <= 1
            and not self.invites.filter(
                accepted_at__isnull=True, revoked_at__isnull=True
            ).exists()
        )


class Membership(models.Model):
    """One person in one organization.

    A row in a seat-consuming role **is** the used seat.  There is no separate
    seat object, because a seat that is nobody is only a number, and that
    number is on the Stripe subscription already.

    Three roles.  The split answers a hole in the obvious two-role design: if
    an admin were simply exempt from consuming a seat, a firm could make all
    six people admins and pay for nothing.  So the exemption comes with no
    access.

    * ``member`` — a seat, and Pro access.
    * ``admin`` — a seat, Pro access, and may invite, remove and change seats.
    * ``billing`` — **no** seat and **no** Pro access; may manage seats and
      reach the invoice.  This is the office manager who buys for the firm and
      never opens a provision.
    """

    # Auto pk and FK columns, plugin-only — declared for Pyright.
    id: int
    organization_id: int
    user_id: int

    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        ADMIN = "admin", "Admin"
        BILLING = "billing", "Billing only"

    #: The roles that consume a seat.  Also the roles that grant Pro access:
    #: one name for both on purpose, because a role that reads is a role that
    #: is paid for, and two lists could drift into a free-access role.
    SEAT_ROLES = (Role.MEMBER, Role.ADMIN)
    #: The roles that may invite, remove, and change the seat count.
    ADMIN_ROLES = (Role.ADMIN, Role.BILLING)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "organization_memberships"
        unique_together = ("organization", "user")
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.user.email} in {self.organization.name} ({self.role})"

    @property
    def consumes_seat(self) -> bool:
        return self.role in Membership.SEAT_ROLES

    @property
    def grants_access(self) -> bool:
        """Whether this row is a reason to read every edition."""
        return self.role in Membership.SEAT_ROLES

    @property
    def is_admin(self) -> bool:
        return self.role in Membership.ADMIN_ROLES


class Invite(models.Model):
    """An invitation to take a seat.

    The invitation is where a person is added, so the invitation is where the
    seat check runs — at acceptance, the moment a seat is really taken.  A
    check at sign-in would lock out somebody who did nothing wrong.

    Only the hash of the token is stored, exactly as :class:`ApiKey` does it.
    The link is emailed once.  A lost link is replaced by a new invitation,
    never recovered.
    """

    # Auto pk and FK column, plugin-only — declared for Pyright.
    id: int
    organization_id: int

    #: How long a link works.  Long enough for somebody on holiday, short
    #: enough that a mail forwarded a year later opens nothing.
    LIFETIME = timedelta(days=14)
    #: How much of the token stays in clear, to find the row in one query.
    LOOKUP_LENGTH = 11

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invites"
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=16, choices=Membership.Role.choices, default=Membership.Role.MEMBER
    )
    lookup = models.CharField(max_length=16, db_index=True)
    hashed_token = models.CharField(max_length=64)
    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="invites_sent"
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    # Withdrawn, never deleted: the row is the record that somebody was asked.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "organization_invites"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "accepted_at"])]

    def __str__(self) -> str:
        return f"{self.email} to {self.organization.name}"

    @staticmethod
    def hash_token(token: str) -> str:
        """The stored form of a token.  SHA-256, for the reason in ``ApiKey``."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def generate(
        cls,
        organization: Organization,
        email: str,
        role: str,
        invited_by: "User | None" = None,
    ) -> tuple["Invite", str]:
        """Create an invitation, and return it with the one copy of its token."""
        token = secrets.token_urlsafe(32)
        invite = cls.objects.create(
            organization=organization,
            email=email.strip().lower(),
            role=role,
            lookup=token[: cls.LOOKUP_LENGTH],
            hashed_token=cls.hash_token(token),
            invited_by=invited_by,
            expires_at=timezone.now() + cls.LIFETIME,
        )
        return invite, token

    @classmethod
    def open_for_token(cls, token: str) -> "Invite | None":
        """The live invitation this token opens, or ``None``.

        One indexed query on the clear prefix, then a hash comparison — the
        shape ``ApiKey.lookup`` uses.  A withdrawn link, a spent link and an
        invented link all answer ``None``, so none of them tells the holder
        that any of the others exists.
        """
        if not token:
            return None
        hashed = cls.hash_token(token)
        for invite in cls.objects.filter(lookup=token[: cls.LOOKUP_LENGTH]):
            if secrets.compare_digest(invite.hashed_token, hashed) and invite.is_open:
                return invite
        return None

    @property
    def is_open(self) -> bool:
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )
