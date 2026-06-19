"""Canonical illustrative states for the verification-rail legend.

The attestation rail (``core.verification.rail_geometry`` →
``templates/partials/_attestation_rail.html``) packs a lot of meaning into a few
marks: a solid vs. dashed line, a ◆ diamond vs. a ▪ square, a hollow ◯ ring. New
users have no way to decode that, and the rail's whole job is to *earn trust* — an
undecodable trust signal is a weak one. This module is the data behind an
on-demand legend (``templates/partials/_rail_legend.html``): a symbol key plus one
worked example of each status configuration.

Like the dev preview (``.tmp/render_rail_preview.py``) and unlike a hand-drawn
mock, the examples are fed through the **real** ``rail_geometry`` and rendered by
the **real** partial, so the legend can never drift from the rail that ships. The
geometry is precomputed once at import against a fixed reference date — the
examples are static, so there is no per-request work and nothing depends on the
wall clock. The dates are illustrative; the consolidation labels carry no URL (an
illustrative date shouldn't link to a real consolidation it doesn't match).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from core.verification import ConsolidationRef, RailStatus, rail_geometry

# A fixed "today" so the open-tail examples are deterministic (the rail anchors an
# open window's right edge to this when it computes the query tick's position).
_REF = date(2026, 1, 1)


def _cons(
    frm: date,
    to: date,
    role: Literal["covering", "prior", "following"],
    *,
    kind: Literal["consolidation", "base"] = "consolidation",
    label: str = "consolidation",
    off_line: Literal["left", "right"] | None = None,
    clamp_left: bool = False,
    clamp_right: bool = False,
) -> ConsolidationRef:
    """An attestation point/interval for an example. ``url=""`` ⇒ a plain-text label."""
    return {
        "from": frm,
        "to": to,
        "url": "",
        "role": role,
        "kind": kind,
        "label": label,
        "off_line": off_line,
        "clamp_left": clamp_left,
        "clamp_right": clamp_right,
    }


def _status(
    rank: int | Literal["unconfirmed"],
    status_text: str,
    in_from: date,
    in_until: date | None,
    query: date,
    consolidations: list[ConsolidationRef],
    *,
    reconstructed: bool = False,
) -> RailStatus:
    """A hand-built ``RailStatus`` — the same shape ``derive_status`` returns."""
    return {
        "rank": rank,
        "status_text": status_text,
        "in_force": {"from": in_from, "until": in_until},
        "query_date": query,
        "consolidations": consolidations,
        "reconstructed_from": reconstructed,
    }


# One worked example per status configuration, strongest → weakest, then the
# enacting-regulation special case. ``note`` disambiguates only where the rank chip
# alone is ambiguous (the ▪ base example shares rank 4's chip). The status sentences
# are written generically — they explain the *configuration*, paired with a concrete
# (illustrative) graphic.
_EXAMPLES: list[tuple[str, RailStatus]] = [
    (
        "",
        _status(
            1,
            "Verified — the version in force on the query date was checked against a "
            "dated e-Laws consolidation whose published range covers that date.",
            date(2012, 1, 1),
            date(2014, 1, 1),
            date(2013, 3, 1),
            [_cons(date(2012, 6, 1), date(2013, 9, 1), "covering")],
        ),
    ),
    (
        "",
        _status(
            2,
            "Bracketed — consolidations before and after the query date carry identical "
            "text, so the version is unchanged across the gap, even though none lands "
            "exactly on the date.",
            date(2014, 1, 1),
            date(2020, 1, 1),
            date(2016, 6, 1),
            [
                _cons(date(2015, 1, 1), date(2015, 1, 1), "prior"),
                _cons(date(2018, 1, 1), date(2018, 1, 1), "following"),
            ],
        ),
    ),
    (
        "",
        _status(
            3,
            "Bracketed, with a reconstructed start — surrounding consolidations confirm "
            "the text, but the exact in-force start was inferred because none pins it (◯).",
            date(2015, 3, 1),
            date(2017, 1, 1),
            date(2016, 6, 1),
            [
                _cons(date(2015, 1, 1), date(2015, 1, 1), "prior", off_line="left"),
                _cons(date(2018, 1, 1), date(2018, 1, 1), "following", off_line="right"),
            ],
            reconstructed=True,
        ),
    ),
    (
        "",
        _status(
            4,
            "Open tail — confirmed through the latest consolidation and unchanged since, "
            "but no newer consolidation has yet attested the most recent stretch (dashed).",
            date(2012, 1, 1),
            None,
            date(2020, 1, 1),
            [_cons(date(2013, 1, 1), date(2014, 7, 1), "prior")],
        ),
    ),
    (
        "",
        _status(
            5,
            "Open tail, reconstructed — the text changed after the last consolidation; the "
            "new in-force start was inferred (◯), and no later consolidation has confirmed it.",
            date(2024, 5, 1),
            None,
            date(2025, 1, 1),
            [_cons(date(2022, 1, 1), date(2022, 1, 1), "prior", off_line="left")],
            reconstructed=True,
        ),
    ),
    (
        "",
        _status(
            "unconfirmed",
            "Not yet consolidated — this version was introduced after the most recent "
            "consolidation, so nothing independent has confirmed it yet.",
            date(2024, 5, 1),
            None,
            date(2024, 8, 1),
            [],
            reconstructed=True,
        ),
    ),
    (
        "Before e-Laws, the original O. Reg. is the attestation — a filled ▪ square "
        "instead of a ◆ consolidation.",
        _status(
            4,
            "Verified at enactment by the enacting regulation (▪), then unchanged — but with "
            "no consolidation since, the later stretch isn't independently attested.",
            date(2006, 6, 28),
            None,
            date(2009, 6, 1),
            [_cons(date(2006, 6, 28), date(2006, 6, 28), "prior", kind="base", label="O. Reg. 350/06")],
        ),
    ),
]

# Render-ready: each example as the ``result`` dict the band passes to the rail
# partial (no ``from_commencement``/``until_commencement`` keys ⇒ the partial's
# Derivation/End-date buttons stay hidden). Precomputed once at import.
LEGEND_RAILS: list[dict[str, Any]] = [
    {"note": note, "result": {"rail": rail_geometry(status, _REF)}}
    for note, status in _EXAMPLES
]


# The rail's visual vocabulary. ``cls`` selects a swatch drawn by ``.rail-legend .sw.*``
# in base.html, mirroring the live marks (the ◆/▪/◯ markers, the solid/dashed line).
SYMBOL_KEY: list[dict[str, str]] = [
    {
        "cls": "sw-solid",
        "name": "Solid line",
        "meaning": "Attested stretch — the text is directly backed by a consolidation here.",
    },
    {
        "cls": "sw-dash",
        "name": "Dashed line",
        "meaning": "Unattested stretch — inferred between consolidations, or a recent tail "
        "no consolidation has reached yet.",
    },
    {
        "cls": "sw-diamond",
        "name": "Consolidation",
        "meaning": "A dated e-Laws republication used to confirm the text. A pair of "
        "arrowheads ◄ ► marks one that spans a date range.",
    },
    {
        "cls": "sw-square",
        "name": "Enacting regulation",
        "meaning": "The original O. Reg. itself — the attestation when no consolidation applies.",
    },
    {
        "cls": "sw-ring",
        "name": "Reconstructed date",
        "meaning": "The in-force start was inferred; no consolidation pins exactly when this "
        "version began.",
    },
    {
        "cls": "sw-query",
        "name": "Query date",
        "meaning": "The date you searched, placed on the timeline.",
    },
    {
        "cls": "sw-divider",
        "name": "Margin rule",
        "meaning": "Holds a consolidation that falls entirely outside this version's in-force "
        "window.",
    },
]
