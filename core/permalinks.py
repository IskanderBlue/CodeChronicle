"""Provision permalink URL resolution.

Shared by the regulation views and the lineage resolver
(``core.provision_lineage``) — it lives here, below the view layer, so the
resolver can build URLs without importing a view module (which would be
circular once the views call the resolver).
"""

from django.urls import reverse


def provision_permalink_url(
    code_name: str, division: str, provision_id: str, version: int
) -> str:
    """Reverse a provision permalink, routing around empty divisions.

    A ``<str:division>`` path segment can't be empty, so division-less
    editions (e.g. OBC 1997, ``division=""``) must use the sibling
    ``provision_permalink_no_division`` route or ``reverse`` raises
    ``NoReverseMatch``.
    """
    if division:
        return reverse(
            "core:provision_permalink",
            args=[code_name, division, provision_id, version],
        )
    return reverse(
        "core:provision_permalink_no_division",
        args=[code_name, provision_id, version],
    )
