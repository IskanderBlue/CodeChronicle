from django.contrib import admin

from .models import User, SearchHistory


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'username', 'is_active', 'date_joined']
    search_fields = ['email', 'username']
    list_filter = ['is_active', 'is_staff']


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'ip_address', 'query', 'result_count', 'timestamp']
    list_filter = ['timestamp']
    search_fields = ['query', 'user__email']
    readonly_fields = ['parsed_params']
