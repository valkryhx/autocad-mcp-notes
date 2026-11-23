"""Measure the continuous, square-cornered clear band around one cabinet row."""

from __future__ import annotations

import json
import math
from typing import NamedTuple

from ezdxf import DXFError, bbox
from .circulation import TOL, _read_plan
from .overlap import Finding

KIND = "rack_loop_clearance"


class Rect(NamedTuple):
    left: float
    bottom: float
    right: float
    top: float

    def grow(self, width):
        return Rect(
            self.left - width, self.bottom - width, self.right + width, self.top + width
        )

    def gap(self, other):
        # First contact as the four sides expand at the same rate (L-infinity).
        return max(
            0.0,
            self.left - other.right,
            other.left - self.right,
            self.bottom - other.top,
            other.bottom - self.top,
        )

    def contains(self, other):
        return (
            self.left <= other.left <= other.right <= self.right
            and self.bottom <= other.bottom <= other.top <= self.top
        )


def bounds(points):
    xs, ys = zip(*((p[0], p[1]) for p in points))
    return Rect(min(xs), min(ys), max(xs), max(ys))


def rectangle(points):
    points = list(points)
    box = bounds(points)
    ox, oy = points[0]
    perimeter = twice_area = 0.0
    for (x, y), (u, v) in zip(points, points[1:] + points[:1]):
        horizontal = (
            abs(y - v) <= TOL and min(abs(y - box.bottom), abs(y - box.top)) <= TOL
        )
        vertical = (
            abs(x - u) <= TOL and min(abs(x - box.left), abs(x - box.right)) <= TOL
        )
        if not (horizontal or vertical):
            raise ValueError("需要与 WCS 对齐的矩形外框")
        perimeter += math.hypot(u - x, v - y)
        twice_area += (x - ox) * (v - oy) - (u - ox) * (y - oy)
    w, h = box.right - box.left, box.top - box.bottom
    if (
        min(w, h) <= TOL
        or abs(perimeter - 2 * (w + h)) > TOL
        or abs(abs(twice_area) / 2 - w * h) > TOL * (w + h)
    ):
        raise ValueError("矩形外框不完整或存在回折")
    return box


def poly_box(poly):
    if (
        not poly.closed
        or poly.has_arc
        or poly.has_width
        or abs(poly.dxf.elevation) > TOL
        or tuple(poly.dxf.extrusion) != (0, 0, 1)
    ):
        raise ValueError("需要平面内闭合、零线宽的直边轮廓")
    return rectangle(poly.get_points("xy"))


def block_box(ref):
    if (
        ref.mcount != 1
        or abs(ref.dxf.insert.z) > TOL
        or tuple(ref.dxf.extrusion) != (0, 0, 1)
    ):
        raise ValueError("阵列或非平面块参照")
    skipped = []
    parts = list(
        ref.virtual_entities(skipped_entity_callback=lambda e, why: skipped.append(why))
    )
    outlines = [e for e in parts if e.dxftype() == "LWPOLYLINE" and e.closed]
    if skipped or len(outlines) != 1:
        raise ValueError("设备块需要唯一闭合占地轮廓")
    outer = poly_box(outlines[0])
    for part in parts:
        if part is outlines[0] or part.dxftype() in ("TEXT", "MTEXT", "ATTDEF"):
            continue
        if part.dxftype() not in ("LINE", "ARC", "CIRCLE", "LWPOLYLINE"):
            raise ValueError("含无法识别的设备块成员")
        ext = bbox.extents([part])
        if not ext.has_data or not outer.grow(TOL).contains(
            bounds([ext.extmin.xy, ext.extmax.xy])
        ):
            raise ValueError("设备成员超出占地轮廓")
    return outer


def row_envelope(boxes):
    for horizontal in (True, False):
        ordered = sorted(boxes, key=lambda r: r.left if horizontal else r.bottom)
        for a, b in zip(ordered, ordered[1:]):
            deviations = (
                (a.right - b.left, a.bottom - b.bottom, a.top - b.top)
                if horizontal
                else (a.top - b.bottom, a.left - b.left, a.right - b.right)
            )
            if max(map(abs, deviations)) > TOL:
                break
        else:
            return bounds(
                [p for r in boxes for p in ((r.left, r.bottom), (r.right, r.top))]
            )
    raise ValueError("柜体外框没有拼成同一直排，存在错位、间断或重叠")


def disk_gap(row, center, radius, limit, quadrant=None):
    """Find contact with a solid disk or an orthogonal door's filled quarter disk."""
    x, y = center.x, center.y

    def hits(width):
        left, bottom, right, top = row.grow(width)
        if quadrant is not None:
            if quadrant in (0, 3):
                left = max(left, x)
            else:
                right = min(right, x)
            if quadrant in (0, 1):
                bottom = max(bottom, y)
            else:
                top = min(top, y)
            if left > right or bottom > top:
                return False
        return (
            math.hypot(max(0.0, left - x, x - right), max(0.0, bottom - y, y - top))
            <= radius
        )

    if not hits(limit):
        return math.inf
    low, high = 0.0, limit
    for _ in range(54):
        mid = (low + high) / 2
        if hits(mid):
            high = mid
        else:
            low = mid
    return high


def collect_cabinets(space, group):
    boxes, selected = {}, {}
    for ref in space.query("INSERT"):
        handle = ref.dxf.handle
        try:
            boxes[handle] = block_box(ref)
        except ValueError as exc:
            raise ValueError(f"{handle}: {exc}") from exc
        ids = [a.dxf.text for a in ref.attribs if a.dxf.tag.upper() == "CAB_ID"]
        for tag in ids:
            prefix, sep, number = tag.rpartition("-")
            if sep and prefix == group:
                if (
                    not number.isascii()
                    or not number.isdecimal()
                    or len(ids) != 1
                    or tag in selected
                ):
                    raise ValueError(f"{handle}: 柜号 {tag} 不唯一或格式不明")
                selected[tag] = handle
    if not selected:
        raise ValueError(f"没有 CAB_ID 属于 {group} 排")
    return selected, boxes


def architecture(space, center):
    from engineering.arch.faces import face_containing
    from engineering.arch.model import Wall, Opening, from_payload

    carriers = [e for e in space if e.has_xdata("ACADMCP_ARCH")]
    faces, named, _, doors = _read_plan(space, carriers)
    face = face_containing(faces, center)
    if face not in named or face.holes:
        raise ValueError("柜排未绑定唯一可核实的无内岛房间")
    wall_layers, owned = set(), set()
    for e in carriers:
        obj = from_payload(
            json.loads("".join(t.value for t in e.get_xdata("ACADMCP_ARCH")))
        )
        if isinstance(obj, Wall):
            wall_layers.add(e.dxf.layer)
        if isinstance(obj, (Opening, Wall)) and e.has_xdata("ACADMCP_ARCH_H"):
            for tag in e.get_xdata("ACADMCP_ARCH_H"):
                member = space.doc.entitydb.get(tag.value)
                if isinstance(obj, Opening) or (
                    member is not None and member.dxftype() == "HATCH"
                ):
                    owned.add(tag.value)
    wall_lines = [e for e in space.query("LINE") if e.dxf.layer in wall_layers]
    owned.update(e.dxf.handle for e in wall_lines)
    return named[face].id, rectangle(face.loop), wall_lines, owned, doors


def wall_handles(lines, row, side, coord, gap):
    axis = 0 if side in ("west", "east") else 1
    found = []
    for e in lines:
        a, b = e.dxf.start, e.dxf.end
        if (
            max(abs(a[axis] - coord), abs(b[axis] - coord)) <= TOL
            and row.gap(bounds([a.xy, b.xy])) <= gap + TOL
        ):
            found.append(e.dxf.handle)
    return found


def obstacle_gaps(space, row, limit, owned, doors):
    for arc, _, _ in doors.values():
        start = arc.dxf.start_angle
        q = round(start / 90)
        if (
            abs(start - q * 90) > 1e-7
            or abs((arc.dxf.end_angle - start) % 360 - 90) > 1e-7
        ):
            raise ValueError(f"{arc.dxf.handle}: 门扇不是轴对齐的四分之一圆")
        gap = disk_gap(row, arc.dxf.center, arc.dxf.radius, limit, q % 4)
        yield gap, "door", [arc.dxf.handle], None
    window = row.grow(limit)
    annotation = {"TEXT", "MTEXT", "DIMENSION", "MULTILEADER", "LEADER", "ACAD_TABLE"}
    for e in space:
        h, kind = e.dxf.handle, e.dxftype()
        if h in owned or kind == "INSERT" or kind in annotation:
            continue
        if kind in ("LINE", "LWPOLYLINE") and e.dxf.layer.upper() == "IT-MAINT-LOOP":
            continue  # dedicated, nonphysical route overlay
        if kind == "LWPOLYLINE" and e.closed:
            try:
                gap = row.gap(poly_box(e))
            except ValueError as exc:
                raise ValueError(f"{h}: {exc}") from exc
        elif (
            kind == "CIRCLE"
            and tuple(e.dxf.extrusion) == (0, 0, 1)
            and abs(e.dxf.center.z) <= TOL
        ):
            gap = disk_gap(row, e.dxf.center, e.dxf.radius, limit)
        elif (
            kind == "LINE" and window.gap(bounds([e.dxf.start.xy, e.dxf.end.xy])) > TOL
        ):
            continue
        else:
            raise ValueError(f"{h} [{e.dxf.layer}] {kind}: 无法排除障碍，请复核其占地")
        yield gap, "equipment", [h], None


def measure(space, group, width):
    if not space.is_modelspace or space.doc.units != 4:
        raise ValueError("需要声明毫米的模型空间")
    selected, boxes = collect_cabinets(space, group)
    handles = set(selected.values())
    row = row_envelope([boxes[h] for h in handles])
    center = ((row.left + row.right) / 2, (row.bottom + row.top) / 2)
    room_id, room, walls, owned, doors = architecture(space, center)
    if not room.contains(row):
        raise ValueError("柜排跨越房间边界")
    sides = dict(
        west=row.left - room.left,
        east=room.right - row.right,
        south=row.bottom - room.bottom,
        north=room.top - row.top,
    )
    coords = dict(west=room.left, east=room.right, south=room.bottom, north=room.top)
    candidates = [
        (v, "wall", wall_handles(walls, row, side, coords[side], v), side)
        for side, v in sides.items()
    ]
    candidates.extend(
        (row.gap(b), "equipment", [h], None)
        for h, b in boxes.items()
        if h not in handles
    )
    candidates.extend(obstacle_gaps(space, row, min(sides.values()), owned, doors))
    clear = min(c[0] for c in candidates)
    tight = [c for c in candidates if abs(c[0] - clear) <= TOL]
    limiting = sorted({h for _, _, ids, _ in tight for h in ids})
    sides_hit = [s for _, _, _, s in tight if s]
    passed = clear + 1e-8 >= width
    result = dict(
        row=group,
        room_id=room_id,
        cabinet_count=len(selected),
        cabinets=selected,
        required_mm=width,
        clear_mm=round(clear, 8),
        wall_gaps_mm=sides,
        limiting_kind=tight[0][1],
        limiting_handles=limiting,
        limiting_walls=sides_hit,
        status="pass" if passed else "fail",
    )
    findings = []
    if not passed:
        ref = space.doc.entitydb[next(iter(selected.values()))]
        note = (
            f"{group} 排连续环道净宽 {clear:g} mm，要求 {width:g} mm。限制位置 "
            + ", ".join(sides_hit + limiting)
        )
        findings.append(
            Finding(
                KIND, ref.dxf.handle, ref.dxf.layer, group, row, where=center, note=note
            )
        )
    return findings, result


def rack_loop_check(space, group, width, expand_blocks):
    if (
        not isinstance(group, str)
        or not group.strip()
        or not isinstance(width, (float, int))
        or isinstance(width, bool)
        or not math.isfinite(width)
        or width <= 0
    ):
        raise ValueError(
            "--rack-loop 和 --min-rack-loop-mm 必须同时提供，净宽须为有限正数（毫米）"
        )
    try:
        if not expand_blocks:
            raise ValueError("需要展开机柜和设备块")
        return measure(space, group, width)
    except (
        DXFError,
        ValueError,
        TypeError,
        ImportError,
        KeyError,
        IndexError,
        ArithmeticError,
        AttributeError,
        StopIteration,
    ) as exc:
        return [], dict(
            row=group, required_mm=width, status="not_checked", reason=str(exc)
        )
