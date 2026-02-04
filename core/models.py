"""
Core models for CodeChronicle.
"""
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
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
        """Check if user has an active Pro subscription."""
        from djstripe.models import Customer, Subscription
        # dj-stripe uses 'subscriber' to link to the user model
        customer = Customer.objects.filter(subscriber=self).first()
        if not customer:
            return False
        return Subscription.objects.filter(
            customer=customer,
            status__in=['active', 'trialing']
        ).exists()


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
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'search_history'
        verbose_name = 'Search History'
        verbose_name_plural = 'Search History'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['ip_address', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.user or self.ip_address}: {self.query[:50]}"
