"""
URL patterns for core app (frontend pages).
"""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # The front door is the landing page; ``redirect_signed_in`` sends an
    # authenticated reader straight on to the tool.  ``/about/`` is the same
    # page without that redirect, so the explanation stays linkable for
    # everybody (see core.views.landing).
    path("", views.landing, {"redirect_signed_in": True}, name="landing"),
    path("about/", views.landing, name="about"),
    path("search/", views.search_page, name="search"),
    path("pricing/", views.pricing, name="pricing"),
    path("terms/", views.terms_of_service, name="terms_of_service"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    path("sources/", views.data_sources, name="data_sources"),
    path("verification-rail/", views.verification_guide, name="verification_guide"),
    path("list-punctuation/", views.list_punctuation, name="list_punctuation"),
    path("history/", views.history, name="history"),
    # Staff-only traction dashboard.  Also disallowed in robots.txt.
    path("insights/", views.insights, name="insights"),
    path("settings/", views.user_settings, name="user_settings"),
    path("search-results/", views.search_results, name="search_results"),
    # Demand capture — which code/edition a visitor came looking for.
    path("edition-request/", views.edition_request, name="edition_request"),
    # Reader reports — "this looks wrong" on a specific text.
    path("report/", views.report_problem, name="report_problem"),
    path("report/<int:pk>/status/", views.feedback_status, name="feedback_status"),
    # Exports — the four ways to take something out of the product.  The
    # target is the same ``?v=OBC_2006/B/3.2.5.7./v0`` reference /compare/
    # takes, so a reader who copied a URL has already produced it.
    path("export/citation/", views.citation_panel, name="citation_panel"),
    path("export/results.csv", views.results_csv, name="results_csv"),
    path("export/record/", views.record_export, name="record_export"),
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
    # The exhibit: the same provision, laid out to print. A route rather than a
    # query parameter, because it is a different document and not a mode of the
    # reading page — and because a printed page's URL should say what it is.
    path(
        "provision/<str:code_edition>/<str:division>/<str:provision_id>/v<int:version>/print/",
        views.provision_permalink,
        name="provision_print",
        kwargs={"for_print": True},
    ),
    path(
        "provision/<str:code_edition>/<str:provision_id>/v<int:version>/print/",
        views.provision_permalink,
        name="provision_print_no_division",
        kwargs={"division": "", "for_print": True},
    ),
    path("edition/<int:pk>/chain/", views.edition_chain, name="edition_chain"),
    # Two version references in, one page out.  Query params rather than path
    # segments because the two references are of equal standing and neither
    # owns the URL — and because a reference itself contains slashes.
    path("compare/", views.compare_versions, name="compare"),
    path(
        "compare/print/",
        views.compare_versions,
        name="compare_print",
        kwargs={"for_print": True},
    ),
]
