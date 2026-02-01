"""
URL configuration for code_chronicle project.
"""
from django.contrib import admin
from django.urls import path, include

from api.views import api

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    path('accounts/', include('allauth.urls')),
    path('stripe/', include('djstripe.urls', namespace='djstripe')),
    path('', include('core.urls')),
]
