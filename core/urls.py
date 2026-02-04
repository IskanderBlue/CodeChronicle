"""
URL patterns for core app (frontend pages).
"""
from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('pricing/', views.pricing, name='pricing'),
    path('search-results/', views.search_results, name='search_results'),
]
