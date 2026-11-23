"""Text-overlap detection on a DXF, as the prototype for an MCP tool.

What it reports
---------------
Two shapes of collision, each with a location, the handle and a text excerpt
for both sides, and the offending geometry:

* ``text_text``: two text entities whose drawn boxes intersect. The rule is
  the intersection's area against the *smaller* of the two boxes, so a long
  note running through a short axis label is reported rather than excused.
* ``text_curve``: a curve passing through the inset core of a text box. The
  outer band is ignored, because an underline, a box around a label or a
  leader touching a corner is not a collision - only a line that crosses the
  text does.

Deliberately silent
-------------------
* A DIMENSION's own geometry is skipped: its extension lines and arrows are
  placed against its text by design.
* A HATCH's boundary and fill are skipped for the same reason - a filled
  shape often contains a label on purpose.
* Two texts from the same *layer* whose boxes overlap only in the outer band
  (under 15% of the smaller box) are not reported: axis labels that sit on
  their axis line, and table cells whose padding is tight, land there.

Units are drawing units; every box is WCS, axis aligned.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

import ezdxf
from ezdxf.math import Matrix44, Vec3
from ezdxf.path import make_path
from ezdxf.tools.text_size import get_font_name

from .textbox import Box, calibrate, measure_text

__all__ = ["Finding", "detect", "TEXT_TYPES"]

#: Entity types measured as text.
TEXT_TYPES = frozenset({"MTEXT", "TEXT", "ATTRIB", "ATTDEF"})

#: Entity types flattened into curves and tested against text boxes.
CURVE_TYPES = frozenset(
    {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "SPLINE", "ELLIPSE"}
)

#: Types whose geometry is placed against text on purpose; never tested.
SKIPPED_TYPES = frozenset(
    {"DIMENSION", "HATCH", "SOLID", "TRACE", "POINT", "VIEWPORT", "INSERT", "TABLE", "LEADER"}
)

#: Chord deviation when flattening a curve, in drawing units.
FLATTEN = 0.5

#: Share of the smaller text box two texts must overlap by to be reported.
TEXT_TEXT_MIN_RATIO = 0.15

#: Fraction of a text box's width/height removed on each side before a curve
#: counts as crossing the text rather than grazing its edge.
CORE_INSET = 0.05

#: Curves shorter than this are ignored: a tick mark is not a collision.
MIN_SEGMENT = 1e-6

#: A table's cell text is drawn into an anonymous ``*T<n>`` block whose handle
#: is recorded on the ACAD_TABLE as ``block_record_handle``. Measured on
#: ``draw_test/123_check.dxf``: three tables, each an ``*T19``/``*T20``/``*T21``
#: block of MTEXT cells plus the rule LINEs. Two type names name a table
#: depending on the DXF version; both are read the same way.
TABLE_TYPES = frozenset({"ACAD_TABLE", "TABLE"})

#: How far a text's drawn height may sit from the drawing's typical height
#: before it is reported. Measured need: ``datacenter_plan_200558.dxf`` has
#: ``$DIMSCALE`` 1 with ``$DIMTXT`` 2.5, so its 13 dimension texts render 2.5
#: units tall while every other label in the same file is 125-175 - a 50x
#: mismatch that reads as "the dimensions have no text" on a plot.
TEXT_SCALE_TOLERANCE = 4.0

#: Below this many measurable texts a "typical height" is not meaningful.
TEXT_SCALE_MIN_SAMPLES = 5

#: Two texts count as duplicates when their content matches and their boxes sit
#: within this fraction of a text height of each other. Exact-zero matching
#: misses a copy-paste that landed one unit off; a whole text height would merge
#: two genuinely separate labels.
DUPLICATE_TOLERANCE = 0.25

#: ISO 3098 minimum lettering height for technical drawings, in millimetres.
#: The same constant `engineering/critique.py` uses, so this check and the
#: project's own critique agree on what "too small to read" means.
ISO_3098_MIN_TEXT_MM = 2.5

#: Millimetres per drawing unit per ``$INSUNITS`` value (DXF group 70 in the
#: header). Only the lengths that appear in CAD work are listed; 0 (unitless)
#: and anything unknown means the check cannot run and says so.
MM_PER_UNIT = {
    1: 25.4,      # inches
    2: 304.8,     # feet
    3: 1609344.0, # miles
    4: 1.0,       # millimetres
    5: 10.0,      # centimetres
    6: 1000.0,    # metres
    7: 1_000_000.0,  # kilometres
    8: 0.0000254,  # microinches
    9: 0.0254,     # mils
    10: 914.4,     # yards
    14: 100.0,     # decimetres
}


#: A MULTILEADER carries its text outside the normal entity fields: the string
#: lives in ``context.mtext.default_content`` and the height in
#: ``context.char_height`` (a style-unit value; multiply by ``context.scale``).
#: Neither ``virtual_entities()`` nor ``explode()`` returns the text - measured
#: on ezdxf 1.4.4, ``explode()`` yields only a HATCH and the leader POLYLINEs.
MLEADER_TYPES = frozenset({"MULTILEADER", "MLEADER"})

_PROBE_DOC = None


def _probe_doc():
    """A scratch document used to measure text that carries no drawable entity
    of its own (a MULTILEADER's content, for one). Never the input drawing."""
    global _PROBE_DOC
    if _PROBE_DOC is None:
        _PROBE_DOC = ezdxf.new("R2010")
    return _PROBE_DOC


@dataclass
class Finding:
    """One collision, with enough detail to fix it without a second query."""

    kind: str
    handle: str
    layer: str
    text: str
    box: Box
    #: DXF text style name. Reported because it is what a reader needs to fix a
    #: glyph problem: changing the style is how `m²`/`Ø`/CJK starts rendering,
    #: and the style is not visible from layer + text alone.
    style: str = ""
    with_style: str | None = None
    #: How many texts this one row stands for. Grouped checks (``text_scale``,
    #: ``text_illegible``, ``text_glyphless``, ``text_hidden``) collapse a whole
    #: class of texts into one row, so counting rows understates the damage -
    #: measured on ``gpu_dc_100.dxf``: 6 illegible rows are 129 texts.
    affected: int = 1
    with_handle: str | None = None
    with_kind: str | None = None
    with_layer: str | None = None
    with_text: str | None = None
    ratio: float | None = None
    where: tuple[float, float] | None = None
    note: str = ""
    #: The block reference the colliding text came from, when expanded.
    via: str | None = None
    #: A concrete way out, computed from the geometry: a shift that clears the
    #: collision, expressed as ``entity_move`` arguments on one of the two.
    fix: dict | None = None

    def as_dict(self) -> dict:
        out = {
            "kind": self.kind,
            "handle": self.handle,
            "layer": self.layer,
            "text": self.text,
            "box": [round(v, 3) for v in self.box],
        }
        if self.via is not None:
            out["in_block"] = self.via
        if self.style:
            out["style"] = self.style
        if self.with_handle is not None:
            out["with"] = {
                "handle": self.with_handle,
                "type": self.with_kind,
                "layer": self.with_layer,
                "text": self.with_text,
            }
            if self.with_style:
                out["with"]["style"] = self.with_style
        if self.ratio is not None:
            out["overlap_ratio"] = round(self.ratio, 4)
        if self.where is not None:
            out["at"] = [round(self.where[0], 3), round(self.where[1], 3)]
        if self.note:
            out["note"] = self.note
        if self.affected != 1:
            out["affected_texts"] = self.affected
        if self.fix:
            out["fix"] = self.fix
        return out


@dataclass
class _Text:
    entity: object
    box: Box
    text: str
    layer: str
    style: str
    reliable: bool
    #: "handle" for an entity of the checked space, else ``BLOCKNAME[handle]``
    #: for text expanded out of a block reference.
    origin: str = ""
    #: The block reference the text came from, when it was expanded.
    via: str | None = None
    #: The drawn height of the text **as set**, before rotation turns it
    #: sideways. Comparing a rotated label's axis-aligned box height against
    #: upright labels' would call every vertical label an outlier: measured on
    #: ``gpu_dc_100.dxf``, where two 90-degree "封闭冷通道" labels have a box
    #: 4.7x taller than the drawing's median.
    natural_height: float | None = None


def _dim_scale(dimension) -> float:
    """The factor AutoCAD multiplies a dimension's style sizes by when drawing.

    ``$DIMSCALE`` (or a per-dimension override on its style). The project's own
    ``engineering/arch/draw.py`` records why it matters: "Drawn at the style's
    DIMSCALE 1, a 1:50 chain's 2.5 text was 2.5 drawing units - 0.05 mm on the
    sheet, which is no text at all."
    """
    try:
        scale = dimension.doc.header.get("$DIMSCALE", 1.0)
        override = dimension.dxf.get("dimstyle", "")
        if override:
            style = dimension.doc.dimstyles.get(override)
            if style is not None and style.dxf.get("dimscale"):
                scale = style.dxf.get("dimscale")
        scale = float(scale or 1.0)
        return scale if scale > 0 else 1.0
    except Exception:
        return 1.0


def _dim_text_height(dimension, block_height: float) -> float:
    """The height AutoCAD draws a dimension's text at.

    Read off the style (``DIMTXT``) times ``DIMSCALE``, *not* off the ``*D``
    block's baked ``char_height``. Measured on ``draw_test/123_check.dxf``: the
    ``*D1`` block holds text at 2.5 units while the drawing's ordinary text runs
    120-250, and the block's own arrow is 2.53 units against ``DIMASZ`` 2.5 -
    i.e. the block stores style-unit decorations at drawing-unit positions, and
    AutoCAD re-renders them at ``DIMSCALE`` (50 here, giving 125 units of text,
    which matches the drawing's other labels).
    """
    try:
        style_name = dimension.dxf.get("dimstyle", "")
        doc = dimension.doc
        dimtxt = None
        if style_name:
            style = doc.dimstyles.get(style_name)
            if style is not None:
                dimtxt = style.dxf.get("dimtxt")
        if not dimtxt:
            dimtxt = doc.header.get("$DIMTXT")
        dimtxt = float(dimtxt or 0.0)
        if dimtxt > 0:
            return dimtxt * _dim_scale(dimension)
    except Exception:
        pass
    return block_height


def _dims_of_space(space, skipped: list[str]) -> tuple[list[_Text], dict]:
    """A DIMENSION's own text, as a box in drawing units.

    Built from two things that were each verified against AutoCAD:

    * **where** - the dimension's ``text_midpoint`` (group 11), which is in
      drawing units and matches the ``*D`` block's text insert exactly.
    * **how big** - ``DIMTXT * DIMSCALE``, because the block's baked
      ``char_height`` is a style-unit value (see ``_dim_text_height``).

    The block's text is measured for its *shape* (width relative to height) and
    the shape is then scaled to the drawn height and centred on the midpoint, so
    the box is right whether or not the block's own scale is.

    The returned dict maps a dimension's handle to the handles of its own
    geometry, so the curve check can skip them: a dimension's lines and arrows
    sit against its text by design.
    """
    texts: list[_Text] = []
    own_geometry: dict[str, set[str]] = {}
    for entity in space:
        if entity.dxftype() != "DIMENSION":
            continue
        try:
            block = entity.doc.blocks[entity.dxf.geometry]
        except Exception as exc:
            skipped.append(f"{entity.dxf.handle} (dimension): geometry block unreadable: {exc}")
            continue
        own_geometry[str(entity.dxf.handle)] = {str(m.dxf.handle) for m in block if m.dxf.handle}
        midpoint = entity.dxf.get("text_midpoint")
        members = [m for m in block if m.dxftype() in TEXT_TYPES]
        if not members:
            skipped.append(f"{entity.dxf.handle} (dimension): no text in its block")
            continue
        for member in members:
            try:
                calibration = calibrate(get_font_name(member))
                raw = measure_text(member, calibration)
            except Exception as exc:
                skipped.append(f"{entity.dxf.handle} (dimension text): {exc}")
                continue
            if raw is None:
                continue
            drawn_height = _dim_text_height(
                entity, float(member.dxf.get("char_height") or member.dxf.get("height") or 0.0)
            )
            box = _scale_box(raw, drawn_height, midpoint)
            texts.append(
                _Text(
                    entity=entity,
                    box=box,
                    text=_renderable(member),
                    layer=str(entity.dxf.get("layer", "0")),
                    style=_style_of(member),
                    reliable=calibration.reliable,
                    origin=str(entity.dxf.handle),
                    via=None,
                    natural_height=drawn_height,
                )
            )
    return texts, own_geometry


def _scale_box(box: Box, drawn_height: float, midpoint) -> Box:
    """Scale a measured box to ``drawn_height`` and centre it on ``midpoint``."""
    height = box[3] - box[1]
    width = box[2] - box[0]
    if height <= 0 or drawn_height <= 0:
        return box
    factor = drawn_height / height
    cx = (box[0] + box[2]) / 2.0
    cy = (box[1] + box[3]) / 2.0
    target_x = float(midpoint[0]) if midpoint is not None else cx
    target_y = float(midpoint[1]) if midpoint is not None else cy
    half_w = width * factor / 2.0
    half_h = drawn_height / 2.0
    return (target_x - half_w, target_y - half_h, target_x + half_w, target_y + half_h)


def _renderable(entity) -> str:
    kind = entity.dxftype()
    if kind == "MTEXT":
        return entity.plain_text().replace("\n", " | ").strip()
    return (entity.dxf.get("text", "") or "").strip()


def _style_of(entity) -> str:
    """The entity's text style, with DXF's default made explicit.

    A text entity that carries no ``style`` at all is drawn in ``Standard`` -
    that is what AutoCAD reads. Measured on ``draw_test/123.dxf``: 136 of its 142
    texts have the attribute absent, so reading it with a ``""`` default said
    "no style" for almost every label and hid the fact that they all land in
    ``Standard``.
    """
    name = entity.dxf.get("style", "") if entity.dxf.is_supported("style") else ""
    return str(name or "Standard")


#: How deep nested block references are followed. A depth cap keeps a
#: self-referencing block from recursing forever; anything cut off is reported
#: as not checked rather than silently dropped.
MAX_BLOCK_DEPTH = 8


def _transform_rotation(matrix) -> tuple[float, float]:
    """(rotation in degrees, uniform scale) of a block reference's transform.

    Read off the direction the matrix sends +X, so a rotated block's text is
    measured rotated. Returns scale 0 when the transform is not a similarity
    (non-uniform or mirrored): a text box under such a transform is a
    parallelogram, and this check's axis-aligned boxes cannot stand for it.
    """
    ux = matrix.transform_direction((1.0, 0.0, 0.0))
    uy = matrix.transform_direction((0.0, 1.0, 0.0))
    scale_x, scale_y = ux.magnitude, uy.magnitude
    if scale_x <= 0 or scale_y <= 0:
        return (0.0, 0.0)
    # A similarity keeps the axes perpendicular and equal in length.
    if abs(scale_x - scale_y) > 1e-6 * max(scale_x, scale_y):
        return (0.0, 0.0)
    if abs(ux.dot(uy)) > 1e-6 * scale_x * scale_y:
        return (0.0, 0.0)
    return (math.degrees(math.atan2(ux.y, ux.x)), scale_x)


def _table_block(table, blocked: list[str]):
    """The anonymous block holding a table's cell text, or None.

    An ACAD_TABLE draws nothing itself: its cells are MTEXT and its rules are
    LINEs, all inside a ``*T<n>`` block named by ``block_record_handle``.
    Skipping the table therefore skipped every cell - which is how three door,
    window and room schedules went unread in ``123_check.dxf``.
    """
    handle = table.dxf.get("block_record_handle")
    if not handle:
        blocked.append(f"{table.dxf.handle} (table): no block_record_handle, cells not read")
        return None
    try:
        for block in table.doc.blocks:
            if block.block_record_handle == handle:
                return block
    except Exception as exc:
        blocked.append(f"{table.dxf.handle} (table): cannot resolve its block: {exc}")
        return None
    blocked.append(f"{table.dxf.handle} (table): block {handle} not found, cells not read")
    return None


def _expand(insert, depth: int, blocked: list[str], _via: str | None = None):
    """Yield (entity, matrix, via_handle) for a block reference's contents,
    following nested references to ``MAX_BLOCK_DEPTH``.

    ``_via`` is the outermost reference's handle, threaded down the recursion.
    It is ``None`` only on the first call; every yielded text carries it, so a
    text three blocks deep still says which **top-level** reference to edit.

    Do not derive it from a nested ``INSERT``'s own handle: ``copy()`` does not
    carry a handle (the copy never enters the entitydb), so
    ``str(insert.dxf.handle)`` there is the string ``'None'``, which reads in a
    report as "inside block reference None". Measured on a two-level nesting.
    """
    via = _via if _via is not None else str(insert.dxf.handle)
    if depth > MAX_BLOCK_DEPTH:
        blocked.append(f"{insert.dxf.handle} (INSERT): nested deeper than {MAX_BLOCK_DEPTH}")
        return
    try:
        matrix = insert.matrix44()
        block = insert.doc.blocks[insert.dxf.name]
    except Exception as exc:
        blocked.append(f"{insert.dxf.handle} (INSERT): cannot expand: {exc}")
        return
    for member in block:
        kind = member.dxftype()
        if kind == "ATTDEF":
            continue
        if kind == "INSERT":
            nested = member.copy()
            nested.transform(matrix)
            # Keep the outermost reference's handle as `via`, not the nested
            # one's: the copy has no handle at all (see the docstring).
            yield from _expand(nested, depth + 1, blocked, _via=via)
        elif kind in TABLE_TYPES:
            nested_table = _table_block(member, blocked)
            if nested_table is not None:
                yield from _expand_table(nested_table, matrix, via, depth + 1, blocked)
        else:
            yield member, matrix, via


def _expand_table(block, matrix, via: str, depth: int, blocked: list[str]):
    """Yield a table block's members, placed by the containing transform.

    A table's block coordinates already land the cells in the right place
    relative to the table's insert point, so the reference matrix (usually
    translation only) is applied the same way it is for any block.
    """
    if depth > MAX_BLOCK_DEPTH:
        blocked.append(f"table block {block.name}: nested deeper than {MAX_BLOCK_DEPTH}")
        return
    for member in block:
        kind = member.dxftype()
        if kind in TABLE_TYPES:
            nested_table = _table_block(member, blocked)
            if nested_table is not None:
                yield from _expand_table(nested_table, matrix, via, depth + 1, blocked)
        elif kind == "INSERT":
            nested = member.copy()
            nested.transform(matrix)
            # Same reason as in `_expand`: the copy has no handle, so the `via`
            # must come from the container, not from this member.
            yield from _expand(nested, depth + 1, blocked, _via=via)
        else:
            yield member, matrix, via


def _attribs(entity) -> list:
    """An INSERT's ATTRIB entities - the variable text drawn by the block.

    ``virtual_entities()`` does not include them (measured on ezdxf 1.4.4), so
    a block with tagged text would otherwise lose exactly the part that varies
    between insertions. Their ``insert``/``rotation``/``height`` are already in
    WCS and already scaled, so they are measured directly, with no matrix.
    """
    try:
        return list(entity.attribs)
    except Exception:
        return []


def _table_matrix(table) -> Matrix44:
    """A table's own placement: its insert point and its horizontal direction.

    The cell geometry lives in the ``*T<n>`` block in block coordinates, so
    without this the cells of every table land on the origin - which reads as
    perfectly overlapping text.
    """
    insert = table.dxf.get("insert", (0.0, 0.0, 0.0))
    direction = table.dxf.get("horizontal_direction", (1.0, 0.0, 0.0))
    angle = math.atan2(float(direction[1]), float(direction[0])) if direction else 0.0
    rotation = Matrix44.z_rotate(angle - math.atan2(0.0, 1.0))
    return rotation @ Matrix44.translate(float(insert[0]), float(insert[1]), float(insert[2] or 0.0))


def _collect_texts(
    msp, expand_blocks: bool = True
) -> tuple[list[_Text], list[str], dict[str, set[str]]]:
    """Every visible text in the space, with the geometry that draws it.

    Returns ``(texts, not_checked_reasons, own_geometry)``. ``own_geometry``
    maps a dimension's handle to the handles of its own block members, so the
    curve check can leave a dimension's text alone with its own arrows and
    lines - those are placed against it on purpose.
    """
    texts: list[_Text] = []
    skipped: list[str] = []
    own_geometry: dict[str, set[str]] = {}
    for entity in msp:
        kind = entity.dxftype()
        if kind == "INSERT":
            if not expand_blocks:
                skipped.append(f"{entity.dxf.handle} (INSERT): block text not read")
                continue
            # The block's own geometry: fixed text and the tagged text's
            # ATTDEF is skipped, the live ATTRIBs are added below.
            for member, matrix, via in _expand(entity, 1, skipped):
                if member.dxftype() not in TEXT_TYPES:
                    continue
                texts.extend(_measure_in_block(member, matrix, via, skipped))
            for attrib in _attribs(entity):
                texts.extend(_measure_attrib(attrib, str(entity.dxf.handle), skipped))
            continue
        if kind in TABLE_TYPES:
            if not expand_blocks:
                skipped.append(f"{entity.dxf.handle} (table): cells not read")
                continue
            block = _table_block(entity, skipped)
            if block is None:
                continue
            matrix = _table_matrix(entity)
            for member, _inherit, via in _expand_table(
                block, matrix, str(entity.dxf.handle), 1, skipped
            ):
                if member.dxftype() not in TEXT_TYPES:
                    continue
                texts.extend(_measure_in_block(member, matrix, via, skipped))
            continue
        if kind == "DIMENSION":
            if not expand_blocks:
                skipped.append(f"{entity.dxf.handle} (dimension): text not read")
                continue
            dim_texts, own = _dims_of_space([entity], skipped)
            texts.extend(dim_texts)
            own_geometry.update(own)
            continue
        if kind in MLEADER_TYPES:
            texts.extend(_mleader_text(entity, skipped))
            continue
        if kind not in TEXT_TYPES:
            continue
        try:
            calibration = calibrate(get_font_name(entity))
            box = measure_text(entity, calibration)
        except Exception as exc:  # a proxy or malformed entity
            skipped.append(f"{entity.dxf.handle} ({kind}): {exc}")
            continue
        if box is None:
            continue
        texts.append(
            _Text(
                entity=entity,
                box=box,
                text=_renderable(entity),
                layer=str(entity.dxf.get("layer", "0")),
                style=_style_of(entity),
                reliable=calibration.reliable,
                origin=str(entity.dxf.handle),
                natural_height=_natural_height(entity, box),
            )
        )
    return texts, skipped, own_geometry


def _measure_attrib(attrib, via: str, skipped: list[str]) -> list[_Text]:
    """Measure one ATTRIB, which is already in WCS."""
    try:
        calibration = calibrate(get_font_name(attrib))
        box = measure_text(attrib, calibration)
    except Exception as exc:
        skipped.append(f"{attrib.dxf.handle or '?'} (attrib of {via}): {exc}")
        return []
    if box is None:
        return []
    tag = str(attrib.dxf.get("tag", ""))
    value = _renderable(attrib)
    label = f"{tag}={value}" if tag else value
    return [
        _Text(
            entity=attrib,
            box=box,
            text=label,
            layer=str(attrib.dxf.get("layer", "0")),
            style=_style_of(attrib),
            reliable=calibration.reliable,
            origin=f"{attrib.dxf.handle or '?'} in {via}",
            via=via,
            natural_height=_natural_height(attrib, box),
        )
    ]


def _measure_in_block(member, matrix, via: str, skipped: list[str]) -> list[_Text]:
    """Measure one block member's text in WCS, through the reference's matrix."""
    _rotation, scale = _transform_rotation(matrix)
    if scale <= 0:
        skipped.append(
            f"{member.dxf.handle or '?'} (block {via}): non-uniform or mirrored "
            "transform, text box not measured"
        )
        return []
    placed = member.copy()
    try:
        placed.transform(matrix)
    except Exception as exc:
        skipped.append(f"{member.dxf.handle or '?'} (block {via}): {exc}")
        return []
    # No manual rotation fix-up here. `transform()` already folds the reference's
    # rotation into the entity - MTEXT into ``text_direction``, TEXT into
    # ``rotation`` - on top of the rotation the member already had. Measured on
    # ezdxf 1.4.4: a MTEXT at 20 deg inside a block rotated 45 comes out with
    # ``text_direction`` at exactly 65 deg, and a TEXT the same way with
    # ``rotation`` = 65.
    #
    # An earlier version of this function read ``_transform_rotation`` and added
    # the block's angle again. For MTEXT that was harmless *only* because the
    # entity's ``rotation`` attribute is absent once ``text_direction`` is set,
    # so the "base" it added to was 0 - which is why the block tests passed. For
    # TEXT the base was the already-correct 65, and the box came out at 110 deg.
    try:
        calibration = calibrate(get_font_name(placed))
        box = measure_text(placed, calibration)
    except Exception as exc:
        skipped.append(f"{member.dxf.handle or '?'} (block {via}): {exc}")
        return []
    if box is None:
        return []
    return [
        _Text(
            entity=member,
            box=box,
            text=_renderable(member),
            layer=str(member.dxf.get("layer", "0")),
            style=_style_of(member),
            reliable=calibration.reliable,
            origin=f"{(member.dxf.handle or '?')} in {via}",
            via=via,
            natural_height=_natural_height(placed, box),
        )
    ]


def _segments(entity) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    try:
        path = make_path(entity)
    except Exception:
        return []
    if path is None:
        return []
    try:
        points = [(v.x, v.y) for v in path.flattening(FLATTEN)]
    except Exception:
        return []
    return [
        (points[i], points[i + 1])
        for i in range(len(points) - 1)
        if abs(points[i][0] - points[i + 1][0]) > MIN_SEGMENT
        or abs(points[i][1] - points[i + 1][1]) > MIN_SEGMENT
    ]


def _clip(segment, box: Box):
    """Liang-Barsky: the parameter range in which the segment is inside ``box``."""
    (xa, ya), (xb, yb) = segment
    dx, dy = xb - xa, yb - ya
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, xa - box[0]),
        (dx, box[2] - xa),
        (-dy, ya - box[1]),
        (dy, box[3] - ya),
    ):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return None
    return (t0, t1)


def _inset(box: Box, fraction: float) -> Box:
    w, h = box[2] - box[0], box[3] - box[1]
    dx, dy = w * fraction, h * fraction
    return (box[0] + dx, box[1] + dy, box[2] - dx, box[3] - dy)


def _intersection(a: Box, b: Box) -> tuple[float, float, float, float] | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _mleader_text(entity, skipped: list[str]) -> list[_Text]:
    """A MULTILEADER's text box.

    The entity's own fields do not hold the text: ``explode()`` drops it and
    ``virtual_entities()`` does not produce it (measured on ezdxf 1.4.4 - the
    explode yields a HATCH and the leader POLYLINEs only). It lives in
    ``context.mtext``:

    * ``default_content`` is the string,
    * ``insert`` is the text's anchor point, in drawing units,
    * ``context.char_height * context.scale`` is the drawn height.

    Measured against AutoCAD on a leader built through COM: ``TextHeight`` 10
    came back as ``context.char_height`` 10 with ``scale`` 1.0, and the DXF's
    ``insert`` matched the leader's landing point.

    ``GetBoundingBox`` cannot confirm it - it returns the leader's *geometry*
    box and ignores the text entirely (three leaders at text heights 0.18, 1.0
    and 10 all measured 817 x 805).
    """
    try:
        context = entity.context
        data = context.mtext
    except Exception as exc:
        skipped.append(f"{entity.dxf.handle} (mleader): no text context: {exc}")
        return []
    content = (getattr(data, "default_content", "") or "").strip()
    if not content:
        return []
    height = float(getattr(context, "char_height", 0.0) or 0.0) * float(
        getattr(context, "scale", 1.0) or 1.0
    )
    if height <= 0:
        skipped.append(f"{entity.dxf.handle} (mleader): text height reads 0")
        return []
    insert = getattr(data, "insert", None)
    if insert is None:
        skipped.append(f"{entity.dxf.handle} (mleader): text has no insert point")
        return []
    rotation = math.degrees(float(getattr(data, "rotation", 0.0) or 0.0))
    width = float(getattr(data, "width", 0.0) or 0.0)

    # Measure on a throwaway MTEXT in a scratch document, so the box comes from
    # the same font-outline code path as every other text and the input drawing
    # is never modified.
    probe = _probe_doc()
    mtext = probe.modelspace().add_mtext(
        content,
        dxfattribs={
            "char_height": height,
            "insert": (float(insert[0]), float(insert[1]), 0.0),
            "rotation": rotation,
            "style": "Standard",
        },
    )
    if width > 0:
        mtext.dxf.width = width
    try:
        calibration = calibrate(get_font_name(mtext))
        box = measure_text(mtext, calibration)
    except Exception as exc:
        skipped.append(f"{entity.dxf.handle} (mleader text): {exc}")
        return []
    if box is None:
        return []
    return [
        _Text(
            entity=entity,
            box=box,
            text=content.replace("\n", " | "),
            layer=str(entity.dxf.get("layer", "0")),
            style="",
            reliable=calibration.reliable,
            origin=str(entity.dxf.handle),
            natural_height=height,
        )
    ]


def _natural_height(entity, box: Box) -> float | None:
    """A text's height as set, with its rotation taken back out.

    Axis-aligned box height is not comparable across rotations: a 90-degree
    label's box is as tall as the text is long. The style's ``DIMTXT`` (or the
    entity's ``char_height``/``height``) is rotation-free, so that is what the
    scale check compares.
    """
    kind = entity.dxftype()
    try:
        if kind == "MTEXT":
            value = float(entity.dxf.get("char_height") or 0.0)
        elif kind in {"TEXT", "ATTRIB", "ATTDEF"}:
            value = float(entity.dxf.get("height") or 0.0)
        else:
            value = 0.0
    except Exception:
        value = 0.0
    if value > 0:
        return value
    return box[3] - box[1] if box[3] > box[1] else None


def _scale_findings(texts: list[_Text]) -> list[Finding]:
    """Text drawn at a height far from the drawing's own habit.

    A drawing has a house text size; a label five times smaller than every other
    label is a drafting defect even when nothing overlaps it. Measured case:
    ``datacenter_plan_200558.dxf`` renders its 13 dimension texts at 2.5 units
    against 125-175 for everything else, because ``$DIMSCALE`` is 1 while
    ``$DIMTXT`` is 2.5.

    Reported as ``text_scale``, one finding per group of same-height texts, so
    13 dimension texts make one row, not thirteen.
    """
    heights = [t.natural_height for t in texts if t.natural_height and t.natural_height > 0]
    if len(heights) < TEXT_SCALE_MIN_SAMPLES:
        return []
    typical = statistics.median(heights)
    if typical <= 0:
        return []
    findings: list[Finding] = []
    outliers: dict[tuple[int, str], list[_Text]] = {}
    for text in texts:
        height = text.natural_height
        if not height or height <= 0:
            continue
        ratio = height / typical
        if 1.0 / TEXT_SCALE_TOLERANCE <= ratio <= TEXT_SCALE_TOLERANCE:
            continue
        # Group by rounded height and source, so one cause is one row.
        key = (round(height), text.entity.dxftype())
        outliers.setdefault(key, []).append(text)
    for (height, kind), group in sorted(outliers.items()):
        first = group[0]
        ratio = height / typical
        findings.append(
            Finding(
                kind="text_scale",
                handle=first.origin,
                layer=first.layer,
                style=first.style,
                affected=len(group),
                text=first.text,
                box=first.box,
                with_kind=kind,
                ratio=ratio,
                where=(
                    (first.box[0] + first.box[2]) / 2,
                    (first.box[1] + first.box[3]) / 2,
                ),
                note=(
                    f"{len(group)} {kind} text(s) drawn {height:.1f} units tall "
                    f"against a drawing median of {typical:.1f} "
                    f"({ratio:.2f}x)"
                ),
            )
        )
    return findings


def _text_text(texts: list[_Text]) -> list[Finding]:
    findings: list[Finding] = []
    ordered = sorted(texts, key=lambda t: t.box[0])
    for i, first in enumerate(ordered):
        # Only compare against boxes that can still reach this one.
        for second in ordered[i + 1 :]:
            if second.box[0] >= first.box[2]:
                break
            overlap = _intersection(first.box, second.box)
            if overlap is None:
                continue
            area = (overlap[2] - overlap[0]) * (overlap[3] - overlap[1])
            smaller = min(
                (first.box[2] - first.box[0]) * (first.box[3] - first.box[1]),
                (second.box[2] - second.box[0]) * (second.box[3] - second.box[1]),
            )
            if smaller <= 0:
                continue
            ratio = area / smaller
            if ratio < TEXT_TEXT_MIN_RATIO:
                continue
            note = ""
            if not (first.reliable and second.reliable):
                note = "text box estimated: font has no calibration"
            findings.append(
                Finding(
                    kind="text_text",
                    handle=first.origin,
                    layer=first.layer,
                    style=first.style,
                    with_style=second.style,
                    text=first.text,
                    box=first.box,
                    with_handle=second.origin,
                    with_kind="text",
                    with_layer=second.layer,
                    with_text=second.text,
                    ratio=ratio,
                    where=((overlap[0] + overlap[2]) / 2, (overlap[1] + overlap[3]) / 2),
                    note=note,
                    via=first.via,
                )
            )
    return findings


def _curves_of_space(space, skipped: list[str]) -> list[tuple]:
    """Every curve in the space, block and table contents included.

    A wall drawn as a block still runs through a label, and a table's rules
    are what a cell's text may collide with - measured on
    ``123_check.dxf``, where the room schedule's ``TELECOM EQUIPMENT ROOM``
    cell is crossed by the column rule at x=14350.

    A DIMENSION's own lines and arrows are **not** included: they are placed
    against its text by design, so every dimension text would report a
    collision with its own dimension line. They are still reachable through
    ``own_geometry`` if a caller wants them.
    """
    curves: list[tuple] = []
    for entity in space:
        kind = entity.dxftype()
        if kind in CURVE_TYPES:
            segments = _segments(entity)
            if segments:
                curves.append((entity, segments, None))
            else:
                skipped.append(f"{entity.dxf.handle} ({kind}): no flattenable geometry")
        elif kind == "INSERT":
            for member, matrix, via in _expand(entity, 1, skipped):
                if member.dxftype() not in CURVE_TYPES:
                    continue
                placed = member.copy()
                try:
                    placed.transform(matrix)
                    segments = _segments(placed)
                except Exception:
                    continue
                if segments:
                    curves.append((member, segments, via))
        elif kind in TABLE_TYPES:
            block = _table_block(entity, skipped)
            if block is None:
                continue
            matrix = _table_matrix(entity)
            for member, _inherit, via in _expand_table(
                block, matrix, str(entity.dxf.handle), 1, skipped
            ):
                if member.dxftype() not in CURVE_TYPES:
                    continue
                placed = member.copy()
                try:
                    placed.transform(matrix)
                    segments = _segments(placed)
                except Exception:
                    continue
                if segments:
                    curves.append((member, segments, via))
    return curves


def _text_curve(
    msp, texts: list[_Text], own_geometry: dict[str, set[str]] | None = None
) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    skipped: list[str] = []
    curves = _curves_of_space(msp, skipped)
    own = own_geometry or {}

    for text in texts:
        core = _inset(text.box, CORE_INSET)
        suppress = own.get(str(text.entity.dxf.handle), frozenset()) if text.via is None else frozenset()
        hits = []
        # How far the worst curve runs *inside* the full text box, as a share of
        # the text's own height. A rule grazing the top edge and one cutting the
        # label in half are both "a curve crosses this text", but a reader has to
        # treat them differently - measured on
        # `telecom_equipment_room_plan.dxf`, where one crossing runs 100% of the
        # height (the label is cut clean through) and another 40%.
        deepest = 0.0
        for entity, segments, via in curves:
            # A text never collides with the entity it is drawn by, nor with a
            # dimension's own arrows and lines.
            if text.via is None and entity.dxf.handle == text.entity.dxf.handle:
                continue
            if str(entity.dxf.handle) in suppress:
                continue
            for segment in segments:
                if _clip(segment, core) is None:
                    continue
                hits.append((entity, via))
                full = _clip(segment, text.box)
                if full is not None:
                    (xa, ya), (xb, yb) = segment
                    length = math.hypot(xb - xa, yb - ya)
                    deepest = max(deepest, length * (full[1] - full[0]))
                break
        if not hits:
            continue
        # One finding per text, naming the first curve and how many others.
        first, via = hits[0]
        first_handle = str(first.dxf.handle or "?")
        if via is not None:
            first_handle = f"{first_handle} in {via}"
        findings.append(
            Finding(
                kind="text_curve",
                handle=text.origin,
                layer=text.layer,
                style=text.style,
                text=text.text,
                box=text.box,
                with_handle=first_handle,
                with_kind=first.dxftype(),
                with_layer=str(first.dxf.get("layer", "0")),
                with_text=None,
                # overlap_ratio is meaningless for a curve; the count of
                # crossing curves is what a reader needs instead.
                ratio=None,
                where=((text.box[0] + text.box[2]) / 2, (text.box[1] + text.box[3]) / 2),
                note=f"{len(hits)} curve(s) cross this text"
                if len(hits) > 1
                else f"{first.dxftype()} crosses this text",
                via=text.via,
            )
        )
        height = text.box[3] - text.box[1]
        if height > 0:
            findings[-1].note += (
                f"; the worst one runs {deepest / height * 100:.0f}% of the "
                f"text height inside the box"
            )
    return findings, skipped


def _glyphless_style(style_name: str, doc) -> str | None:
    """The font name when this style cannot draw non-ASCII, else None.

    An SHX stroke font carries only the characters its glyph table lists. The
    stock ``txt.shx`` has no CJK and no `²`/`Ø`/`³`, and AutoCAD then draws
    nothing for those characters **without reporting anything** - the text is
    stored, reads back correctly, and is invisible. Verified with screenshots in
    ``docs/20261117-chinese-text.md``. A SHX style with a ``bigfont`` covers CJK
    (that is what big fonts are for), so only a bigfont-less SHX style is flagged.

    TrueType is deliberately not judged here. `simhei.ttf` has no U+00B2 in its
    cmap, yet AutoCAD renders `m²` in it - measured with a COM width probe - so a
    cmap test would raise false alarms. The documented, reproducible failure is
    the SHX one.
    """
    try:
        style = doc.styles.get(style_name)
    except Exception:
        return None
    font = str(style.dxf.get("font", "") or "").strip()
    if not font:
        return None
    lower = font.lower()
    if lower.endswith((".ttf", ".ttc", ".otf")):
        return None
    # `txt`, `txt.shx`, `simplex.shx` - a stroke font, not a filled font.
    if style.dxf.get("bigfont", ""):
        return None
    return font


def _style_glyph_findings(space, texts: list[_Text]) -> list[Finding]:
    """Text whose characters its own SHX style cannot draw.

    Reports as ``text_glyphless``, one row per style and font, because a whole
    drawing in ``Standard`` is one mistake to fix, not a hundred.

    The failure this catches is silent in every other tool: the entity is there,
    ``entity_list`` reads the right string back, and the plot simply lacks those
    characters. Measured on ``draw_test/datacenter_plan_200558.dxf`` and
    ``Drawing7.dxf``, whose three area labels are all in ``Standard`` /
    ``txt.shx`` and whose `²` therefore never plots.
    """
    doc = space.doc
    groups: dict[tuple[str, str], list[_Text]] = {}
    for text in texts:
        if not text.text:
            continue
        # Only the characters an SHX stroke font is known to lack: CJK, and the
        # superscript/degree/diameter/plus-minus symbols Latin-1 draws above or
        # outside ASCII.
        exotic = {ch for ch in text.text if ord(ch) > 127}
        if not exotic:
            continue
        font = _glyphless_style(text.style, doc)
        if font is None:
            continue
        groups.setdefault((text.style, font), []).append(text)

    findings: list[Finding] = []
    for (style_name, font), group in sorted(groups.items()):
        first = group[0]
        chars = sorted({ch for t in group for ch in t.text if ord(ch) > 127})
        findings.append(
            Finding(
                kind="text_glyphless",
                handle=first.origin,
                layer=first.layer,
                style=style_name,
                affected=len(group),
                text=first.text,
                box=first.box,
                where=(
                    (first.box[0] + first.box[2]) / 2,
                    (first.box[1] + first.box[3]) / 2,
                ),
                note=(
                    f"{len(group)} text(s) use style {style_name!r} "
                    f"(font {font!r}, no CJK/Unicode fallback) and contain "
                    f"{''.join(chars)!r}: those characters do not plot. "
                    f"Point the text at a TrueType style "
                    f"(simsun.ttc / simhei.ttf) - and write the Unicode "
                    f"character, not a %% escape"
                ),
            )
        )
    return findings


def _visibility_findings(space, texts: list[_Text]) -> list[Finding]:
    """Text that will not print: it sits on a layer that is off or frozen.

    A label on an off layer is invisible on screen and missing from the plot, so
    the drawing reads as complete while the label is absent. AutoCAD hides this
    quietly - nothing warns.

    Reported as ``text_hidden``, one row per layer and reason, because a whole
    annotation layer switched off is one mistake, not forty.
    """
    try:
        layers = {layer.dxf.name: layer for layer in space.doc.layers}
    except Exception:
        return []
    groups: dict[tuple[str, str], list[_Text]] = {}
    for text in texts:
        layer = layers.get(text.layer)
        if layer is None:
            continue
        try:
            if layer.is_off():
                groups.setdefault((text.layer, "off"), []).append(text)
            elif layer.is_frozen():
                groups.setdefault((text.layer, "frozen"), []).append(text)
        except Exception:
            continue
    findings: list[Finding] = []
    for (layer, reason), group in sorted(groups.items()):
        first = group[0]
        what = "switched off" if reason == "off" else "frozen"
        findings.append(
            Finding(
                kind="text_hidden",
                handle=first.origin,
                layer=layer,
                style=first.style,
                affected=len(group),
                text=first.text,
                box=first.box,
                where=(
                    (first.box[0] + first.box[2]) / 2,
                    (first.box[1] + first.box[3]) / 2,
                ),
                note=(
                    f"{len(group)} text(s) on layer {layer!r}, which is {what}: "
                    "they do not appear in a plot"
                ),
            )
        )
    return findings


def _duplicate_findings(texts: list[_Text]) -> list[Finding]:
    """The same text drawn twice in the same place.

    Usually a copy-paste that was never cleaned up. Two labels genuinely can be
    identical in content, so this only fires when the boxes also coincide.

    Reported as ``text_duplicate``. A duplicate both hides one label under
    another and makes every count - door tags, equipment numbers - wrong.
    """
    findings: list[Finding] = []
    ordered = sorted(texts, key=lambda t: (t.text, t.box[0]))
    for i, first in enumerate(ordered):
        if not first.text.strip():
            continue
        for second in ordered[i + 1 :]:
            if second.text != first.text:
                break
            limit = max((first.box[3] - first.box[1]) * DUPLICATE_TOLERANCE, 1e-6)
            if abs(second.box[0] - first.box[0]) > limit:
                continue
            if abs(second.box[1] - first.box[1]) > limit:
                continue
            findings.append(
                Finding(
                    kind="text_duplicate",
                    handle=first.origin,
                    layer=first.layer,
                    style=first.style,
                    with_style=second.style,
                    text=first.text,
                    box=first.box,
                    with_handle=second.origin,
                    with_kind="text",
                    with_layer=second.layer,
                    with_text=second.text,
                    where=(
                        (first.box[0] + first.box[2]) / 2,
                        (first.box[1] + first.box[3]) / 2,
                    ),
                    note=(
                        "the same text twice in the same place - one of them is "
                        "a duplicate. Delete one rather than moving it"
                    ),
                    fix={
                        "tool": "entity_delete",
                        "args": {"handle": second.origin},
                        "which": "the later of the two",
                        "note": (
                            f"keep {first.origin} and delete {second.origin}, or "
                            f"the other way round - the two are identical apart "
                            f"from their handle"
                        ),
                    },
                )
            )
    return findings


def _drop_duplicate_collisions(
    findings: list[Finding], duplicates: list[Finding]
) -> list[Finding]:
    """Remove the ``text_text`` row that a ``text_duplicate`` row already covers.

    Two coincident texts always trip both checks, and the same pair listed twice
    reads as two defects instead of one. Measured on ``draw_test/123.dxf``: `01`
    at (1861.4, 2468.2) produced four rows for two real duplicates.

    The duplicate row is the one kept, because it is the better instruction:
    a ``text_text`` row offers a shift, and shifting a duplicate leaves both
    texts in the drawing. Returns a new list; the order of what remains is
    preserved.
    """
    pairs = {(d.handle, d.with_handle) for d in duplicates}
    pairs |= {(b, a) for a, b in pairs}
    kept: list[Finding] = []
    for finding in findings:
        if finding.kind == "text_text" and (finding.handle, finding.with_handle) in pairs:
            continue
        kept.append(finding)
    return kept


def _plot_scales(space) -> list[tuple[str, float, float]]:
    """Reading scale of every paper layout, as ``(name, model_per_paper, mm_scale)``.

    A model-space text is drawn at ``height`` drawing units. When it is seen
    through a paper viewport, it lands on the sheet at
    ``height × mm_per_unit / model_per_paper`` millimetres, where
    ``model_per_paper = view_height / height`` of the viewport (the familiar
    1:100 when that reads 100).

    Returns an empty list when the drawing has no paper viewport showing the
    model, which is the normal state of a model-only DXF - there is nothing to
    be unreadable *on paper* when no sheet exists.
    """
    results: list[tuple[str, float, float]] = []
    try:
        doc = space.doc
        units = int(doc.header.get("$INSUNITS", 0) or 0)
        mm_per_unit = MM_PER_UNIT.get(units)
        if mm_per_unit is None:
            return []
        for name in doc.layouts.names():
            if name == "Model":
                continue
            layout = doc.layouts.get(name)
            for entity in layout:
                if entity.dxftype() != "VIEWPORT":
                    continue
                # The paper's own viewport (status 1, or id 1) shows the sheet,
                # not the model; skip it.
                if int(entity.dxf.get("status", 0) or 0) == 1:
                    continue
                paper_height = float(entity.dxf.get("height", 0.0) or 0.0)
                view_height = float(entity.dxf.get("view_height", 0.0) or 0.0)
                if paper_height <= 0 or view_height <= 0:
                    continue
                results.append((name, view_height / paper_height, mm_per_unit))
    except Exception:
        return []
    return results


def _legibility_findings(space, texts: list[_Text]) -> list[Finding]:
    """Model text that prints smaller than ISO 3098's 2.5 mm minimum.

    The check the viewport exists for: a 100 mm label is generous on a 1:100
    sheet (1 mm) and illegible on a 1:20 sheet (5 mm is fine, 100/20/1 = 5). The
    number that matters is millimetres **on paper**, so the model height is
    divided by the viewport's scale.

    Only model-space text is judged: paper-space text is already at its printed
    size. A drawing with no paper viewport gets no rows at all - nothing to be
    unreadable on a sheet that does not exist.
    """
    scales = _plot_scales(space)
    if not scales:
        return []
    if space.name != "Model":
        return []
    findings: list[Finding] = []
    reported: dict[tuple[int, str], list[_Text]] = {}
    for text in texts:
        height = text.natural_height or (text.box[3] - text.box[1])
        if not height or height <= 0:
            continue
        for layout, model_per_paper, mm_per_unit in scales:
            on_paper = height * mm_per_unit / model_per_paper
            if on_paper >= ISO_3098_MIN_TEXT_MM:
                continue
            reported.setdefault((round(on_paper, 2), layout), []).append(text)
    for (on_paper, layout), group in sorted(reported.items()):
        first = group[0]
        findings.append(
            Finding(
                kind="text_illegible",
                handle=first.origin,
                layer=first.layer,
                style=first.style,
                affected=len(group),
                text=first.text,
                box=first.box,
                where=(
                    (first.box[0] + first.box[2]) / 2,
                    (first.box[1] + first.box[3]) / 2,
                ),
                note=(
                    f"{len(group)} text(s) print at {on_paper:g} mm on layout "
                    f"{layout!r}; ISO 3098 sets the minimum at "
                    f"{ISO_3098_MIN_TEXT_MM:g} mm. The label is "
                    f"{first.natural_height or 0:g} units tall, so the "
                    f"viewport scale (1:{model_per_paper:g}) or the text height "
                    f"is what to change - not this label alone"
                ),
            )
        )
    return findings


#: Two texts are treated as lines of *one* label - and therefore moved together -
#: when they share a layer and style, overlap horizontally by this share of the
#: narrower box, and sit **clear of each other** vertically with a gap no larger
#: than this many text heights. Measured need, on ``gpu_dc_100.dxf``: the room
#: name ``GPU 智算机房`` sits directly above ``288.0 m² 100 柜 × 12 kW`` (same
#: layer, x-overlap 100%, gap 141 units against a 600-unit height). Moving the
#: name alone is possible but breaks the label's alignment; moving both keeps it.
GROUP_X_OVERLAP = 0.5
GROUP_MAX_GAP = 1.0


def _stack_group(text: _Text, texts: list[_Text]) -> list[_Text]:
    """The texts that form one multi-line label with ``text``, including itself.

    A room label is authored as several independent TEXT/MTEXT entities stacked
    in a column - name, number, area. They are one thing to a reader, and moving
    any single line breaks the block, so a fix has to move them as a unit.

    Deliberately conservative:

    * same layer and same text style,
    * real horizontal overlap,
    * **vertical clearance** - the boxes must not already intersect. Two texts
      that overlap are a collision to report, not a label to shift as a group:
      measured on ``planted.dxf``, where ``CRAC-01 40kW`` and ``精密空调`` overlap
      each other, grouping them made one "fix" that left the collision in place,
    * a vertical gap no larger than one text height, so two unrelated labels in
      neighbouring rooms are never grouped.

    An empty result (just the text itself) is the normal case. Block-nested text
    is excluded - it has no movable handle here.
    """
    if text.via is not None:
        return [text]
    width = text.box[2] - text.box[0]
    height = text.box[3] - text.box[1]
    if width <= 0 or height <= 0:
        return [text]
    group = [text]
    for other in texts:
        if other is text or other.via is not None:
            continue
        if other.layer != text.layer or other.style != text.style:
            continue
        overlap = min(text.box[2], other.box[2]) - max(text.box[0], other.box[0])
        narrower = min(width, other.box[2] - other.box[0])
        if narrower <= 0 or overlap < narrower * GROUP_X_OVERLAP:
            continue
        # Already intersecting means this is a collision, not a stack.
        if _intersection(text.box, other.box) is not None:
            continue
        # Vertically adjacent within one text height of one another.
        if other.box[1] >= text.box[3]:
            gap = other.box[1] - text.box[3]
        elif text.box[1] >= other.box[3]:
            gap = text.box[1] - other.box[3]
        else:
            continue
        if gap > height * GROUP_MAX_GAP:
            continue
        group.append(other)
    return group


def _try_shift(
    boxes: list[Box],
    others: list[Box],
    curves: list[tuple],
    height: float,
) -> dict | None:
    """The **smallest** verified shift that clears everything, or None.

    ``boxes`` move together as one unit - a single text box in the common case,
    or the several lines of a stacked label (see ``_stack_group``). Every member
    is tested at the shifted position, so a group shift is only offered when all
    of it lands clear.

    A suggestion is only worth printing if it works *and* is not wildly larger
    than it needs to be. The naive answer - move just clear of the one thing it
    collides with - was measured to fail: on ``gpu_dc_100.dxf``, nudging the
    axis label ``D7`` 182.5 units up cleared its neighbour ``D2`` and dropped it
    straight onto the circle ``D1``.

    So the search is: for each direction, grow the step from a fraction of the
    text's own height and stop at the first distance whose new boxes touch no
    other box and no curve. The shortest of those per-direction minima wins.
    Returns None when even a large shift cannot clear the text.
    """
    if not boxes:
        return None
    tallest = max(box[3] - box[1] for box in boxes)
    widest = max(box[2] - box[0] for box in boxes)
    clearance = max(tallest * 0.10, 0.5)
    start = max(height * 0.25, clearance)
    limit = max(height * 6.0, widest * 2.0)
    best: tuple[float, float, float, str] | None = None

    def clear_at(dx: float, dy: float) -> bool:
        for box in boxes:
            moved = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
            if any(_intersection(moved, other) is not None for other in others):
                return False
            core = _inset(moved, CORE_INSET)
            if any(_clip(segment, core) is not None for segment in curves):
                return False
        return True

    for ax, ay, word in ((0.0, 1.0, "up"), (0.0, -1.0, "down"), (1.0, 0.0, "right"), (-1.0, 0.0, "left")):
        step = start
        while step <= limit:
            dx, dy = ax * step, ay * step
            if clear_at(dx, dy):
                # Add the clearance so the result does not touch on the next run.
                dx, dy = dx + ax * clearance, dy + ay * clearance
                if clear_at(dx, dy):
                    distance = math.hypot(dx, dy)
                    if best is None or distance < best[0]:
                        best = (distance, dx, dy, word)
                break
            step *= 1.35
    if best is None:
        return None
    distance, dx, dy, word = best
    return {
        "dx": round(dx, 3),
        "dy": round(dy, 3),
        "moves": f"{distance:.2f} drawing units {word}",
    }


def _no_shift_reason(
    text: _Text,
    group: list[_Text],
    all_boxes: list[Box],
    all_segments: list[tuple],
) -> str:
    """Why no shift was offered, in terms a drafter can act on.

    "Something is on every side of it" is true but unhelpful when the real
    reason is structural. Measured on ``gpu_dc_100.dxf``: the area row
    ``288.0 m² 100 柜 × 12 kW`` is 6026 units wide and straddles the axis at
    x=21400; it needs to travel 1916 units to clear that axis, and the labels
    either side of it block the way long before that. The honest advice is
    "shorten or split this line", not "move it".

    Three cases, checked in this order:

    * **wide and straddling** - the text is wider than the gap it sits in, so
      no translation can free it; splitting the line is the fix.
    * **one line of a stack** - report that the whole label was tried as a unit.
    * anything else - the generic "boxed in" wording.
    """
    width = text.box[2] - text.box[0]
    height = max(text.box[3] - text.box[1], 0.0)

    # The horizontal slots immediately left and right of this text, measured to
    # the nearest other text box. If neither slot is wide enough for the text
    # itself, no pure horizontal shift can ever work.
    left_limit = None
    right_limit = None
    for box in all_boxes:
        if box == text.box:
            continue
        if box[3] <= text.box[1] or box[1] >= text.box[3]:
            continue
        if box[2] <= text.box[0]:
            left_limit = box[2] if left_limit is None else max(left_limit, box[2])
        elif box[0] >= text.box[2]:
            right_limit = box[0] if right_limit is None else min(right_limit, box[0])
    room_left = text.box[0] - left_limit if left_limit is not None else None
    room_right = right_limit - text.box[2] if right_limit is not None else None
    widest_slot = max(
        [value for value in (room_left, room_right) if value is not None], default=None
    )
    if widest_slot is not None and width > widest_slot and width > 0:
        return (
            f"no shift can free this text: it is {width:.0f} units wide and the "
            f"widest free slot beside it is {widest_slot:.0f}. Shorten it or "
            f"split it onto two lines"
        )
    if len(group) > 1:
        others = ", ".join(m.origin for m in group if m is not text)
        return (
            f"no shift clears this text even when its whole {len(group)}-line "
            f"label moves together ({others}). Something crosses every candidate "
            f"position - move or shorten whatever crosses it, or resize the text"
        )
    return (
        "no short shift clears this text - something is on every side of it. "
        "Move or shorten whatever crosses it, or resize the text"
    )


def _attach_fixes(
    findings: list[Finding],
    texts: list[_Text],
    curves: list[tuple],
) -> None:
    """Give each collision a shift that was **verified** to clear it.

    The candidate is tested against every other box and every curve, not just
    the one it collides with - see ``_try_shift`` for the measured failure that
    made this necessary. A finding with no safe short shift carries
    ``fix: None`` and a note saying it is boxed in, rather than a move that
    would trade one collision for another.
    """
    by_origin = {t.origin: t for t in texts}
    all_boxes = [t.box for t in texts]
    all_segments = [segment for _entity, segments, _via in curves for segment in segments]
    # Group lookups are the same for every finding, so resolve them once.
    groups = {t.origin: _stack_group(t, texts) for t in texts if t.via is None}

    for finding in findings:
        if finding.kind not in ("text_text", "text_curve"):
            continue
        text = by_origin.get(finding.handle)
        if text is None:
            continue
        if text.via is not None:
            # Text expanded out of a block has no handle of its own in this
            # space: ``entity_move`` on ``4B2 in 3F1`` addresses nothing. Say so
            # instead of leaving ``fix`` empty, which reads as "checked and
            # found nothing wrong".
            finding.fix = {
                "tool": None,
                "note": (
                    f"this text lives in block reference {text.via}; move or "
                    f"edit it inside the block definition, not here. "
                    f"``entity_move`` needs the handle of a top-level entity"
                ),
            }
            continue
        # Everything except this text's own box.
        others = [box for box in all_boxes if box != text.box]
        height = text.natural_height or (text.box[3] - text.box[1])
        candidate = groups.get(finding.handle) or [text]
        shift = None
        group: list[_Text] = []
        if len(candidate) > 1:
            # A line of a stacked label is moved with its neighbours, always -
            # not only when moving it alone fails. Clearing just this line would
            # break the label's alignment, which is a worse drawing than the
            # collision: on `gpu_dc_100.dxf`, the room name alone can be nudged
            # 324 units right, but the area row under it would stay put.
            member_boxes = [member.box for member in candidate]
            outside = [box for box in all_boxes if box not in member_boxes]
            tallest = max(m.natural_height or (m.box[3] - m.box[1]) for m in candidate)
            group_shift = _try_shift(member_boxes, outside, all_segments, tallest)
            if group_shift is not None:
                shift = group_shift
                group = candidate
        if shift is None:
            shift = _try_shift([text.box], others, all_segments, height)
        if shift is None:
            finding.fix = {
                "tool": None,
                "note": _no_shift_reason(text, candidate, all_boxes, all_segments),
            }
            continue
        if group:
            # One `entity_move` per line, expressed as a single `cad_batch` so the
            # label cannot end up half-moved.
            finding.fix = {
                "tool": "cad_batch",
                "args": {
                    "steps": [
                        {
                            "tool": "entity_move",
                            "args": {
                                "handle": member.origin,
                                "dx": shift["dx"],
                                "dy": shift["dy"],
                            },
                        }
                        for member in group
                    ]
                },
                "clears": finding.with_handle,
                "moves": shift["moves"],
                "moves_with": [
                    {"handle": member.origin, "text": member.text} for member in group
                ],
                "verified": (
                    f"the whole {len(group)}-line label moves together and was "
                    f"tested against every other text box and every curve: none "
                    f"of the lines collides after the shift"
                ),
                "note": (
                    "this text is one line of a stacked label, so the lines above "
                    "and below it move with it - moving this line alone always "
                    "lands on one of them"
                ),
            }
            continue
        finding.fix = {
            "tool": "entity_move",
            "args": {
                "handle": finding.handle,
                "dx": shift["dx"],
                "dy": shift["dy"],
            },
            "clears": finding.with_handle,
            "moves": shift["moves"],
            "verified": (
                "tested against every other text box and every curve in this "
                "drawing: this shift collides with none of them"
            ),
            "note": (
                "one option: moving whatever crosses the text may suit the "
                "drawing better, and an intended crossing needs no change"
            ),
        }
        if len(candidate) > 1:
            # The whole label could not be moved, so only this line is offered.
            # Say so: the reader has to know the other lines stay put, or the
            # label ends up ragged and they will not know why.
            stay = ", ".join(m.origin for m in candidate if m is not text)
            finding.fix["note"] = (
                f"this line belongs to a {len(candidate)}-line label, but the "
                f"label cannot move as a whole - so only {finding.handle} moves "
                f"and {stay} stays put. Moving this line alone will leave the "
                f"label misaligned; shortening or re-laying-out the label is the "
                f"better fix"
            )
            finding.fix["moves_alone"] = True


def detect(path: str, *, layout: str | None = None, expand_blocks: bool = True,
           min_corridor_width_mm: float | None = None, corridor_ids=(), require_circulation=False,
           rack_loop: str | None = None, min_rack_loop_mm: float | None = None) -> dict:
    """Run both checks on one DXF and return a report dict.

    Raises ``FileNotFoundError`` for a missing file and ``ValueError`` for a
    file that is not a DXF or a layout that does not exist - a caller should
    print those, not treat them as "clean".
    """
    try:
        doc = ezdxf.readfile(path)
    except FileNotFoundError:
        raise
    except (OSError, ezdxf.DXFStructureError) as exc:
        # ezdxf reports a non-DXF (a DWG, say) as a plain OSError.
        raise ValueError(str(exc)) from exc
    if layout is None:
        space = doc.modelspace()
    else:
        names = list(doc.layouts.names())
        if layout not in names:
            raise ValueError(
                f"no layout named {layout!r}; this file has: {', '.join(names)}"
            )
        space = doc.layouts.get(layout)

    texts, skipped_text, own_geometry = _collect_texts(space, expand_blocks=expand_blocks)
    findings = _text_text(texts)
    curve_findings, skipped_curves = _text_curve(space, texts, own_geometry)
    findings.extend(curve_findings)
    _attach_fixes(findings, texts, _curves_of_space(space, []))
    findings.extend(_scale_findings(texts))
    findings.extend(_visibility_findings(space, texts))
    duplicates = _duplicate_findings(texts)
    # Two coincident texts trip both checks; listing the pair twice reads as two
    # defects instead of one. The duplicate row is kept because it is the better
    # instruction - a shift would leave both texts in the drawing.
    findings = _drop_duplicate_collisions(findings, duplicates)
    findings.extend(duplicates)
    findings.extend(_legibility_findings(space, texts))
    findings.extend(_style_glyph_findings(space, texts))

    # Physical collisions. A text check cannot see a rack standing in a
    # doorway; on the plan that motivated this (2026-11-19) the only symptom
    # was a text_curve row on the rack's own label, which would have been
    # "fixed" by moving the label and leaving the rack in the opening.
    from .physical import physical_findings
    skipped_physical: list[str] = []
    findings.extend(physical_findings(space, skipped_physical))

    from .circulation import KINDS, circulation
    access_findings, access, skipped_access = circulation(space, min_corridor_width_mm, corridor_ids, require_circulation)
    findings.extend(access_findings)
    loop = None
    if rack_loop is not None or min_rack_loop_mm is not None:
        from .rack_loop import KIND, rack_loop_check
        extra, loop = rack_loop_check(space, rack_loop, min_rack_loop_mm, expand_blocks)
        findings.extend(extra)
        KINDS = (*KINDS, KIND)
        if loop['status'] == 'not_checked':
            skipped_access.append('rack_loop: ' + loop['reason'])
    findings.sort(key=lambda f: (-(f.ratio or 0), f.kind))

    # How many text entities the space holds *directly*: a reader that
    # reported "0 texts, 0 findings" on a drawing whose labels all live in
    # blocks, tables or dimensions would be passing an incomplete read off as
    # a clean one.
    direct_texts = sum(1 for e in space if e.dxftype() in TEXT_TYPES)
    dimensions = sum(1 for e in space if e.dxftype() == "DIMENSION")
    from_dimensions = sum(1 for t in texts if t.entity.dxftype() == "DIMENSION")
    expanded = sum(1 for t in texts if t.via is not None)
    containers = sum(1 for e in space if e.dxftype() == "INSERT" or e.dxftype() in TABLE_TYPES)

    return {
        "path": path,
        "layout": layout or "Model",
        "texts_measured": len(texts),
        "texts_total": direct_texts,
        "texts_in_blocks": expanded,
        "dimensions": dimensions,
        "texts_from_dimensions": from_dimensions,
        "containers": containers,
        "curves": sum(1 for e in space if e.dxftype() in CURVE_TYPES),
        "findings": [f.as_dict() for f in findings],
        "circulation": access,
        **({"rack_loop": loop} if loop is not None else {}),
        "by_kind": {
            kind: sum(1 for f in findings if f.kind == kind)
            for kind in (
            "text_text",
            "text_curve",
            "text_scale",
            "text_hidden",
            "text_duplicate",
            "text_illegible",
            "text_glyphless",
            "opening_blocked",
            "solid_overlap",
            *KINDS,
        )
        },
        "not_checked": sorted(set(skipped_text + skipped_curves + skipped_physical + skipped_access)),
        "skipped_types": sorted(SKIPPED_TYPES),
    }