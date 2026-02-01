"""
Core models for CodeChronicle.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for CodeChronicle.
    Uses email as the primary identifier.
    """
    email = models.EmailField(unique=True)
    
    # Stripe customer ID (managed by dj-stripe, but useful for quick lookup)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return self.email
    
    @property
    def has_active_subscription(self) -> bool:
        """Check if user has an active Pro subscription."""
        # Will be implemented with dj-stripe integration
        return False


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
