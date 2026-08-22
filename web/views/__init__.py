"""
Views for the website (frontend pages).
"""

from web.views.api_keys import create_api_key, revoke_api_key
from web.views.billing import (
    create_checkout_session,
    create_customer_portal_session,
    stripe_cancel,
    stripe_success,
)
from web.views.compare import compare_versions
from web.views.demand import edition_request
from web.views.exports import citation_panel, record_export, results_csv
from web.views.feedback import feedback_status, report_form, report_problem
from web.views.guard_height import guard_height
from web.views.history import history
from web.views.insights import insights
from web.views.landing import landing
from web.views.pages import (
    data_sources,
    list_punctuation,
    pricing,
    privacy_policy,
    terms_of_service,
    user_settings,
    verification_guide,
)
from web.views.reacceptance import accept_terms
from web.views.regulation import (
    edition_chain,
    edition_contents,
    provision_permalink,
    provision_text,
    regulation_detail,
)
from web.views.search import (
    search_page,
    search_results,
    viewer_edition_dates,
    viewer_edition_nav,
    viewer_section_content,
)
from web.views.teams import (
    accept_invite_view,
    invite_to_team,
    remove_from_team,
    revoke_invite,
)

__all__ = [
    "accept_invite_view",
    "accept_terms",
    "citation_panel",
    "compare_versions",
    "create_api_key",
    "create_checkout_session",
    "create_customer_portal_session",
    "data_sources",
    "edition_chain",
    "edition_contents",
    "edition_request",
    "feedback_status",
    "guard_height",
    "history",
    "insights",
    "invite_to_team",
    "landing",
    "list_punctuation",
    "pricing",
    "privacy_policy",
    "provision_permalink",
    "provision_text",
    "record_export",
    "regulation_detail",
    "remove_from_team",
    "report_form",
    "report_problem",
    "results_csv",
    "revoke_api_key",
    "revoke_invite",
    "search_page",
    "search_results",
    "stripe_cancel",
    "stripe_success",
    "terms_of_service",
    "user_settings",
    "verification_guide",
    "viewer_edition_dates",
    "viewer_edition_nav",
    "viewer_section_content",
]
