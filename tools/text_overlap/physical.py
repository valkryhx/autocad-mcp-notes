"""Physical collisions: plan objects that overlap each other, or a door's swing.

The text checks answer "can this label be read". They cannot answer "does this
rack stand in the doorway", which is a defect a reader sees at once and that no
text measurement will ever catch. Measured on a real plan (2026-11-19): a rack
row was laid out to x=11300 while the wall door's leaf swept x=11300..12500, so
the last rack stood in the opening. The text check DID fire - as ``text_curve``
on that rack's label, because the swing arc crossed the label - but it reported
a text problem where the real defect was the rack's position. Fixing the label
would have hidden it.

What it reports
---------------
``opening_blocked``
    A solid footprint lies inside a door's swept quarter disc. The disc is the
    space a person needs clear; a rack, desk or column in it means the door
    cannot open.

``solid_overlap``
    Two solid footprints intersect by at least 15% of the smaller one. Boxes
    are the WCS extent of each entity's drawn geometry, blocks expanded.

How a door is recognised
------------------------
From its layer: a layer whose name contains ``DOOR`` or ``KAPI``. That is the
signal ``arch_opening`` writes (``A-DOOR-E-N``) and what an architect reads. The
ARC on that layer gives hinge (its centre), leaf length (its radius) and sweep
(its start/end angles) in one entity, so a door whose leaf is a polyline still
resolves. A door drawn on some other layer is **not guessed at** - it is
reported as not checked, never as a made-up swing.

Deliberately silent
-------------------
* ``HATCH`` and ``SOLID``: a floor finish under a rack is not a clash.
* Annotation (``DIMENSION``, ``TABLE`` and their blocks).
* Members of one block reference: a rack's internal lines are its design, and
  two racks of the same definition are separate footprints, not one clash.
* A footprint under ``MIN_SOLID_AREA``: a tick mark or a jamb is not a solid.

Units are drawing units; every box is WCS, axis aligned.
"""

from __future__ import annotations

import math

from .overlap import Finding, _expand, _segments, Box

__all__ = ["physical_findings", "door_swings"]

#: A layer is a door layer when its name contains one of these.
DOOR_TOKENS = ("DOOR", "KAPI")

#: Entity types with a plan footprint (a filled area). Open runs of lines are
#: the wall engine's business, not a footprint.
FOOTPRINT_TYPES = frozenset({"LWPOLYLINE", "POLYLINE", "CIRCLE"})

#: Two boxes that merely share an edge are touching, not clashing. Measured on
#: a rack row: adjacent racks share their edge exactly, and reporting 47 clashes
#: for 48 racks is noise.
TOUCH_TOLERANCE = 0.01

#: Below this (drawing units^2) a box is a tick or a jamb. A rack is 600x1200.
MIN_SOLID_AREA = 10000.0

#: Overlap (as a fraction of the smaller box) below which two footprints are
#: adjacent rather than one-in-another.
MIN_OVERLAP_FRACTION = 0.15

#: How far a footprint is pulled in before the swing test. A rack that merely
#: ABUTS the swept quarter disc is not in the doorway: measured on the plan that
#: motivated this check, rack R4-B05 ends at x=11300 and the door's swing starts
#: at x=11300, so its corner sits exactly on the arc at distance == radius.
#: Reporting that would name a rack that is clear, and the drafter would move
#: the wrong one. The same "touching is not colliding" rule as `_overlap`.
SWING_MARGIN = 1.0


def _is_door_layer(name: str) -> bool:
    upper = (name or "").upper()
    return any(token in upper for token in DOOR_TOKENS)


def _angle_in(angle: float, start: float, end: float) -> bool:
    """Is `angle` on the CCW sweep start -> end (degrees, mod 360)?"""
    span = (end - start) % 360.0
    offset = (angle - start) % 360.0
    return offset <= span + 1e-9


class Swing:
    """One door: the quarter disc its leaf sweeps."""

    __slots__ = ("handle", "layer", "hinge", "radius", "start_deg", "end_deg")

    def __init__(self, handle, layer, hinge, radius, start_deg, end_deg):
        self.handle = handle
        self.layer = layer
        self.hinge = hinge
        self.radius = radius
        self.start_deg = start_deg
        self.end_deg = end_deg

    def blocks(self, box: Box) -> bool:
        """True when `box` reaches more than SWING_MARGIN into the swept disc.

        Two probes, because either alone misses a case:
        * the box's nearest point to the hinge - the only point that can be
          inside the disc when the box is entirely beyond it;
        * the box's four corners - catches a disc that cuts a side without
          reaching the nearest point (a swing over one end of a long rack row).
        The angular test keeps the other three quarters out, and
        ``SWING_MARGIN`` keeps a footprint that merely abuts the arc from being
        called a blockage.
        """
        hx, hy = self.hinge
        limit = self.radius - SWING_MARGIN
        if limit <= 0:
            return False
        x0, y0, x1, y1 = box
        probes = [
            (min(max(hx, x0), x1), min(max(hy, y0), y1)),
            (x0, y0), (x0, y1), (x1, y0), (x1, y1),
        ]
        for px, py in probes:
            dx, dy = px - hx, py - hy
            if math.hypot(dx, dy) > limit:
                continue
            if abs(dx) <= TOUCH_TOLERANCE and abs(dy) <= TOUCH_TOLERANCE:
                return True                       # the hinge is inside the box
            angle = math.degrees(math.atan2(dy, dx)) % 360.0
            if _angle_in(angle, self.start_deg, self.end_deg):
                return True
        return False


class Solid:
    """A plan object's footprint box.

    ``via`` is the enclosing INSERT's handle - what a caller must move. Every
    rack of one block definition has the SAME member handle inside the
    definition (measured: all 48 racks report handle ``110``), so reporting the
    member handle identifies nothing. The INSERT handle is the addressable one.
    """

    __slots__ = ("handle", "layer", "box", "via", "block")

    def __init__(self, handle, layer, box, via, block):
        self.handle = handle
        self.layer = layer
        self.box = box
        self.via = via
        self.block = block

    @property
    def address(self) -> str:
        """The handle a caller can act on: the INSERT when inside one."""
        return self.via or self.handle

    @property
    def area(self) -> float:
        return (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])


def door_swings(space, skipped: list[str]) -> list[Swing]:
    """Every door arc on a door layer, as hinge + radius + sweep."""
    swings: list[Swing] = []
    for entity in space:
        if entity.dxftype() != "ARC":
            continue
        layer = entity.dxf.layer
        if not _is_door_layer(layer):
            continue
        try:
            c = entity.dxf.center
            swings.append(
                Swing(
                    handle=str(entity.dxf.handle),
                    layer=layer,
                    hinge=(float(c.x), float(c.y)),
                    radius=float(entity.dxf.radius),
                    start_deg=float(entity.dxf.start_angle),
                    end_deg=float(entity.dxf.end_angle),
                )
            )
        except Exception:
            skipped.append(f"{entity.dxf.handle} (ARC on {layer}): unreadable swing")
    return swings


def _box_of(segments) -> Box | None:
    xs = [p[0] for seg in segments for p in seg]
    ys = [p[1] for seg in segments for p in seg]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _is_closed(entity) -> bool:
    """A polyline is a footprint only when closed; an open run is wall geometry."""
    kind = entity.dxftype()
    if kind == "CIRCLE":
        return True
    if kind == "LWPOLYLINE":
        return bool(entity.closed)
    if kind == "POLYLINE":
        return bool(entity.is_closed)
    return False


def _solids_of_space(space, skipped: list[str]) -> list[Solid]:
    solids: list[Solid] = []

    def add(entity, matrix, via, block_name):
        if entity.dxftype() not in FOOTPRINT_TYPES:
            return
        placed = entity
        if matrix is not None:
            placed = entity.copy()
            try:
                placed.transform(matrix)
            except Exception:
                return
        if not _is_closed(placed):
            return
        try:
            segments = _segments(placed)
        except Exception:
            return
        box = _box_of(segments) if segments else None
        if box is None:
            return
        solid = Solid(
            handle=str(entity.dxf.handle),
            layer=entity.dxf.layer,
            box=box,
            via=via,
            block=block_name,
        )
        if solid.area < MIN_SOLID_AREA:
            return
        solids.append(solid)

    for entity in space:
        kind = entity.dxftype()
        if kind in FOOTPRINT_TYPES:
            add(entity, None, None, None)
        elif kind == "INSERT":
            try:
                name = entity.dxf.name
            except Exception:
                name = None
            for member, matrix, via in _expand(entity, 1, skipped):
                add(member, matrix, via, name)
    return solids


def _overlap(
    a: Box, b: Box
) -> tuple[float, float] | None:
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    if ox > TOUCH_TOLERANCE and oy > TOUCH_TOLERANCE:
        return ox, oy
    return None


def physical_findings(space, skipped: list[str] | None = None) -> list[Finding]:
    """Door-swing blockages and solid-on-solid clashes."""
    skipped = skipped if skipped is not None else []
    findings: list[Finding] = []
    solids = _solids_of_space(space, skipped)
    swings = door_swings(space, skipped)

    # ── a solid standing in a doorway ──────────────────────────────────────
    for swing in swings:
        for solid in solids:
            if _is_door_layer(solid.layer):
                continue                       # the leaf itself is not "blocked"
            if not swing.blocks(solid.box):
                continue
            findings.append(
                Finding(
                    kind="opening_blocked",
                    handle=solid.address,
                    layer=solid.layer,
                    text="",
                    box=solid.box,
                    via=solid.via,
                    with_handle=swing.handle,
                    with_kind="ARC",
                    with_layer=swing.layer,
                    with_text="",
                    where=(
                        (solid.box[0] + solid.box[2]) / 2.0,
                        (solid.box[1] + solid.box[3]) / 2.0,
                    ),
                    note=(
                        f"block reference {solid.address}"
                        + (f" ({solid.block})" if solid.block else "")
                        + f" stands inside the swing of door {swing.handle} "
                        f"(hinge {swing.hinge[0]:.0f},{swing.hinge[1]:.0f}, "
                        f"leaf {swing.radius:.0f}); the doorway cannot open. "
                        f"Move {solid.address} clear of the swept quarter disc "
                        f"(x {swing.hinge[0] - swing.radius:.0f}..{swing.hinge[0]:.0f}, "
                        f"y {swing.hinge[1] - swing.radius:.0f}..{swing.hinge[1]:.0f})."
                    ),
                )
            )

    # ── two solids in the same place ───────────────────────────────────────
    for i, first in enumerate(solids):
        for second in solids[i + 1:]:
            if first.via is not None and first.via == second.via:
                continue                       # one block's own members
            hit = _overlap(first.box, second.box)
            if hit is None:
                continue
            ox, oy = hit
            smaller = min(first.area, second.area)
            if smaller <= 0:
                continue
            fraction = (ox * oy) / smaller
            if fraction < MIN_OVERLAP_FRACTION:
                continue
            findings.append(
                Finding(
                    kind="solid_overlap",
                    handle=first.address,
                    layer=first.layer,
                    text="",
                    box=first.box,
                    via=first.via,
                    with_handle=second.address,
                    with_kind=None,
                    with_layer=second.layer,
                    with_text="",
                    ratio=fraction,
                    where=(
                        (max(first.box[0], second.box[0]) + min(first.box[2], second.box[2])) / 2.0,
                        (max(first.box[1], second.box[1]) + min(first.box[3], second.box[3])) / 2.0,
                    ),
                    note=(
                        f"overlaps {second.address} ({second.layer}) by "
                        f"{fraction * 100:.0f}% of the smaller footprint"
                    ),
                )
            )
    return findings