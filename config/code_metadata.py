"""
Helpers for looking up code metadata stored in the database.
"""

#: The name a reader would use for each code system.
#:
#: This lives here rather than in the CCM payload because it is a presentation
#: choice and not a mapping result: CCM writes one file per edition, so a
#: code-system fact would repeat in every one of them and a wording change
#: would need a mapping run.  ``load_edition`` applies this map to the ``Code``
#: row, which keeps the value in version control instead of in whatever seeded
#: the row last — the state that left ``OBC`` unnamed while every code the
#: product does not serve kept its own name.
#:
#: Add a code here when its first edition loads.  A code that is absent falls
#: back to its own short form, which reads as trade shorthand but is never
#: wrong.
DISPLAY_NAMES = {
    "OBC": "Ontario Building Code",
    "NBC": "National Building Code",
    "NFC": "National Fire Code",
    "NPC": "National Plumbing Code",
    "ABC": "Alberta Building Code",
}


def get_code_display_name(system_code: str) -> str:
    """
    Get the display name for a code system (e.g., OBC -> Ontario Building Code).

    The database row answers first, because ``load_edition`` keeps it equal to
    ``DISPLAY_NAMES``.  The map answers for a code whose row is unnamed or
    absent — a code the loader has not reached, and any caller running without
    a database.
    """
    try:
        from core.models import Code
    except Exception:
        return DISPLAY_NAMES.get(system_code, system_code)

    system = Code.objects.filter(code=system_code).first()
    if system and system.display_name:
        return system.display_name
    return DISPLAY_NAMES.get(system_code, system_code)


def edition_display_name(code_name: str) -> str:
    """Turn a ``CodeEdition.code_name`` into prose: OBC_2012 -> OBC 2012's name.

    ``code_name`` is the internal join of system code and edition id; it should
    never reach a user (see the no-internal-identifiers rule), but several
    surfaces carry it as a dict key.  Unknown shapes pass through unchanged
    rather than raising — a teaser is not worth a 500.
    """
    system_code, _, edition_id = (code_name or "").partition("_")
    return f"{get_code_display_name(system_code)} {edition_id}".strip()
