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


def edition_contents_url(code_name: str) -> str:
    """The contents page of one edition, e.g. ``OBC_2006``.

    Named the same way a provision permalink names its edition, because the
    two are rungs of one ladder: a reader climbs out of a provision into this
    page and back down into another.
    """
    return reverse("core:edition_contents", args=[code_name])


def provision_print_url(
    code_name: str, division: str, provision_id: str, version: int
) -> str:
    """Reverse the printable form of a provision permalink.

    Same empty-division split as :func:`provision_permalink_url`, and here for
    the same reason: the rule about division-less editions is one rule, and a
    second copy of it is a second thing to get wrong.
    """
    if division:
        return reverse(
            "core:provision_print",
            args=[code_name, division, provision_id, version],
        )
    return reverse(
        "core:provision_print_no_division",
        args=[code_name, provision_id, version],
    )
