"""Reader-facing names for a code system and for an edition.

The names themselves stay in :data:`data.code_metadata.DISPLAY_NAMES`.
These two helpers prefer the ``Code`` row, so they live here instead: nothing
in ``config`` imports Django, ``core`` or ``api``, and a lookup that reads a
model cannot keep that promise.  The function-body import that used to hide
the breach is what ``tests/test_module_conventions.py`` now refuses.
"""

from core.models import Code
from data.code_metadata import DISPLAY_NAMES


def get_code_display_name(system_code: str) -> str:
    """
    Get the display name for a code system (e.g., OBC -> Ontario Building Code).

    The database row answers first, because ``load_edition`` keeps it equal to
    ``DISPLAY_NAMES``.  The map answers for a code whose row is unnamed or
    absent — a code the loader has not reached.
    """
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
