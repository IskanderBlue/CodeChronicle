"""Getting back to the settings page after a write.

The settings page is one page with several panels, and every write that
happens on it — issue a key, revoke a key, invite a member, leave a team —
answers with a redirect to the panel the reader was working in.  The panel is
a fragment on the same URL.

One home because the URL name is the part that rots.  Two modules each
building ``reverse("core:user_settings") + "#..."`` is two places to fix when
the route is renamed, and the one that is missed sends the reader to the top
of the page with no sign that anything went wrong.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

#: The panels a write can send a reader back to.  These are the ``id``
#: attributes in ``templates/settings.html``; a name not in this set lands at
#: the top of the page, which is why the callers pass one of these constants
#: rather than a literal.
API_KEYS_SECTION = "api"
TEAM_SECTION = "team"


def settings_redirect(section: str) -> HttpResponse:
    """Back to one panel of the settings page."""
    return redirect(f"{reverse('core:user_settings')}#{section}")
