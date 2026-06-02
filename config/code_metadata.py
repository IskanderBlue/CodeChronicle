"""
Helpers for looking up code metadata stored in the database.
"""
from datetime import date
from typing import List

from django.db import models


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


def get_applicable_codes(province: str, search_date: date) -> List[str]:
    """
    Find which code editions were in effect at a given date.

    Returns a list of code names (e.g., ['OBC_2012_v17', 'NBC_2015'])
    """
    codes: list[str] = []

    try:
        from core.models import Code, CodeEdition, ProvinceCode
    except Exception:
        return codes

    # Per CCM contract: in-force window is [effective_date, ineffective_date).
    # A null ineffective_date means the edition is still in force.
    in_force = models.Q(effective_date__lte=search_date) & (
        models.Q(ineffective_date__isnull=True)
        | models.Q(ineffective_date__gt=search_date)
    )

    province_map = (
        ProvinceCode.objects.select_related("code")
        .filter(province=province)
        .first()
    )
    if province_map:
        edition = (
            CodeEdition.objects.filter(code=province_map.code)
            .filter(in_force)
            .order_by("-effective_date")
            .first()
        )
        if edition:
            codes.append(edition.code_name)

    national_systems = Code.objects.filter(is_national=True)
    for system in national_systems:
        edition = (
            CodeEdition.objects.filter(code=system)
            .filter(in_force)
            .order_by("-effective_date")
            .first()
        )
        if edition:
            codes.append(edition.code_name)

    return codes
