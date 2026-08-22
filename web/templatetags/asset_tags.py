"""Template access to the mirrored-asset URLs.

One filter, so the four ``<img>`` sites cannot disagree about whether a scan
needs a token.  See :mod:`corpus.asset_signing` for why one of them does.
"""

from django import template

from corpus.asset_signing import asset_url

register = template.Library()


@register.filter(name="asset_url")
def asset_url_filter(asset_key: str) -> str:
    """Turn a CCM asset key into a root-relative URL, signed where required.

    Usage: ``<img src="{{ img_entry.image|asset_url }}">`` — note there is no
    leading slash in the template, because the filter supplies it.

    The Python name differs from the filter name on purpose.  The decorator
    already states what templates call this, so the module has no need of a
    second ``asset_url``, and one name for two things is how a caller ends up
    importing the wrapper when it wanted the rule.
    """
    return asset_url(asset_key)
