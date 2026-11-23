"""Single-storey room connectivity, door swing and local corridor sections.

Architectural records identify candidates. Actual wall faces, jambs and opening
members must match before a negative finding (especially 'no door') is safe.
The existing text/footprint checks do not depend on the architecture package.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
import json
import math

from ezdxf import DXFError
from ezdxf.math import Vec2, area
from ezdxf.math.clipping import ConvexClippingPolygon2d

KINDS = (
    "room_no_entrance",
    "room_unreachable",
    "door_swing_conflict",
    "corridor_clearance",
)
OUTSIDE = "@outside"
TOL = 0.001  # millimetres, floating-point noise only


def xy(p):
    return tuple(round(float(n), 5) for n in tuple(p)[:2])


def segment(a, b):
    return tuple(sorted((xy(a), xy(b))))


def arc_key(center, radius, start, end):
    return (
        "arc",
        xy(center),
        round(radius, 5),
        round(start % 360, 5) % 360,
        round(end % 360, 5) % 360,
    )


def geometry_key(e):
    if e.dxftype() == "LINE" and max(abs(e.dxf.start.z), abs(e.dxf.end.z)) < TOL:
        return ("line", segment(e.dxf.start, e.dxf.end))
    if (
        e.dxftype() == "ARC"
        and abs(e.dxf.center.z) < TOL
        and tuple(e.dxf.extrusion) == (0, 0, 1)
    ):
        return arc_key(e.dxf.center, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle)
    raise ValueError(f"{e.dxf.handle}: unsupported geometry or elevation")


def sector(arc):
    center = Vec2(arc.dxf.center)
    radius = arc.dxf.radius
    start = arc.dxf.start_angle
    span = (arc.dxf.end_angle - start) % 360
    # Inscribed polygon with chord sag <= 0.05 mm. Pure tangency has no area.
    step = math.degrees(2 * math.acos(max(-1.0, 1 - 0.05 / radius)))
    count = max(2, math.ceil(span / step))
    return [center] + [
        center + Vec2.from_deg_angle(start + span * i / count, radius)
        for i in range(count + 1)
    ]


def boundary_distance(face, origin, direction):
    hits = []
    for loop in (face.loop, *face.holes):
        for a, b in zip(loop, loop[1:] + loop[:1]):
            a = Vec2(a)
            edge = Vec2(b) - a
            det = direction.det(edge)
            if abs(det) < 1e-9:
                continue
            delta = a - origin
            t, u = delta.det(edge) / det, delta.det(direction) / det
            if t > TOL and -1e-9 <= u <= 1 + 1e-9:
                hits.append(t)
    if not hits:
        raise ValueError("ambiguous corridor cross section")
    return min(hits)


def _read_plan(space, carriers):
    from engineering.arch.model import from_payload, Wall, Opening, Room
    from engineering.arch.walls import wall_geometry_by_wall
    from engineering.arch.openings import opening_prims
    from engineering.arch.rooms import opening_closures
    from engineering.arch.faces import planar_faces, face_containing
    from engineering.mech.primitives import Line

    objects, anchors = {}, {}
    for e in carriers:
        obj = from_payload(
            json.loads("".join(t.value for t in e.get_xdata("ACADMCP_ARCH")))
        )
        if obj.id in objects:
            raise ValueError(f"duplicate architectural ID {obj.id}")
        objects[obj.id], anchors[obj.id] = obj, e
    walls = [v for v in objects.values() if isinstance(v, Wall)]
    rooms = [v for v in objects.values() if isinstance(v, Room)]
    openings = [v for v in objects.values() if isinstance(v, Opening)]
    if not walls or not rooms:
        raise ValueError("missing tagged walls or room labels")
    lookup = {w.id: w for w in walls}
    geometry = wall_geometry_by_wall(walls, openings, poche=False)
    if any(g.omitted for g in geometry.values()):
        raise ValueError("one or more openings cannot be cut in their host wall")
    wall_layers = {anchors[w.id].dxf.layer for w in walls}
    drawn = [e for e in space if e.dxf.layer in wall_layers]
    expected = Counter(
        ("line", segment(p.p1, p.p2))
        for g in geometry.values()
        for p in (*g.faces, *g.jambs)
    )
    if expected != Counter(geometry_key(e) for e in drawn):
        raise ValueError("wall faces/jambs differ from their records")
    segments = [(xy(e.dxf.start), xy(e.dxf.end)) for e in drawn]
    doors, verified = {}, set()
    for o in openings:
        handles = [str(t.value) for t in anchors[o.id].get_xdata("ACADMCP_ARCH_H")]
        entities = [space.doc.entitydb.get(h) for h in handles]
        if not entities or any(
            e is None or not e.is_alive or e.dxf.owner != anchors[o.id].dxf.owner
            for e in entities
        ):
            raise ValueError(f"{o.id}: missing opening members")
        want = []
        for s in opening_prims(lookup[o.wall], o):
            want.append(
                ("line", segment(s.p1, s.p2))
                if isinstance(s, Line)
                else arc_key(s.center, s.radius, s.start_deg, s.end_deg)
            )
        if Counter(want) != Counter(geometry_key(e) for e in entities):
            raise ValueError(f"{o.id}: opening geometry differs from its record")
        closures, omitted = opening_closures(walls, [o])
        if omitted or len(closures) != 2:
            raise ValueError(f"{o.id}: cannot locate both wall faces")
        segments.extend(closures)
        verified.update(handles)
        if o.kind == "door":
            arc = next(e for e in entities if e.dxftype() == "ARC")
            leaf = next(e for e in entities if e.dxftype() == "LINE")
            doors[o.id] = arc, leaf, closures
    if any(
        e.dxf.handle not in verified
        for e in space
        if ("DOOR" in e.dxf.layer.upper() or "KAPI" in e.dxf.layer.upper())
        and e.dxftype() in ("ARC", "INSERT", "LINE", "LWPOLYLINE")
    ):
        raise ValueError("unbound door symbol on a door layer")

    faces = planar_faces(segments)
    named = {}
    for r in rooms:
        e = anchors[r.id]
        pos = e.dxf.insert
        if e.dxftype() == "TEXT" and (e.dxf.halign or e.dxf.valign):
            pos = e.dxf.get("align_point", pos)
        face = face_containing(faces, xy(pos))
        if (
            face is None
            or face in named
            or r.id.startswith("@")
            or face_containing(faces, r.at) != face
        ):
            raise ValueError(f"{r.id}: ambiguous room binding")
        named[face] = r
    return faces, named, anchors, doors


def _audit(space, carriers, minimum, corridor_ids):
    from engineering.arch.faces import face_containing
    from .overlap import Finding

    faces, named, anchors, doors = _read_plan(space, carriers)
    ids = {
        face: named[face].id if face in named else f"@face-{i}"
        for i, face in enumerate(faces)
    }
    if set(corridor_ids) - {r.id for r in named.values()}:
        raise ValueError("unknown corridor room ID")
    corridors = set(corridor_ids) | {
        r.id
        for r in named.values()
        if any(
            word in r.name.casefold()
            for word in ("走廊", "通廊", "corridor", "hallway")
        )
    }
    graph = defaultdict(set)
    rows, parts, findings = [], [], []

    def issue(kind, e, text, pos, note, other=None):
        x, y = xy(pos)
        findings.append(
            Finding(
                kind,
                e.dxf.handle,
                e.dxf.layer,
                text,
                (x, y, x, y),
                where=(x, y),
                note=note,
                with_handle=other.dxf.handle if other is not None else None,
                with_kind=other.dxftype() if other is not None else None,
                with_layer=other.dxf.layer if other is not None else None,
            )
        )

    for key, (arc, leaf, closures) in doors.items():
        hinge = Vec2(arc.dxf.center)
        tip = max((Vec2(leaf.dxf.start), Vec2(leaf.dxf.end)), key=hinge.distance)
        normal = (tip - hinge).normalize()
        mids = [(Vec2(a) + Vec2(b)) * 0.5 for a, b in closures]
        back, front = sorted(mids, key=lambda p: p.dot(normal))
        f0 = face_containing(faces, back - normal * 0.1)
        f1 = face_containing(faces, front + normal * 0.1)
        src, dst = ids.get(f0, OUTSIDE), ids.get(f1, OUTSIDE)
        if src == dst:
            raise ValueError(f"{key}: opening does not separate two spaces")
        graph[src].add(dst)
        graph[dst].add(src)
        row = dict(
            id=key,
            handle=arc.dxf.handle,
            leaf=leaf.dxf.handle,
            connects=[src, dst],
            opens_into=dst,
            leaf_mm=arc.dxf.radius,
        )
        if dst in corridors or src in corridors:
            swings_in = dst in corridors
            cid, face = (dst, f1) if swings_in else (src, f0)
            direction = normal if swings_in else -normal
            origin = hinge if swings_in else hinge + (back - front)
            width = boundary_distance(face, origin, direction)
            tangent = direction.orthogonal()
            inside = origin + direction * 0.1
            longitudinal = sum(
                boundary_distance(face, inside, v) for v in (tangent, -tangent)
            )
            row.update(corridor_id=cid, opens_into_corridor=swings_in)
            if width >= longitudinal:
                row["section_status"] = (
                    "end wall or junction: review local passage direction"
                )
            else:
                remaining = max(
                    0.0, width - (hinge.distance(tip) if swings_in else 0.0)
                )
                row.update(section_mm=round(width, 3), remaining_mm=round(remaining, 3))
                if minimum is not None and remaining + TOL < minimum:
                    issue(
                        "corridor_clearance",
                        arc,
                        key,
                        hinge,
                        f"{key}, corridor {cid}: section {width:g} mm, one open leaf leaves {remaining:g} mm, project minimum {minimum:g} mm.",
                    )
        rows.append(row)
        parts.append((key, arc, dst, sector(arc)))
    for (key_a, a, side, pa), (key_b, b, other, pb) in combinations(parts, 2):
        if (
            side != other
            or Vec2(a.dxf.center).distance(Vec2(b.dxf.center))
            >= a.dxf.radius + b.dxf.radius
        ):
            continue
        clipped = ConvexClippingPolygon2d(pa).clip_polygon(pb)
        if any(len(poly) >= 3 and area(poly) > TOL**2 for poly in clipped):
            issue(
                "door_swing_conflict",
                a,
                "",
                a.dxf.center,
                f"{key_a} / {key_b} swing into {side}. Their swept areas overlap during simultaneous operation.",
                b,
            )
    visited = {OUTSIDE}
    todo = [OUTSIDE]
    while todo:
        for n in graph[todo.pop()] - visited:
            visited.add(n)
            todo.append(n)
    for r in named.values():
        if r.id not in visited:
            has_door = bool(graph[r.id])
            issue(
                "room_unreachable" if has_door else "room_no_entrance",
                anchors[r.id],
                r.name,
                r.at,
                f"{r.id}: "
                + (
                    "doors lead only to an isolated group of spaces."
                    if has_door
                    else "no verified doorway connects this space."
                ),
            )
    return findings, dict(
        status="checked",
        rooms=len(named),
        reachable=sum(r.id in visited for r in named.values()),
        doors=rows,
        corridors=sorted(corridors),
        minimum_mm=minimum,
    )


def circulation(space, minimum=None, corridors=(), required=False):
    if minimum is not None and (not math.isfinite(minimum) or minimum <= 0):
        raise ValueError("min_corridor_width_mm must be a finite positive number")
    carriers = [e for e in space if e.has_xdata("ACADMCP_ARCH")]
    if not carriers and not (
        required
        or minimum is not None
        or corridors
        or any(
            "WALL" in e.dxf.layer.upper() or "DOOR" in e.dxf.layer.upper()
            for e in space
        )
    ):
        return [], dict(status="not_applicable"), []
    try:
        if not space.is_modelspace or not carriers:
            raise ValueError("tagged model-space architecture required")
        if space.doc.units != 4:
            raise ValueError("declared millimetres required")
        findings, report = _audit(space, carriers, minimum, corridors)
    except (
        ImportError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        ArithmeticError,
        AttributeError,
        DXFError,
    ) as exc:
        reason = f"circulation: {exc}"
        return [], dict(status="not_checked", reason=reason), [reason]
    skipped = []
    if minimum is not None:
        if not report["corridors"] or not any(
            "remaining_mm" in door for door in report["doors"]
        ):
            skipped.append(
                "corridor width not_checked: no measurable door sections; select the corridor ID if needed"
            )
        for door in report["doors"]:
            if "section_status" in door:
                skipped.append(
                    f"{door['id']}: corridor width not_checked ({door['section_status']})"
                )
        if skipped:
            report["status"] = "partial"
    return findings, report, skipped
