"""
URL patterns for core app (frontend pages).
"""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("pricing/", views.pricing, name="pricing"),
    path("terms/", views.terms_of_service, name="terms_of_service"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    path("sources/", views.data_sources, name="data_sources"),
    path("history/", views.history, name="history"),
    path("settings/", views.user_settings, name="user_settings"),
    path("search-results/", views.search_results, name="search_results"),
    path("viewer/edition-nav/", views.viewer_edition_nav, name="viewer_edition_nav"),
    path("viewer/edition-dates/", views.viewer_edition_dates, name="viewer_edition_dates"),
    path("viewer/section-content/", views.viewer_section_content, name="viewer_section_content"),
    path("create-checkout-session/", views.create_checkout_session, name="create_checkout_session"),
    path("stripe/success/", views.stripe_success, name="stripe_success"),
    path("stripe/cancel/", views.stripe_cancel, name="stripe_cancel"),
    path("stripe/portal/", views.create_customer_portal_session, name="stripe_portal"),
    path("regulation/<int:pk>/", views.regulation_detail, name="regulation_detail"),
    path(
        "provision/<str:code_edition>/<str:division>/<str:provision_id>/v<int:version>/",
        views.provision_permalink,
        name="provision_permalink",
    ),
    # Division-less editions (e.g. OBC 1997) store division="" — a <str>
    # path segment can't be empty, so they get a sibling route that omits the
    # division segment entirely (no sentinel in the URL).
    path(
        "provision/<str:code_edition>/<str:provision_id>/v<int:version>/",
        views.provision_permalink,
        name="provision_permalink_no_division",
        kwargs={"division": ""},
    ),
    path("edition/<int:pk>/chain/", views.edition_chain, name="edition_chain"),
]
