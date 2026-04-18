"""
Core models for CodeChronicle.
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import connection, models
from django.utils import timezone


class UserManager(BaseUserManager):
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

    objects = UserManager()

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
        from djstripe.models import Customer, Subscription

        customer = Customer.objects.filter(subscriber=self).first()
        if not customer and self.stripe_customer_id:
            customer = Customer.objects.filter(id=self.stripe_customer_id).first()
            if customer and not customer.subscriber:
                customer.subscriber = self
                customer.save(update_fields=["subscriber"])
        if not customer:
            return False
        return Subscription.objects.filter(
            customer=customer,
            stripe_data__status__in=["active", "trialing"],
        ).exists()


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

    class Meta:
        db_table = "query_cache"
        verbose_name = "Query Cache"
        verbose_name_plural = "Query Caches"


class SearchHistory(models.Model):
    """
    Track user search history for analytics and rate limiting.
    """

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


class CodeMap(models.Model):
    """
    Top-level map record that stores map identity for a specific code edition.
    """

    code_name = models.CharField(max_length=100)
    map_code = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "code_maps"
        verbose_name = "Code Map"
        verbose_name_plural = "Code Maps"

    def __str__(self):
        return f"{self.map_code} ({self.code_name})"


class CodeMapNode(models.Model):
    """
    Disaggregated map content for a specific section node.
    """

    code_map = models.ForeignKey(CodeMap, on_delete=models.CASCADE, related_name="nodes")
    node_id = models.CharField(max_length=200)
    title = models.CharField(max_length=500)
    page = models.IntegerField(null=True, blank=True)
    page_end = models.IntegerField(null=True, blank=True)
    initial_page_top = models.FloatField(null=True, blank=True)
    final_page_bottom = models.FloatField(null=True, blank=True)
    html = models.TextField(null=True, blank=True)
    notes_html = models.TextField(null=True, blank=True)
    keyword_counts = models.JSONField(
        null=True,
        blank=True,
        help_text='{"keyword": count} — term frequency per node',
    )
    parent_id = models.CharField(max_length=200, null=True, blank=True)
    division = models.CharField(max_length=10, default="", blank=True)
    provision_transitions = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "code_map_nodes"
        verbose_name = "Code Map Node"
        verbose_name_plural = "Code Map Nodes"
        indexes = [
            models.Index(fields=["node_id"], name="code_mapnode_node_id_idx"),
            GinIndex(fields=["keyword_counts"], name="code_mapnode_kwcounts_gin"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["code_map", "node_id", "division"], name="code_map_node_unique"
            ),
        ]

    def __str__(self):
        prefix = f"{self.division}-" if self.division else ""
        return f"{self.code_map.map_code}:{prefix}{self.node_id}"


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

    code = models.ForeignKey(Code, on_delete=models.CASCADE, related_name="editions")
    edition_id = models.CharField(max_length=50)
    year = models.IntegerField()
    map_codes = ArrayField(models.CharField(max_length=100))
    effective_date = models.DateField()
    superseded_date = models.DateField(null=True, blank=True)
    ineffective_date = models.DateField(null=True, blank=True)
    amendment_chain_complete = models.BooleanField(default=False)
    pdf_files = models.JSONField(null=True, blank=True)
    download_url = models.CharField(max_length=500, blank=True, default="")
    amendments = models.JSONField(null=True, blank=True)
    regulation = models.CharField(max_length=200, blank=True, default="")
    version_number = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default="")
    source_url = models.CharField(max_length=500, blank=True, default="")
    amendments_applied = models.JSONField(null=True, blank=True)
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

    class Role(models.TextChoices):
        BASE = "base", "Base"
        AMENDMENT = "amendment", "Amendment"

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

    class Meta:
        db_table = "regulations"
        indexes = [
            models.Index(fields=["edition", "effective_date"]),
        ]

    def __str__(self):
        return f"O. Reg. {self.reg_id} ({self.role})"


class RegulationClause(models.Model):
    """A single amendment directive within a regulation."""

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
    action = models.CharField(max_length=50, choices=Action.choices)
    target_level = models.CharField(
        max_length=50, choices=TargetLevel.choices, blank=True, default=""
    )
    target_id = models.CharField(max_length=200, blank=True, default="")
    clause_text = models.TextField(blank=True, default="")
    strike_text = models.TextField(null=True, blank=True)
    sub_text = models.TextField(null=True, blank=True)
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


class CodeEditionProvision(models.Model):
    """Structural identity of a provision within an edition. No content."""

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


class CodeEditionProvisionVersion(models.Model):
    """A frozen snapshot of a provision's content at a point in the amendment chain."""

    class Action(models.TextChoices):
        ORIGINAL = "original", "Original"
        ADDED = "added", "Added"
        REVOKE_AND_SUBSTITUTE = "revoke_and_substitute", "Revoke and substitute"
        AMEND_ADD = "amend_add", "Amend by adding"
        AMEND_STRIKE_SUB = "amend_strike_sub", "Amend by striking and substituting"
        REVOKED = "revoked", "Revoked"
        RENUMBERED = "renumbered", "Renumbered"

    provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE, related_name="versions",
    )
    version = models.PositiveSmallIntegerField(default=0)
    clause = models.ForeignKey(
        RegulationClause, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="provision_versions",
    )
    action = models.CharField(
        max_length=50, choices=Action.choices, default=Action.ORIGINAL
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
            models.Index(fields=["clause"]),
            models.Index(fields=["effective_date", "ineffective_date"]),
        ]

    def __str__(self):
        return f"{self.provision} v{self.version}"


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


class KeywordIDF(models.Model):
    """Unmanaged model backed by the keyword_idf materialized view."""

    map_code = models.CharField(max_length=100)
    keyword = models.CharField(max_length=100)
    doc_count = models.IntegerField()
    total_docs = models.IntegerField()
    idf = models.FloatField()

    class Meta:
        managed = False
        db_table = "keyword_idf"

    @classmethod
    def refresh(cls) -> None:
        with connection.cursor() as cursor:
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY keyword_idf;")
