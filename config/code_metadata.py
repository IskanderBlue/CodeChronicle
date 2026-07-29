"""
Helpers for looking up code metadata stored in the database.
"""


def get_code_display_name(system_code: str) -> str:
    """
    Get the display name for a code system (e.g., OBC -> Ontario Building Code).
    """
    try:
        from core.models import Code
    except Exception:
        return system_code

    system = Code.objects.filter(code=system_code).first()
    if system and system.display_name:
        return system.display_name
    return system_code


def edition_display_name(code_name: str) -> str:
    """Turn a ``CodeEdition.code_name`` into prose: OBC_2012 -> OBC 2012's name.

    ``code_name`` is the internal join of system code and edition id; it should
    never reach a user (see the no-internal-identifiers rule), but several
    surfaces carry it as a dict key.  Unknown shapes pass through unchanged
    rather than raising — a teaser is not worth a 500.
    """
    system_code, _, edition_id = (code_name or "").partition("_")
    return f"{get_code_display_name(system_code)} {edition_id}".strip()
