"""Template access to the mirrored-asset URLs.

One filter, so the four ``<img>`` sites cannot disagree about whether a scan
needs a token.  See :mod:`core.asset_signing` for why one of them does.
"""

from django import template

from core.asset_signing import asset_url as _asset_url

register = template.Library()


@register.filter(name="asset_url")
def asset_url(asset_key: str) -> str:
    """Turn a CCM asset key into a root-relative URL, signed where required.

    Usage: ``<img src="{{ img_entry.image|asset_url }}">`` — note there is no
    leading slash in the template, because the filter supplies it.
    """
    return _asset_url(asset_key)
