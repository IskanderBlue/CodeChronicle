"""
Views for core app (frontend pages).
"""

from .billing import (
    create_checkout_session,
    create_customer_portal_session,
    stripe_cancel,
    stripe_success,
)
from .history import history
from .pages import pricing, privacy_policy, terms_of_service, user_settings
from .regulation import edition_chain, provision_permalink, regulation_detail
from .search import (
    home,
    search_results,
    viewer_edition_dates,
    viewer_edition_nav,
    viewer_section_content,
)

__all__ = [
    "create_checkout_session",
    "create_customer_portal_session",
    "edition_chain",
    "history",
    "home",
    "pricing",
    "privacy_policy",
    "provision_permalink",
    "regulation_detail",
    "search_results",
    "stripe_cancel",
    "stripe_success",
    "terms_of_service",
    "user_settings",
    "viewer_edition_dates",
    "viewer_edition_nav",
    "viewer_section_content",
]
