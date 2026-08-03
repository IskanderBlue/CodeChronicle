"""
Views for core app (frontend pages).
"""

from .billing import (
    create_checkout_session,
    create_customer_portal_session,
    stripe_cancel,
    stripe_success,
)
from .compare import compare_versions
from .demand import edition_request
from .feedback import feedback_status, report_problem
from .history import history
from .insights import insights
from .landing import landing
from .pages import (
    data_sources,
    list_punctuation,
    pricing,
    privacy_policy,
    terms_of_service,
    user_settings,
    verification_guide,
)
from .regulation import edition_chain, provision_permalink, regulation_detail
from .search import (
    search_page,
    search_results,
    viewer_edition_dates,
    viewer_edition_nav,
    viewer_section_content,
)

__all__ = [
    "compare_versions",
    "create_checkout_session",
    "create_customer_portal_session",
    "data_sources",
    "edition_chain",
    "edition_request",
    "feedback_status",
    "history",
    "insights",
    "landing",
    "list_punctuation",
    "pricing",
    "privacy_policy",
    "provision_permalink",
    "regulation_detail",
    "report_problem",
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
