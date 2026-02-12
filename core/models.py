"""
Core models for CodeChronicle.
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """
    Custom manager for the email-only User model.
    """
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

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
    pro_courtesy = models.BooleanField(default=False, help_text="Grant Pro status without Stripe subscription")
    date_joined = models.DateTimeField(default=timezone.now)

    # Stripe customer ID (managed by dj-stripe, but useful for quick lookup)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

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
            stripe_data__status__in=['active', 'trialing'],
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
        db_table = 'query_cache'
        verbose_name = 'Query Cache'
        verbose_name_plural = 'Query Caches'


class SearchHistory(models.Model):
    """
    Track user search history for analytics and rate limiting.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='searches',
        null=True,  # Allow anonymous searches
        blank=True
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    query = models.TextField()
    parsed_params = models.JSONField(default=dict)
    result_count = models.IntegerField(default=0)
    top_results = models.JSONField(default=list)  # Store minimal metadata for quick links
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'search_history'
        verbose_name = 'Search History'
        verbose_name_plural = 'Search History'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['ip_address', 'timestamp']),
            models.Index(fields=['user', 'query']),
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
        db_table = 'code_maps'
        verbose_name = 'Code Map'
        verbose_name_plural = 'Code Maps'

    def __str__(self):
        return f"{self.map_code} ({self.code_name})"


class CodeMapNode(models.Model):
    """
    Disaggregated map content for a specific section node.
    """
    code_map = models.ForeignKey(CodeMap, on_delete=models.CASCADE, related_name='nodes')
    node_id = models.CharField(max_length=200)
    title = models.CharField(max_length=500)
    page = models.IntegerField(null=True, blank=True)
    page_end = models.IntegerField(null=True, blank=True)
    html = models.TextField(null=True, blank=True)
    notes_html = models.TextField(null=True, blank=True)
    keywords = ArrayField(models.CharField(max_length=100), null=True, blank=True)
    bbox = models.JSONField(null=True, blank=True)
    parent_id = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        db_table = 'code_map_nodes'
        verbose_name = 'Code Map Node'
        verbose_name_plural = 'Code Map Nodes'
        indexes = [
            models.Index(fields=['node_id'], name='code_mapnode_node_id_idx'),
            GinIndex(fields=['keywords'], name='code_mapnode_keywords_gin'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['code_map', 'node_id'], name='code_map_node_unique'),
        ]

    def __str__(self):
        return f"{self.code_map.map_code}:{self.node_id}"


class CodeSystem(models.Model):
    """
    High-level code system (e.g., OBC, NBC, IUGP9).
    """
    code = models.CharField(max_length=20, unique=True)
    display_name = models.CharField(max_length=200, blank=True, default='')
    is_national = models.BooleanField(default=False)
    document_type = models.CharField(
        max_length=20,
        default='code',
        choices=[('code', 'code'), ('guide', 'guide')],
    )

    class Meta:
        db_table = 'code_systems'
        verbose_name = 'Code System'
        verbose_name_plural = 'Code Systems'

    def __str__(self):
        return self.code


class CodeEdition(models.Model):
    """
    A specific edition/version of a code system.
    """
    system = models.ForeignKey(CodeSystem, on_delete=models.CASCADE, related_name='editions')
    edition_id = models.CharField(max_length=50)
    year = models.IntegerField()
    map_codes = ArrayField(models.CharField(max_length=100))
    effective_date = models.DateField()
    superseded_date = models.DateField(null=True, blank=True)
    pdf_files = models.JSONField(null=True, blank=True)
    download_url = models.CharField(max_length=500, blank=True, default='')
    amendments = models.JSONField(null=True, blank=True)
    regulation = models.CharField(max_length=200, blank=True, default='')
    version_number = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default='')
    source_url = models.CharField(max_length=500, blank=True, default='')
    amendments_applied = models.JSONField(null=True, blank=True)
    is_guide = models.BooleanField(default=False)

    class Meta:
        db_table = 'code_editions'
        verbose_name = 'Code Edition'
        verbose_name_plural = 'Code Editions'
        constraints = [
            models.UniqueConstraint(fields=['system', 'edition_id'], name='code_system_edition_unique'),
        ]
        indexes = [
            models.Index(fields=['system', 'effective_date'], name='code_edition_effective_idx'),
        ]

    def __str__(self):
        return f"{self.system.code}_{self.edition_id}"

    @property
    def code_name(self) -> str:
        return f"{self.system.code}_{self.edition_id}"


class ProvinceCodeMap(models.Model):
    """
    Map a province abbreviation to its primary code system.
    """
    province = models.CharField(max_length=2, unique=True)
    code_system = models.ForeignKey(CodeSystem, on_delete=models.CASCADE, related_name='provinces')

    class Meta:
        db_table = 'province_code_maps'
        verbose_name = 'Province Code Map'
        verbose_name_plural = 'Province Code Maps'

    def __str__(self):
        return f"{self.province} -> {self.code_system.code}"
