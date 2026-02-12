from django.contrib import admin

from .models import (
    CodeEdition,
    CodeMap,
    CodeMapNode,
    CodeSystem,
    ProvinceCodeMap,
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


admin.site.register(CodeMap)
admin.site.register(CodeMapNode)
admin.site.register(CodeSystem)
admin.site.register(CodeEdition)
admin.site.register(ProvinceCodeMap)
