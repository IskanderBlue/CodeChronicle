"""Template tags for the verification-rail legend.

Exposes the precomputed legend data (``core.rail_examples``) to templates so the
legend partial is drop-in — it pulls its own symbol key + worked examples and
needs no per-view context threading.
"""

from typing import Any

from django import template

from core.rail_examples import LEGEND_RAILS, SYMBOL_KEY

register = template.Library()


@register.simple_tag
def rail_legend() -> dict[str, Any]:
    """The legend's symbol key + one worked example per status configuration."""
    return {"symbols": SYMBOL_KEY, "rails": LEGEND_RAILS}
