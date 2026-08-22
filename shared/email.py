"""Cleaning an address a visitor typed into an optional field.

Sits beside :mod:`shared.ip` for the same reason: the anonymous submission
forms — the edition request and the reader report — each carry a required
field we want and one optional field we merely hope for, and both fields are
cleaned rather than validated.
"""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

#: Longest address stored.  The RFC's practical ceiling, and it matches the
#: model fields, so a truncation here never surprises the database.
MAX_EMAIL = 254


def clean_optional_email(raw: str) -> str:
    """Return a valid address, or the empty string.

    A malformed address is dropped rather than refused.  The other field is
    the one that matters — the need, or the note — and refusing the whole
    submission over a typo in the optional field would lose the part we
    actually wanted.
    """
    candidate = (raw or "").strip()[:MAX_EMAIL]
    if not candidate:
        return ""
    try:
        validate_email(candidate)
    except ValidationError:
        return ""
    return candidate
