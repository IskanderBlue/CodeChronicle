"""Verification-coverage derivation — per ``(provision, query-date)`` confidence.

Given the version of a provision in force on a query date, how confident are we
that our reconstruction of its in-force text is *actually correct* for that date —
i.e. cross-checked against an independent, date-matched e-Laws consolidation?

This is the pure data layer behind the *attestation rail* (``## Presentation`` in
``tasks/verification-coverage.md``). It reads two things CC already has — the
edition's ``Consolidation`` rows (the attestation calendar) and the
provision's own version timeline (``effective_date``/``ineffective_date``) — and
returns a render *contract*: rank + supporting facts. It computes **no geometry**
(lane x, leader angles, %s, the label solver are the template's job from these
facts), so it can be unit-tested without a DOM.

The unifying idea (decisions 2 + 4 of the doc): a consolidation is an
**interval** ``[effective_from, effective_to]`` (a closed historical period, or a
zero-range point ``[d, d]`` for a periodic reprint / the live row). The version in
force at the *attesting* consolidation's date — ``ver_at(C)`` — decides everything:

* ``D`` inside a consolidation interval ⇒ **covered** (rank 1).
* otherwise the query sits between a *prior* and/or *following* consolidation, and
  ``reconstructed_from`` ⇔ ``ver_at(prior) is not V`` — the prior consolidation
  predates this version's commencement, so it cannot vouch for *when* the version
  began (the rank-3/5 reconstruction; the ``From`` ring in the rail). For a
  fully-covered e-Laws edition this is rare (e-Laws republishes on every
  commencement, so a version's ``From`` coincides with a consolidation start); it
  is primarily a periodic-PDF phenomenon.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal, NamedTuple, TypedDict

from core.models import CodeEditionProvisionVersion, Consolidation, Regulation

# ── The render contract (consumed by templates/partials/_attestation_rail.html) ──
# ``from``/``to``/``until`` are reserved words in Python, so the geometry keys use
# functional-syntax TypedDicts; the template reads them as dict lookups.
InForce = TypedDict("InForce", {"from": date, "until": "date | None"})
ConsolidationRef = TypedDict(
    "ConsolidationRef",
    {
        "from": date,
        "to": date,  # ``from == to`` ⇒ a zero-range point (reprint / live row / base reg)
        "url": str,
        "role": Literal["covering", "prior", "following"],
        # "consolidation" → open arrowheads / ◆ diamond; "base" → the base reg's
        # enactment, a filled ▪ square (a source, not an e-Laws snapshot).
        "kind": Literal["consolidation", "base"],
        "label": str,  # the marker's link text: "consolidation", or the reg citation
        # Wholly outside the in-force window ⇒ park in a fixed off-line gutter,
        # drawn as a single inward marker (prior → left, following → right).
        "off_line": "Literal['left', 'right'] | None",
        # An interval end that falls outside the in-force window ⇒ draw no head there.
        "clamp_left": bool,
        "clamp_right": bool,
    },
)

# What the assemblers pass in for the base regulation (built from the base
# ``Regulation`` row): its enactment date, citation, and source link. It is folded
# into the calendar as a zero-range attestation candidate — the "first
# consolidation" — competing for covering/prior/following like any other, and
# rendered only when selected (a later consolidation as prior simply wins).
BaseInput = TypedDict("BaseInput", {"date": date, "label": str, "url": str})


class RailStatus(TypedDict):
    rank: "int | Literal['unconfirmed']"
    status_text: str
    in_force: InForce
    query_date: date
    consolidations: list[ConsolidationRef]
    reconstructed_from: bool


class _Point(NamedTuple):
    """A normalized attestation point — an e-Laws consolidation or the base reg."""

    frm: date
    to: date
    url: str
    kind: Literal["consolidation", "base"]
    label: str  # link text: "consolidation", or the base reg's citation


def _name(p: _Point) -> str:
    """How an attestation is named in the status sentence."""
    if p.kind == "base":
        return f"{p.label} (the enacting regulation)"
    if p.frm == p.to:
        return f"the {p.frm.isoformat()} consolidation"
    return f"the {p.frm.isoformat()}–{p.to.isoformat()} consolidation"


def consolidations_for(edition_id: int) -> list[Consolidation]:
    """The edition's attestation calendar — e-Laws consolidations, earliest first.

    Pulled out so the search formatter can fetch it once per edition (the rows are
    identical for every result of an edition) and inject it, while single-rail
    callers let ``derive_status`` fetch lazily.
    """
    return list(
        Consolidation.objects.filter(edition_id=edition_id).order_by("effective_from")
    )


def base_input(reg: Regulation | None) -> "BaseInput | None":
    """The base regulation as a ``BaseInput`` — its enactment date, citation, link.

    Both assemblers fold the base reg into the rail; this keeps the ``O. Reg. NNN``
    citation shape and key mapping in one place. ``None`` when there's no base reg.
    """
    if reg is None:
        return None
    return {"date": reg.effective_date, "label": f"O. Reg. {reg.reg_id}", "url": reg.source_url}


def derive_status(
    version: CodeEditionProvisionVersion,
    query_date: date | None,
    base: "BaseInput | None" = None,
    consolidations: "list[Consolidation] | None" = None,
) -> RailStatus | None:
    """The verification status of ``version`` read on ``query_date``.

    ``base`` (optional) describes the edition's base regulation —
    ``{"date", "label", "url"}`` — which is folded in as a zero-range attestation
    point. It attests the *base version* with certainty (no amendment chain to have
    mis-captured) but, via the existence rule + same-version test, does nothing for
    amended versions; for an amendment-added provision it is dropped entirely
    (``ver_at(enactment) is None``).

    ``consolidations`` (optional) is the edition's pre-fetched attestation calendar;
    pass it to avoid a per-call query when formatting many results of one edition.
    Left ``None``, the rows are fetched lazily via ``consolidations_for``.

    Returns the render contract (see ``RailStatus``), or ``None`` when there is no
    real in-force period to attest — a ``never_in_force`` version or a missing
    query date (the rail, like the old consolidation line, is then suppressed).
    """
    if query_date is None or version.never_in_force:
        return None

    provision = version.provision
    siblings = list(provision.versions.all())

    # The version's own in-force window [F, U]. U is its ineffective date, else the
    # next version's commencement, else None ("current") — matching the band.
    in_from = version.effective_date
    in_until = version.ineffective_date
    if in_until is None:
        later = [v for v in siblings if v.effective_date > in_from]
        in_until = min((v.effective_date for v in later), default=None)

    def ver_at(day: date) -> CodeEditionProvisionVersion | None:
        return next((v for v in siblings if v.in_force_on(day)), None)

    def is_this_version(other: CodeEditionProvisionVersion | None) -> bool:
        # ``siblings`` are freshly fetched, so compare by pk, not identity.
        return other is not None and other.pk == version.pk

    # The attestation calendar: e-Laws consolidations + (optionally) the base
    # regulation's enactment, both as zero-range points. The base reg is the "first
    # consolidation" — it competes for covering/prior/following like any other.
    if consolidations is None:
        consolidations = consolidations_for(provision.edition_id)
    points = [
        _Point(c.effective_from, c.effective_to, c.url, "consolidation", "consolidation")
        for c in consolidations
    ]
    if base is not None:
        points.append(_Point(base["date"], base["date"], base["url"], "base", base["label"]))

    # Existence rule (decision 3): an attestation covers this provision only if some
    # version of it was in force at that instant — skips pre-existence consolidations
    # and drops the base point for amendment-added provisions, both for free.
    applicable = [p for p in points if ver_at(p.frm) is not None]

    covering = max(
        (p for p in applicable if p.frm <= query_date <= p.to),
        key=lambda p: p.frm, default=None,
    )
    prior = max(
        (p for p in applicable if p.to < query_date),
        key=lambda p: p.frm, default=None,
    )
    following = min(
        (p for p in applicable if p.frm > query_date),
        key=lambda p: p.frm, default=None,
    )

    def ref(p: _Point, role: Literal["covering", "prior", "following"]) -> ConsolidationRef:
        before = p.to < in_from
        after = in_until is not None and p.frm > in_until
        off_line: Literal["left", "right"] | None = (
            "left" if before else "right" if after else None
        )
        return {
            "from": p.frm,
            "to": p.to,
            "url": p.url,
            "role": role,
            "kind": p.kind,
            "label": p.label,
            "off_line": off_line,
            "clamp_left": p.frm < in_from,
            "clamp_right": in_until is not None and p.to > in_until,
        }

    refs: list[ConsolidationRef] = []
    rank: int | Literal["unconfirmed"]
    reconstructed_from: bool

    def add(p: _Point | None, role: Literal["covering", "prior", "following"]) -> None:
        if p is not None:
            refs.append(ref(p, role))

    if covering is not None:
        # Covered — the query date lies inside one attestation's interval (a closed
        # e-Laws period, or a zero-range point hit exactly: a reprint or the base reg).
        rank = 1
        reconstructed_from = not is_this_version(ver_at(covering.frm))
        add(covering, "covering")
        if covering.frm == covering.to:
            status_text = f"Verified against {_name(covering)}."
        else:
            status_text = (
                f"Verified against {_name(covering)}, whose range covers the query date."
            )
    elif prior is None:
        # No prior attestation — no backward extrapolation from a future one, so the
        # date is unconfirmed (a provision that predates every published attestation).
        rank = "unconfirmed"
        reconstructed_from = True
        add(following, "following")
        if following is not None:
            status_text = (
                f"Introduced on {in_from.isoformat()}; first attested by {_name(following)} "
                f"— the span before it is not independently confirmed."
            )
        else:
            status_text = (
                f"Introduced on {in_from.isoformat()} — no published consolidation has "
                f"covered it yet, so it is not yet confirmed."
            )
    elif following is not None:
        # Bracketed — the query date sits in a gap between two attestations.
        reconstructed_from = not is_this_version(ver_at(prior.frm))
        add(prior, "prior")
        add(following, "following")
        if reconstructed_from:
            rank = 3
            status_text = (
                f"Text matches {_name(prior)}; the {in_from.isoformat()} in-force date is "
                f"reconstructed. {_name(following).capitalize()} confirms no later change."
            )
        else:
            rank = 2
            status_text = (
                f"Unchanged between {_name(prior)} and {_name(following)} — bracketed "
                f"both sides; the span between is not directly attested."
            )
    else:
        # Open tail — a prior attestation but no following one; the tail rests on our
        # reconstruction (decision 4: the date is past the last attestation).
        reconstructed_from = not is_this_version(ver_at(prior.frm))
        add(prior, "prior")
        if reconstructed_from:
            rank = 5
            status_text = (
                f"Changed since {_name(prior)}; the {in_from.isoformat()} in-force date is "
                f"reconstructed and no later consolidation has confirmed it."
            )
        elif prior.kind == "base":
            rank = 4
            status_text = (
                f"Enacted by {prior.label}; "
                f"unchanged since, but no consolidation attests the tail."
            )
        else:
            rank = 4
            days = (query_date - prior.to).days
            status_text = (
                f"Verified through {prior.to.isoformat()}; unchanged since ({days} days), "
                f"but no later consolidation attests the tail."
            )

    return {
        "rank": rank,
        "status_text": status_text,
        "in_force": {"from": in_from, "until": in_until},
        "query_date": query_date,
        "consolidations": refs,
        "reconstructed_from": reconstructed_from,
    }


# ── Geometry (the attestation rail's layout) ─────────────────────────────────
# Deterministic % positions for the rail, ported from the settled v8 mock. This
# is the *presentation* layer: it turns the pure ``RailStatus`` (dates) into lane
# x / leader endpoints / line segments so the template renders static HTML+SVG
# with no client JS. The in-force window is drawn 18%→82%, leaving symmetric
# off-line gutters for consolidations that fall wholly outside it.
_W_FROM, _W_UNTIL = 18.0, 82.0
_GUTTER_LEFT, _GUTTER_RIGHT = 6.0, 94.0
_DIVIDER_LEFT, _DIVIDER_RIGHT = 12.0, 88.0
_LANE_QUERY = 50.0
# The inner consolidation lanes sit exactly halfway between the query lane and the
# nearest in-force edge — equidistant by construction (derived, not hand-tuned), so
# they track _W_FROM/_W_UNTIL/_LANE_QUERY rather than drifting query-ward as the
# eyeballed v8-mock constants (36/64) did.
_LANE_INNER_PRIOR = (_W_FROM + _LANE_QUERY) / 2  # 34.0
_LANE_INNER_FOLLOWING = (_LANE_QUERY + _W_UNTIL) / 2  # 66.0

# rank → (chip label, card class) — mirrors the mock's six cards.
_RANK_META: dict[Any, tuple[str, str]] = {
    1: ("Verified · covered", "r-cov"),
    2: ("Bracketed · unchanged", "r-brk"),
    3: ("Bracketed · date reconstructed", "r-rec"),
    4: ("Open tail · unchanged", "r-tail"),
    5: ("Open tail · date reconstructed", "r-rec"),
    "unconfirmed": ("Introduced · not yet consolidated", "r-new"),
}


def _interp(d: date, w_from: date, w_until: date) -> float:
    """Map a date into the in-force window's ``[18%, 82%]`` span (clamped)."""
    span = (w_until - w_from).days
    if span <= 0:
        return _W_FROM
    frac = max(0.0, min(1.0, (d - w_from).days / span))
    return round(_W_FROM + frac * (_W_UNTIL - _W_FROM), 2)


def _solid(a: float, b: float) -> dict[str, Any]:
    return {"cls": "line-solid", "left": round(a, 2), "width": round(b - a, 2)}


def _dash(a: float, b: float) -> dict[str, Any]:
    return {"cls": "line-dash", "left": round(a, 2), "width": round(b - a, 2)}


def rail_geometry(status: RailStatus, today: date) -> dict[str, Any]:
    """Render-ready % positions for the attestation rail, from a ``RailStatus``.

    ``today`` anchors the right edge of an open ("current") window so the query
    tick lands proportionally rather than pinned at the end. The returned dict is
    consumed verbatim by ``templates/partials/_attestation_rail.html``:

    * ``labels`` — fixed-lane date captions (``lane`` x, ``anchor`` x for the
      leader's foot, role/url/date/cls, and ``row`` = ``top`` for the in-force
      edges + query tick / ``bot`` for consolidations — the two-row stagger that
      keeps wide range captions from overlapping at narrow widths);
    * ``segments`` — the in-force line as solid (attested) / dashed (not) runs;
    * ``heads`` — the ◄/► arrowheads (a pair at one x ⇒ a ◆ diamond);
    * ``ring`` — the reconstructed-``From`` hollow ring (or ``None``);
    * ``qmark`` — the query-date tick; ``dividers`` — off-line gutter rules.
    """
    rank = status["rank"]
    in_from = status["in_force"]["from"]
    in_until = status["in_force"]["until"]
    query = status["query_date"]
    cons = status["consolidations"]
    reconstructed = status["reconstructed_from"]

    # The interpolation window. An open ("current") tail has no closing date, so
    # the right edge is the furthest of today / the query / any consolidation end.
    w_from = in_from
    if in_until is not None:
        w_until = in_until
    else:
        w_until = max([query, today, *(c["to"] for c in cons)])
    if w_until <= w_from:
        w_until = w_from + timedelta(days=1)

    def x(d: date) -> float:
        return _interp(d, w_from, w_until)

    labels: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    heads: list[dict[str, Any]] = []
    dividers: list[float] = []
    ring = _W_FROM if reconstructed else None

    # From / until / query — always present, in their fixed lanes.
    # The in-force edges and the query tick ride the TOP label row; consolidations
    # ride the BOTTOM row (see ``cons_label``). Splitting the rows is what keeps the
    # widest caption — a covering date *range* — from colliding with its neighbours
    # at narrow container widths: the two rows never share horizontal space.
    from_label = {
        "lane": _W_FROM,
        "anchor": _W_FROM,
        "role": "introduced" if rank == "unconfirmed" else "from",
        "url": None,
        "link_text": "",
        "date": in_from.isoformat(),
        "cls": "recon" if reconstructed else "",
        "leader": "",
        "row": "top",
    }
    labels.append(from_label)
    labels.append(
        {
            "lane": _W_UNTIL,
            "anchor": _W_UNTIL,
            "role": "until",
            "url": None,
            "link_text": "",
            "date": in_until.isoformat() if in_until is not None else "current",
            "cls": "" if in_until is not None else "end",
            "leader": "",
            "row": "top",
        }
    )
    qx = x(query)
    labels.append(
        {
            "lane": _LANE_QUERY,
            "anchor": qx,
            "role": "query date",
            "url": None,
            "link_text": "",
            "date": query.isoformat(),
            "cls": "q",
            "leader": "q",
            "row": "top",
        }
    )

    def cons_label(lane: float, anchor: float, ref: ConsolidationRef, dt: str) -> None:
        # The base reg keeps its "base" caption + citation link wherever it lands;
        # consolidations show their selection role + the word "consolidation".
        labels.append(
            {
                "lane": lane, "anchor": anchor,
                "role": "base" if ref["kind"] == "base" else ref["role"],
                "url": ref["url"], "link_text": ref["label"],
                "date": dt, "cls": "", "leader": "",
                "row": "bot",
            }
        )

    def in_window_marker(ref: ConsolidationRef) -> None:
        # ▪ square (base) · ◆ diamond (zero-range consolidation) · ◄══► heads
        # (positive-width period, each end dropped if it falls outside the window).
        if ref["kind"] == "base":
            heads.append({"cls": "cbase", "left": x(ref["from"])})
            return
        if not ref["clamp_left"]:
            heads.append({"cls": "cstart", "left": x(ref["from"])})
        if not ref["clamp_right"]:
            heads.append({"cls": "cend", "left": x(ref["to"])})

    covering = next((c for c in cons if c["role"] == "covering"), None)
    prior = next((c for c in cons if c["role"] == "prior"), None)
    following = next((c for c in cons if c["role"] == "following"), None)

    # The rank-4 e-Laws branch draws the prior's own marker inline; this flag tells
    # the generic prior block below not to draw it a second time.
    prior_drawn = False
    if covering is not None and covering["from"] != covering["to"]:
        # Covered by a positive-width period — solid over the covering interval
        # (clamped to the window), dashed on either side.
        s0 = x(max(covering["from"], w_from))
        s1 = x(min(covering["to"], w_until))
        if s0 > _W_FROM:
            segments.append(_dash(_W_FROM, s0))
        segments.append(_solid(s0, s1))
        if s1 < _W_UNTIL:
            segments.append(_dash(s1, _W_UNTIL))
        in_window_marker(covering)
        cons_label(
            _LANE_INNER_PRIOR, x(covering["from"]), covering,
            f'{covering["from"].isoformat()} → {covering["to"].isoformat()}',
        )
    elif covering is not None:
        # Covered by a zero-range point hit exactly (a reprint or the base reg) — a
        # ▪/◆ marker at that instant, the rest of the line dashed.
        segments.append(_dash(_W_FROM, _W_UNTIL))
        in_window_marker(covering)
        cons_label(_LANE_INNER_PRIOR, x(covering["from"]), covering, covering["from"].isoformat())
    elif rank == 4 and prior is not None and prior["kind"] == "consolidation":
        # Open tail · unchanged, e-Laws prior — solid from the in-force start through
        # the last consolidation's end, then dashed to "current".
        ptx = x(prior["to"])
        segments.append(_solid(_W_FROM, ptx))
        segments.append(_dash(ptx, _W_UNTIL))
        heads.append({"cls": "cstart", "left": _W_FROM})
        heads.append({"cls": "cend", "left": ptx})
        cons_label(_LANE_INNER_PRIOR, ptx, prior, f'through {prior["to"].isoformat()}')
        prior_drawn = True
    else:
        # Bracketed / reconstructed / new / base-prior open tail — the line is wholly
        # dashed (no continuous attestation); point markers sit on top, below.
        segments.append(_dash(_W_FROM, _W_UNTIL))

    # Prior marker, unless the rank-4 e-Laws branch already drew it. (When a covering
    # attestation fills the slot, derive_status leaves no prior, so this skips too.)
    if prior is not None and not prior_drawn:
        if prior["off_line"] == "left":
            dividers.append(_DIVIDER_LEFT)
            heads.append(
                {"cls": "cbase" if prior["kind"] == "base" else "cend", "left": _GUTTER_LEFT}
            )
            cons_label(_GUTTER_LEFT, _GUTTER_LEFT, prior, prior["from"].isoformat())
        else:
            in_window_marker(prior)
            cons_label(_LANE_INNER_PRIOR, x(prior["from"]), prior, prior["from"].isoformat())
    if following is not None:
        if following["off_line"] == "right":
            dividers.append(_DIVIDER_RIGHT)
            heads.append({"cls": "cstart", "left": _GUTTER_RIGHT})
            cons_label(_GUTTER_RIGHT, _GUTTER_RIGHT, following, following["from"].isoformat())
        else:
            in_window_marker(following)
            cons_label(_LANE_INNER_FOLLOWING, x(following["from"]), following, following["from"].isoformat())

    dividers = sorted(set(dividers))
    rank_label, rank_class = _RANK_META[rank]
    return {
        "rank": rank,
        "rank_label": rank_label,
        "rank_class": rank_class,
        "status_text": status["status_text"],
        "query_date": query.isoformat(),
        "labels": labels,
        "segments": segments,
        "heads": heads,
        "ring": ring,
        "qmark": qx,
        "dividers": dividers,
        # The fixed in-force-window edge ticks — the single source for 18%/82%, so
        # the template doesn't restate them as literals.
        "ifends": [_W_FROM, _W_UNTIL],
    }


def build_rail(
    version: CodeEditionProvisionVersion,
    query_date: date | None,
    today: date,
    base: "BaseInput | None" = None,
    consolidations: "list[Consolidation] | None" = None,
) -> dict[str, Any] | None:
    """Convenience for the assemblers: derive the status then its geometry.

    ``base`` is the edition's base regulation (``{"date", "label", "url"}``) — the
    enactment origin folded in as the first attestation. ``consolidations`` is the
    edition's pre-fetched calendar (see ``derive_status``). Returns the render-ready
    rail dict, or ``None`` when there is no rail to draw (``never_in_force`` / no
    query date).
    """
    status = derive_status(version, query_date, base=base, consolidations=consolidations)
    if status is None:
        return None
    return rail_geometry(status, today)
