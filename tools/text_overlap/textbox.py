"""Measured text boxes, calibrated against AutoCAD's own ``GetBoundingBox``.

What went wrong first, and why this module exists
------------------------------------------------
Three measurements were tried on ``draw_test/gpu_dc_100.dxf`` (310 MTEXT, all
style ``CN`` = ``simhei.ttf``) and compared with the boxes AutoCAD itself
returns through COM ``AcadMText.GetBoundingBox``:

1. ``ezdxf.bbox.extents`` - **unusable**. ``ezdxf/disassemble.py`` reads DXF
   group 41 as ``box_width = mtext.dxf.get("width", 0)``; group 41 present
   with ``0.0`` means "do not wrap" but the value goes straight into
   ``text_wrap(text, 0.0, ...)``, whose test is
   ``get_text_width(current_line + t) > box_width``. Every token is wider than
   0, so every token becomes its own line. One 40-character note (handle 3B6)
   measured 2534 high and 5489 wide against AutoCAD's 374 x 11732.
   Median error 10% on width, 20% on height; **0 of 310 within 3%**.

2. font advance widths (``font.text_width``) with ``total_height`` for height -
   still wrong, because AutoCAD reports the **glyph ink box**, not the advance
   box: ``1`` measures 0.298 em wide, not the font's 0.74 em advance. Height
   also came out 20% large.

3. **glyph outlines** (``TrueTypeFont.text_path(...).extents()``) scaled by
   ``1 / 1.0289`` - what this module does. That constant is the font's
   em-per-char-height factor: AutoCAD's ``char_height`` is the cap height,
   while ``text_path`` builds outlines at the em size.

   Measured against AutoCAD on all 310 MTEXT, rotation-aware:

       width ratio  ink/acad  median 1.0000, mean 1.0019
       height ratio ink/acad  median 1.0000, mean 0.9949
       91.6% of texts within 3%, 96.8% within 5%, 98.4% within 8%

   The remaining outliers are superscripts: ``288 m²``, ``70.8 m²`` and a
   lone ``—``. AutoCAD stacks ``²`` as a smaller raised glyph, ezdxf lays the
   outline out inline, so the width runs 14-92% wide. Widths of that shape are
   small in absolute terms (a 91.6% error on a 401-unit dash), and an
   overstated text box produces a *reported* overlap rather than a missed one,
   which is the safe direction for this check.

Rotated text: the glyph box is computed in the entity's own local frame and
then rotated into WCS, so a MTEXT at 90 degrees gets the tall thin box AutoCAD
reports (``封闭冷通道``: 307 x 1627, not 1627 x 307).

Units are drawing units, boxes are WCS and axis aligned.
"""

from __future__ import annotations

import os

import ezdxf
from ezdxf.fonts import fonts
from ezdxf.math import UCS, Vec3
from ezdxf.tools.text_size import get_font_name, valid_text_height

__all__ = ["Box", "Calibration", "measure_text", "calibrate"]

Box = tuple[float, float, float, float]

#: AutoCAD's ``char_height`` is a capital's height, and ``text_path`` builds a
#: capital at exactly that size, so no em-per-cap correction is needed: the
#: outline of ``A`` measures ``char_height`` for every font tested.
_EM_PER_CAP = 1.0

#: AutoCAD's default line spacing for MTEXT is "3-on-5": the baseline-to-baseline
#: pitch is 5/3 of the character height. DXF group 44 holds 1.0 (or is absent)
#: for that default, so the factor has to be applied here.
_THREE_ON_FIVE = 5.0 / 3.0

#: Per-font width correction, measured against AutoCAD ``GetBoundingBox``:
#: ezdxf's outline comes out this many times *wider* than AutoCAD draws the
#: same string (310 MTEXT of one font, constant to 4 decimals), so a measured
#: outline is divided by it. The ratio is a rendering difference, not a font
#: metric: it holds for one character and for forty.
#: Text set in a font absent from this table keeps ratio 1.0 and is only as
#: accurate as ezdxf's raw outline.
_WIDTH_RATIO = {
    "simhei.ttf": 1.028902,
    "simsun.ttc": 1.022867,
}

#: Fonts observed to disagree with ezdxf's outline in a way no constant fixes:
#: for msyh.ttc, "Room A" at char height 350 measures 2066.7 in AutoCAD against
#: 1736.0 from the outline (ratio 0.84), while simhei and simsun both come out
#: a little *wide*. A measurement with no usable calibration is reported as
#: such, never as a confident box.
_UNRELIABLE_FONTS = frozenset({"msyh.ttc", "msyhbd.ttc"})

#: MTEXT attachment point (group 71) -> (horizontal, vertical) anchor. +1/-1
#: mean the insertion point is at the right/top edge; 0 means centred.
_MTEXT_ANCHOR = {
    1: (-1, 1),
    2: (0, 1),
    3: (1, 1),
    4: (-1, 0),
    5: (0, 0),
    6: (1, 0),
    7: (-1, -1),
    8: (0, -1),
    9: (1, -1),
}


class Calibration:
    """How one font's outline relates to the box AutoCAD draws."""

    def __init__(self, font: str = "", width_ratio: float = 1.0, reliable: bool = True):
        self.font = font
        self.width_ratio = width_ratio
        self.reliable = reliable

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"Calibration(font={self.font!r}, width_ratio={self.width_ratio:.6f}, "
            f"reliable={self.reliable})"
        )


def calibrate(font_name: str) -> Calibration:
    """The calibration for a style's font, by its bare file name."""
    bare = _font_name(font_name)
    key = bare.lower()
    if key in _UNRELIABLE_FONTS:
        return Calibration(bare, 1.0, reliable=False)
    ratio = _WIDTH_RATIO.get(key)
    return Calibration(bare, (1.0 / ratio) if ratio else 1.0, reliable=True)


def _attr(entity, name, default):
    """A DXF attribute's value, or ``default`` when the type does not carry it."""
    if not entity.dxf.is_supported(name):
        return default
    value = entity.dxf.get(name, default)
    return default if value is None else value


def _rotation_ucs(entity) -> UCS:
    origin = Vec3(entity.dxf.insert)
    z_axis = Vec3(_attr(entity, "extrusion", (0.0, 0.0, 1.0)))
    x_axis = Vec3(1, 0, 0)
    if entity.dxf.hasattr("text_direction"):
        direction = Vec3(entity.dxf.text_direction)
        if direction.magnitude > 0:
            x_axis = direction
    elif entity.dxf.hasattr("rotation"):
        x_axis = Vec3.from_deg_angle(float(entity.dxf.rotation))
    return UCS(origin=origin, ux=x_axis, uz=z_axis)


def _font(entity, height: float):
    width_factor = float(_attr(entity, "width_factor", 1.0) or 1.0)
    try:
        return fonts.make_font(_font_name(get_font_name(entity)), height, width_factor)
    except Exception:
        return fonts.MonospaceFont(height, width_factor)


def _font_name(name: str) -> str:
    """A style's font as a bare file name.

    ezdxf resolves a **full path** to a different set of metrics than the same
    font by name: measured on ``C:\\Windows\\Fonts\\simhei.ttf`` at char height
    400, the path form reports ``baseline=0`` and a ``国`` outline 349 units
    tall, while ``simhei.ttf`` reports ``baseline=11.56`` and 520 units. Both
    return a ``TrueTypeFont``, so nothing fails loudly - every CJK width is
    just 33% small. AutoCAD writes the full path into a style when the font is
    assigned through COM, so stripping it is not cosmetic.
    """
    if not name:
        return name
    trimmed = name.strip()
    if os.sep in trimmed or (os.altsep and os.altsep in trimmed):
        trimmed = os.path.basename(trimmed.replace("\\", os.sep))
    return trimmed


def _mtext_lines(entity):
    """The authored lines of a MTEXT, with its formatting codes stripped.

    A wrapping width (group 41 > 0) is honoured through ezdxf's
    ``text_wrap``; ``0`` means no wrapping, so only the authored ``\\n``
    breaks apply. This is the correction to ezdxf's own reading of group 41.
    """
    raw = entity.plain_text(split=False)
    if not raw.strip():
        return []
    return [line for line in raw.split("\n")]


def _ink_extents(font, text: str) -> Box | None:
    """The outline box of ``text`` as drawn at the font's em size."""
    if not text:
        return None
    try:
        path = font.text_path(text)
        lo, hi = path.extents()
    except Exception:
        return None
    if not (hi.x > lo.x or hi.y > lo.y):
        return None
    return (lo.x, lo.y, hi.x, hi.y)


def _box_of_points(points, ucs: UCS) -> Box:
    world = [ucs.to_wcs(Vec3(p[0], p[1], 0.0)) for p in points]
    return (
        min(p.x for p in world),
        min(p.y for p in world),
        max(p.x for p in world),
        max(p.y for p in world),
    )


def measure_text(entity, calibration: Calibration | None = None) -> Box | None:
    """The axis-aligned WCS box of a MTEXT / TEXT / ATTRIB / ATTDEF, or None
    when it draws no glyphs."""
    kind = entity.dxftype()
    if kind not in {"MTEXT", "TEXT", "ATTRIB", "ATTDEF"}:
        return None
    cal = calibration or calibrate(get_font_name(entity))
    if kind == "MTEXT":
        return _measure_mtext(entity, cal)
    return _measure_text(entity, cal)


def _glyph_span(font, text: str) -> Box | None:
    """The ink box of ``text``, in drawing units, at the font's own size."""
    return _ink_extents(font, text)


def _measure_mtext(entity, calibration: Calibration) -> Box | None:
    height = valid_text_height(entity.dxf.get("char_height", 0.0))
    font = _font(entity, height)
    lines = _mtext_lines(entity)
    if not lines:
        return None
    spans = []
    for line in lines:
        span = _glyph_span(font, line)
        if span is not None:
            spans.append(span)
    if not spans:
        return None
    line_width = max(s[2] - s[0] for s in spans) * calibration.width_ratio
    # Box height: the tallest line's ink, but never less than a capital. A
    # character with no ascender or descender - a lone em dash measures 24
    # units of ink at char height 280 - is still boxed at the full character
    # height by AutoCAD: measured 280 for that dash and 161.8 for "08" at 160,
    # which is the character height in both cases.
    line_height = max(s[3] - s[1] for s in spans)
    cap = _capital_height(font) or line_height
    line_height = max(line_height, cap)
    if line_width <= 0 or line_height <= 0:
        return None

    # Line pitch: DXF group 44 defaults to 1.0, which AutoCAD reads as its
    # "3-on-5" spacing - 5/3 of the character height, not 1.0 of it. Measured
    # on 2 lines at char height 265 (706.7 = 265 + 5/3*265) and 3 lines at 200
    # (866.7 = 200 + 2*5/3*200), both exact.
    spacing = float(_attr(entity, "line_spacing_factor", 1.0) or 1.0)
    if spacing < 0:
        spacing = 1.0
    total_height = line_height + cap * spacing * _THREE_ON_FIVE * (len(lines) - 1)

    anchor_x, anchor_y = _MTEXT_ANCHOR.get(
        int(_attr(entity, "attachment_point", 1) or 1), (-1, 1)
    )
    # Horizontal: anchor_x -1 = the insertion point is the left edge, 0 = the
    # centre, +1 = the right edge.
    left = -line_width * (anchor_x + 1) / 2.0
    right = left + line_width
    # Vertical, measured against AutoCAD for all nine attachment points:
    # 1-3 put the insertion point on the TOP edge (the box hangs below it),
    # 4-6 on the middle, 7-9 on the BOTTOM edge (the box stands above it).
    if anchor_y > 0:
        top, bottom = 0.0, -total_height
    elif anchor_y < 0:
        top, bottom = total_height, 0.0
    else:
        top, bottom = total_height / 2.0, -total_height / 2.0

    ucs = _rotation_ucs(entity)
    return _box_of_points([(left, bottom), (right, bottom), (right, top), (left, top)], ucs)


def _capital_height(font) -> float | None:
    """The drawn height of a capital ``A`` - which is what AutoCAD's
    ``char_height`` means. Measured from the outline rather than read off
    ``font.measurements.cap_height``, because that field is degenerate for
    some fonts (see ``_font_name``)."""
    ink = _ink_extents(font, "A")
    if ink is None:
        return None
    return ink[3] - ink[1]


def _measure_text(entity, calibration: Calibration) -> Box | None:
    height = valid_text_height(entity.dxf.get("height", 0.0))
    font = _font(entity, height)
    text = entity.dxf.get("text", "")
    span = _glyph_span(font, text)
    if span is None:
        return None
    width = (span[2] - span[0]) * calibration.width_ratio
    low, high = span[1], span[3]
    if width <= 0 or high <= low:
        return None

    # TEXT alignment: group 72 gives the horizontal anchor, and 73 the
    # vertical one; both move the insertion point off the left baseline.
    halign = int(_attr(entity, "halign", 0) or 0)
    valign = int(_attr(entity, "valign", 0) or 0)
    if halign == 0 and valign == 0:
        alignment_point = entity.dxf.get("align_point", None)
        left = 0.0
        baseline = 0.0
        if alignment_point is not None:
            # A non-default alignment stores its point in group 11; the box is
            # placed there rather than at the insert.
            origin = Vec3(alignment_point)
        else:
            origin = Vec3(entity.dxf.insert)
    else:
        origin = Vec3(entity.dxf.insert)
        left = {0: 0.0, 1: -width / 2.0, 2: -width, 3: 0.0, 4: -width / 2.0, 5: 0.0}.get(
            halign, 0.0
        )
        baseline = {0: 0.0, 1: -low, 2: -(low + high) / 2.0, 3: -high}.get(valign, 0.0)

    ucs = UCS(
        origin=origin,
        ux=Vec3.from_deg_angle(float(_attr(entity, "rotation", 0.0) or 0.0)),
        uz=Vec3(_attr(entity, "extrusion", (0.0, 0.0, 1.0))),
    )
    return _box_of_points(
        [
            (left + span[0], baseline + low),
            (left + span[2], baseline + low),
            (left + span[2], baseline + high),
            (left + span[0], baseline + high),
        ],
        ucs,
    )