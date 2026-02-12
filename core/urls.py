"""
URL patterns for core app (frontend pages).
"""
from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('pricing/', views.pricing, name='pricing'),
    path('history/', views.history, name='history'),
    path('settings/', views.user_settings, name='user_settings'),
    path('search-results/', views.search_results, name='search_results'),
    path('create-checkout-session/', views.create_checkout_session, name='create_checkout_session'),
    path('stripe/success/', views.stripe_success, name='stripe_success'),
    path('stripe/cancel/', views.stripe_cancel, name='stripe_cancel'),
    path('stripe/portal/', views.create_customer_portal_session, name='stripe_portal'),
]
