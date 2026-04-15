from django.contrib import admin

from .models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    CodeMap,
    CodeMapNode,
    ProvinceCode,
    ProvisionEditionMapping,
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


admin.site.register(Code)
admin.site.register(CodeEdition)
admin.site.register(CodeMap)
admin.site.register(CodeMapNode)
admin.site.register(ProvinceCode)
admin.site.register(Regulation)
admin.site.register(RegulationClause)
admin.site.register(CodeEditionProvision)
admin.site.register(CodeEditionProvisionVersion)
admin.site.register(ProvisionVersionTable)
admin.site.register(ProvisionEditionMapping)
