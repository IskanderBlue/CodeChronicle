"""
Core models for CodeChronicle.
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Count, Max, Min
from django.utils import timezone
from djstripe.models import Customer, Subscription

from core.provision_notes import GroupedNotes, group_notes


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

    email = models.EmailField(unique=True)

    # Flags
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    pro_courtesy = models.BooleanField(
        default=False, help_text="Grant Pro status without Stripe subscription"
    )
    date_joined = models.DateTimeField(default=timezone.now)

    # Stripe customer ID (managed by dj-stripe, but useful for quick lookup)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)

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
        """
        Check if user has an active Pro subscription.
        Supports:
        1. Explicit courtesy flag on user
        2. Real Stripe subscription
        """
        # 1. Check explicit courtesy flag
        if self.pro_courtesy:
            return True

        # 2. Check Stripe via dj-stripe
        customer = Customer.objects.filter(subscriber=self).first()
        if not customer and self.stripe_customer_id:
            # Fall back to the raw Stripe id when dj-stripe hasn't linked the
            # Customer.subscriber yet.  Read-only on purpose: a property getter
            # must not write — the subscriber back-link is established in the
            # checkout/webhook path (see core.views.billing), not here, so a
            # plain GET render never triggers a DB write.
            customer = Customer.objects.filter(id=self.stripe_customer_id).first()
        if not customer:
            return False
        return Subscription.objects.filter(
            customer=customer,
            stripe_data__status__in=["active", "trialing"],
        ).exists()

    @property
    def latest_terms_acceptance(self) -> "TermsAcceptance | None":
        """The user's most recent Terms / Privacy Policy acceptance, or None."""
        return self.terms_acceptances.order_by("-accepted_at").first()

    def has_accepted_terms(self, version: str) -> bool:
        """Whether this user has a recorded acceptance of ``version``."""
        return self.terms_acceptances.filter(terms_version=version).exists()


class TermsAcceptance(models.Model):
    """Append-only record of a user's acceptance of the Terms of Service /
    Privacy Policy.

    One immutable row per acceptance event — written at signup (clickwrap) and
    on any future re-acceptance prompt — so the full history (which version,
    when, and from where) is preserved as evidence rather than overwritten. The
    account-audit counterpart to ``AuthEvent``: ``user`` is ``SET_NULL`` so the
    record outlives the account, with ``email`` mirrored so a row stands on its
    own. Written in the signup flow; see ``core.forms.CustomSignupForm``.
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
        ]

    def __str__(self) -> str:
        who = self.email or (self.user.email if self.user else "?")
        return f"{who} accepted Terms {self.terms_version}"


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
    # date rolls (see ``api.llm_parser.parse_user_query``).  An explicit /
    # historical date is stable and stays cached indefinitely.
    date_is_relative = models.BooleanField(default=False)

    class Meta:
        db_table = "query_cache"
        verbose_name = "Query Cache"
        verbose_name_plural = "Query Caches"


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

    class Meta:
        db_table = "search_history"
        verbose_name = "Search History"
        verbose_name_plural = "Search History"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["ip_address", "timestamp"]),
            models.Index(fields=["user", "query"]),
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
    ``core.events.record_event``.

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


class AuthEvent(models.Model):
    """Append-only security audit log of authentication outcomes.

    The security counterpart to ``SearchHistory``/``EngagementEvent`` (which
    record *content* access): one row per login, logout, or failed login, so a
    credential-stuffing run or a successful break-in leaves a queryable trail
    (failed-attempt rate per IP/email, last successful login per user).  This is
    the application-layer access log; it does **not** see direct database access
    that bypasses Django — see ``docs/security/breach-response-plan.md``.

    Writes are best-effort and must never block authentication — see
    ``core.auth_audit``.  ``user`` is ``SET_NULL`` so the trail outlives the
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
        return f"O. Reg. {self.reg_id} ({self.role})"

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


class RegulationAsset(models.Model):
    """An inline-image asset referenced from a regulation's clause HTML.

    Mirrors the ``regulations[].assets[]`` registry CCM emits for
    e-Laws-derived editions.  Stored as a manifest only — the bytes live
    under the asset root at ``path`` (e.g.
    ``laws/images/en/R19088_e_files/image007.gif``).  The same relative
    path is the URL path served at host root, so the inline
    ``<img src="/laws/images/...">`` references in ``versions[].html``
    resolve without HTML rewriting.
    """

    regulation = models.ForeignKey(
        Regulation, on_delete=models.CASCADE, related_name="assets",
    )
    path = models.CharField(max_length=500)
    original_url = models.CharField(max_length=500, blank=True, default="")
    sha256 = models.CharField(max_length=64, blank=True, default="")
    byte_size = models.BigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True, default="")

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
        set with ``clause__regulation`` (see ``api.search.orchestration``), so
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
    (``core.provision_lineage``) uses these to refine the covered-no-row
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
    (``core.provision_lineage``) distinguish **discontinued** (covered, no
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
