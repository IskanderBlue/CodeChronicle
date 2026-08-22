"""
URL patterns for the website (frontend pages).
"""

from django.urls import path

from web import views

# The namespace of every route below: ``web:search``, ``web:landing``.  It
# matches the package that serves them, so a reader who meets ``web:pricing``
# in a template looks in the right place for it.
app_name = "web"

urlpatterns = [
    # The front door is the landing page; ``redirect_signed_in`` sends an
    # authenticated reader straight on to the tool.  ``/about/`` is the same
    # page without that redirect, so the explanation stays linkable for
    # everybody (see web.views.landing).
    path("", views.landing, {"redirect_signed_in": True}, name="landing"),
    path("about/", views.landing, name="about"),
    path("search/", views.search_page, name="search"),
    path("pricing/", views.pricing, name="pricing"),
    path("terms/", views.terms_of_service, name="terms_of_service"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    # The re-acceptance wall.  Reached by redirect from
    # TermsReacceptanceMiddleware, not by a link, but it needs a name because
    # the middleware exempts it by name rather than by literal path.
    path("terms/accept/", views.accept_terms, name="accept_terms"),
    path("sources/", views.data_sources, name="data_sources"),
    path("verification-rail/", views.verification_guide, name="verification_guide"),
    path("list-punctuation/", views.list_punctuation, name="list_punctuation"),
    # Proof article: one question, seven texts. Public and indexed; the
    # historical texts render live from the corpus (web.views.guard_height).
    path("guard-height-ontario/", views.guard_height, name="guard_height"),
    path("history/", views.history, name="history"),
    # Staff-only traction dashboard.  Also disallowed in robots.txt.
    path("insights/", views.insights, name="insights"),
    path("settings/", views.user_settings, name="user_settings"),
    # Direct-API credentials.  Both write, both POST-only, and both answer by
    # sending the reader back to the settings page that lists the keys.
    path("settings/api-keys/", views.create_api_key, name="create_api_key"),
    path("settings/api-keys/<int:pk>/revoke/", views.revoke_api_key, name="revoke_api_key"),
    # Seats.  The three write routes are POST-only and answer by sending an
    # administrator back to the team section of the settings page, the same
    # shape the API-key routes above use.
    path("settings/team/<int:pk>/invite/", views.invite_to_team, name="invite_to_team"),
    path("settings/team/invite/<int:pk>/revoke/", views.revoke_invite, name="revoke_invite"),
    path("settings/team/member/<int:pk>/remove/", views.remove_from_team, name="remove_member"),
    # Where an invited person takes the seat.  A page rather than an action on
    # a GET: the reader sees what they are joining, and a mail scanner that
    # opens every link cannot spend the seat.
    path("team/join/<str:token>/", views.accept_invite_view, name="accept_invite"),
    path("search-results/", views.search_results, name="search_results"),
    # Demand capture — which code/edition a visitor came looking for.
    path("edition-request/", views.edition_request, name="edition_request"),
    # Reader reports — "this looks wrong" on a specific text.
    path("report/", views.report_problem, name="report_problem"),
    # The form itself, fetched when the dialog opens.  Kept off the page so a
    # provision response carries no CSRF cookie and stays cacheable.
    path("report/form/", views.report_form, name="report_form"),
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
    # One provision's body. The website's equivalent of ``/api/provision``: a
    # permalink page hands a signed-in reader the headings of what is under it
    # and fetches each body through here, so the reading ledger records one row
    # per text delivered instead of up to forty per page render.
    #
    # The permalink with ``/text/`` on the end, the same way the print route
    # below is the permalink with ``/print/``.
    path(
        "provision/<str:code_edition>/<str:division>/<str:provision_id>/v<int:version>/text/",
        views.provision_text,
        name="provision_text",
    ),
    path(
        "provision/<str:code_edition>/<str:provision_id>/v<int:version>/text/",
        views.provision_text,
        name="provision_text_no_division",
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
    # The edition's contents — the top of the navigation ladder. Keyed by the
    # same ``OBC_2006`` reference the provision permalinks use, not by a pk:
    # a reader who can read one URL can read the other. Declared after the
    # ``<int:pk>`` route above so a numeric first segment still reaches it.
    path(
        "edition/<str:code_edition>/",
        views.edition_contents,
        name="edition_contents",
    ),
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
