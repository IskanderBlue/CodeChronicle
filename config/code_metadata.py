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
