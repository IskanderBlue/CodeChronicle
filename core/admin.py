from django.contrib import admin

from .models import (
    AuthEvent,
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    ProvinceCode,
    ProvisionMapping,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
    SearchHistory,
    User,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_active', 'pro_courtesy', 'stripe_customer_id', 'date_joined']
    search_fields = ['email', 'stripe_customer_id']
    list_filter = ['is_active', 'is_staff', 'pro_courtesy']


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'ip_address', 'query', 'result_count', 'timestamp']
    list_filter = ['timestamp']
    search_fields = ['query', 'user__email']
    readonly_fields = ['parsed_params']


@admin.register(EngagementEvent)
class EngagementEventAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'object_type', 'object_id', 'user', 'ip_address', 'timestamp']
    list_filter = ['event_type', 'timestamp']
    search_fields = ['object_type', 'user__email']
    # Append-only analytics log: inspect, never hand-edit.
    readonly_fields = [
        'user', 'ip_address', 'event_type', 'object_type', 'object_id',
        'search', 'context', 'timestamp',
    ]

    def has_add_permission(self, request):
        return False


@admin.register(AuthEvent)
class AuthEventAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'email', 'ip_address', 'user', 'timestamp']
    list_filter = ['event_type', 'timestamp']
    search_fields = ['email', 'ip_address', 'user__email']
    # Append-only security audit log: inspect (e.g. failed-login bursts by IP),
    # never hand-edit.
    readonly_fields = ['user', 'email', 'ip_address', 'event_type', 'timestamp']

    def has_add_permission(self, request):
        return False


admin.site.register(Code)
admin.site.register(CodeEdition)
admin.site.register(ProvinceCode)
admin.site.register(Regulation)
admin.site.register(RegulationClause)
admin.site.register(CodeEditionProvision)
admin.site.register(CodeEditionProvisionVersion)
admin.site.register(ProvisionVersionTable)
admin.site.register(ProvisionMapping)
