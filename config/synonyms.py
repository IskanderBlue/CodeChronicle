"""
Building-code query synonyms used to expand a user's search terms.

Vendored verbatim (2026-07-28) from ``building_code_mcp.mcp_server.SYNONYMS``
in Canada_building_code_mcp (https://github.com/DavidCho1999/Canada_building_code_mcp),
MIT-licensed, © David Cho.

Copied rather than imported because ``building_code_mcp/__init__.py`` executes
its whole MCP server module on import — including ``@server.list_tools()``,
which raises ``AttributeError`` against current ``mcp`` releases. This table was
the only thing CodeChronicle still used from that package, so vendoring it drops
the dependency (and the import-time crash) altogether. It is a small, stable
hand-curated word list, not generated data — unlike ``config.keywords``, edit
this file directly.
"""

SYNONYMS: dict[str, list[str]] = {
    "restroom": ["washroom", "water closet", "toilet", "lavatory", "bathroom"],
    "washroom": ["restroom", "water closet", "toilet", "lavatory", "bathroom"],
    "stairs": ["stairway", "staircase", "stair"],
    "stairway": ["stairs", "staircase", "stair"],
    "exit": ["egress", "means of egress"],
    "egress": ["exit", "means of egress"],
    "fire": ["fire resistance", "fire separation", "fire-resistance"],
    "garage": ["parking garage", "parking structure", "carport"],
    "window": ["glazing", "fenestration"],
    "door": ["doorway", "entrance"],
    "wall": ["partition", "barrier"],
    "ceiling": ["soffit"],
    "floor": ["storey", "story"],
    "storey": ["floor", "story"],
    "handicap": ["accessible", "accessibility", "barrier-free"],
    "accessible": ["handicap", "accessibility", "barrier-free"],
    "ramp": ["slope", "incline"],
    "handrail": ["guardrail", "railing", "guard"],
    "guardrail": ["handrail", "railing", "guard"],
}
