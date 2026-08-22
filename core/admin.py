from django.contrib import admin

from core.models import (
    AuthEvent,
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    Invite,
    Membership,
    Organization,
    ProvinceCode,
    ProvisionFeedback,
    ProvisionMapping,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
    SearchHistory,
    User,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_active', 'pro_courtesy', 'date_joined']
    search_fields = ['email']
    list_filter = ['is_active', 'is_staff', 'pro_courtesy']


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'ip_address', 'query', 'result_count', 'timestamp']
    list_filter = ['timestamp']
    search_fields = ['query', 'user__email']
    readonly_fields = ['parsed_params']


@admin.register(ProvisionFeedback)
class ProvisionFeedbackAdmin(admin.ModelAdmin):
    """Triage a reader report in full.

    The /insights/ queue is the daily view and moves the status only. This is
    where the resolution note gets written, because a free-text answer wants a
    real text area and belongs to the rare act of closing a report rather than
    to the frequent act of reading the queue.
    """

    list_display = ['target_ref', 'status', 'email', 'surface', 'created_at']
    list_filter = ['status', 'surface', 'created_at']
    search_fields = ['note', 'email', 'provision_id', 'reg_id', 'code_edition']
    readonly_fields = [
        'code_edition', 'division', 'provision_id', 'version', 'reg_id',
        'note', 'email', 'user', 'ip_address', 'surface', 'created_at',
    ]


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


class MembershipInline(admin.TabularInline):
    """The seats, on the organization that pays for them.

    Inline rather than a separate page because a membership means nothing
    alone: the question an operator has is always "who is in this firm".
    """

    model = Membership
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "seats_used", "seats_bought", "created_at"]
    search_fields = ["name", "email"]
    inlines = [MembershipInline]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["email", "organization", "role", "created_at", "accepted_at"]
    search_fields = ["email", "organization__name"]
    list_filter = ["role"]
