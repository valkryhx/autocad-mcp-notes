"""Draw a pump-room plan whose defects all hide inside containers, then check it.

Drawing8 proved that the seven checks fire on text sitting directly in model
space. This fixture attacks the other half of the problem: **text that a naive
reader never sees at all**. Every planted collision here lives inside something
- a block attribute, a block nested in a block, a rotated reference, a
microsoft leader, a table cell - so a checker that only walks model space reports
a clean drawing and looks confident while doing it.

Planted defects, one per hiding place:

    1 text_text      two PUMP references 150 apart: their TAG ATTRIBs collide
    2 text_text      two METER references whose INNER block's text collides
    3 text_text      a 90-degree NAMEPLATE's text against a model label
    4 text_text      a MULTILEADER's text against a model label
    5 text_curve     a partition line through a SENSOR's ATTRIB
    6 text_glyphless `Ø` in Standard (txt.shx), which has no `Ø` glyph
    7 text_hidden    a note on REF-NOTES, which is switched off
    8 text_duplicate V-01 drawn twice at one point
    9 text_scale     3 DIMENSION texts 2.5 units tall among 250-unit labels
   10 text_illegible the same dimensions: 0.05 mm on an A2 at 1:50
   T  text_text      a label on a measured TABLE cell (needs AutoCAD; see below)

Clean controls, which must stay silent:

    * properly spaced VALVE tags in the same block family as the colliding ones
    * a `Ø` label in the CN style (simsun.ttc), which does draw `Ø`
    * axis numbers sitting inside their bubbles
    * every table cell on its own, with nothing on top of it

Run:

    python drawing9.py --inspect    # print every measured box, change nothing
    python drawing9.py              # build, add the table via COM, check, assert
    python drawing9.py --no-table   # skip the COM step, say so in the report

Why the table needs AutoCAD: ezdxf 1.4.4 has no table API and raises
`CopyNotSupported` for ACAD_TABLE. The table is therefore authored through COM
and saved back as DXF, exactly as a person would make one. When AutoCAD is not
available the run says the table path was **not** exercised rather than quietly
scoring it as passed.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

import ezdxf
from ezdxf.math import Vec2

# A Chinese Windows console is GBK, which cannot encode `Ø`, `²` or `±` - all of
# which this fixture prints on purpose. Without this the run dies *after* the
# check succeeded and the whole result is lost. Same fix as tools/text_overlap.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tools.text_overlap import detect  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Drawing9.dxf")

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  {status}  {name}" + ("" if condition else f"  [{detail}]"))
    if not condition:
        FAILURES.append(name)


def build() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    doc.header["$DIMSCALE"] = 1.0

    # A TrueType style: draws CJK, `²` and `Ø`.
    doc.styles.add("CN", font="simsun.ttc")
    # `Standard` stays as shipped - `txt.shx`, which draws none of them.

    for name, color in (
        ("P-WALL", 7),
        ("P-PART", 8),
        ("P-EQUIP", 4),
        ("P-PIPE", 5),
        ("P-TEXT", 7),
        ("P-AXIS", 1),
        ("P-ANNO", 2),
        ("REF-NOTES", 250),
    ):
        doc.layers.add(name, color=color)
    doc.layers.get("REF-NOTES").off()

    dimstyle = doc.dimstyles.add("SMALL")
    dimstyle.dxf.dimtxt = 2.5
    dimstyle.dxf.dimscale = 1.0
    dimstyle.dxf.dimasz = 2.5
    dimstyle.dxf.dimexe = 0.625
    dimstyle.dxf.dimexo = 0.625

    # ── block definitions ──────────────────────────────────────────────────
    # 1. A pump whose tag varies per insertion -> the text is an ATTRIB.
    pump = doc.blocks.new("PUMP")
    pump.add_attdef("TAG", dxfattribs={"height": 250, "style": "CN", "insert": (0, 0)})

    # 2. A meter whose label lives in a block nested inside it.
    core = doc.blocks.new("METER_CORE")
    core.add_text(
        "DN100", dxfattribs={"height": 200, "style": "CN", "insert": (0, 0)}
    )
    meter = doc.blocks.new("METER")
    meter.add_blockref("METER_CORE", (0, 0))

    # 3. A nameplate meant to be inserted rotated.
    plate = doc.blocks.new("NAMEPLATE")
    plate.add_text(
        "立式泵组 A", dxfattribs={"height": 250, "style": "CN", "insert": (0, 0)}
    )

    # 4. A sensor whose tag is an ATTRIB, and a valve for the clean control.
    sensor = doc.blocks.new("SENSOR")
    sensor.add_attdef("ID", dxfattribs={"height": 250, "style": "CN", "insert": (0, 0)})
    valve = doc.blocks.new("VALVE")
    valve.add_attdef("ID", dxfattribs={"height": 250, "style": "CN", "insert": (0, 0)})

    msp = doc.modelspace()

    # ── walls: outer 24000 x 16000, inner partition at x=11000 ─────────────
    for start, end in (
        ((0, 0), (6000, 0)),
        ((7200, 0), (24000, 0)),  # door opening at x 6000-7200
        ((24000, 0), (24000, 16000)),
        ((24000, 16000), (0, 16000)),
        ((0, 16000), (0, 0)),
    ):
        msp.add_line(start, end, dxfattribs={"layer": "P-WALL"})
    for start, end in (
        ((200, 200), (6000, 200)),
        ((7200, 200), (23800, 200)),
        ((23800, 200), (23800, 15800)),
        ((23800, 15800), (200, 15800)),
        ((200, 15800), (200, 200)),
        ((200, 200), (6000, 200)),
    ):
        msp.add_line(start, end, dxfattribs={"layer": "P-WALL"})
    # Partition down the middle, with its own door gap at y 6000-7200.
    msp.add_line((11000, 200), (11000, 6000), dxfattribs={"layer": "P-PART"})
    msp.add_line((11000, 7200), (11000, 15800), dxfattribs={"layer": "P-PART"})

    # Door leaf and swing, hinged at the opening's left jamb.
    msp.add_line((6000, 0), (6000, 1200), dxfattribs={"layer": "P-WALL"})
    msp.add_arc(
        center=(6000, 0), radius=1200, start_angle=0, end_angle=90,
        dxfattribs={"layer": "P-WALL"},
    )

    # ── planted 1: two pump tags 150 apart, text 250 high ─────────────────
    for tag, y in (("P-01", 13000.0), ("P-02", 12850.0)):
        ref = msp.add_blockref("PUMP", (2200, y))
        ref.add_auto_attribs({"TAG": tag})

    # ── planted 2: two meters whose nested text collides ──────────────────
    for x, y in ((2500.0, 3000.0), (2500.0, 2900.0)):
        msp.add_blockref("METER", (x, y))

    # ── planted 3: a rotated nameplate against a model label ──────────────
    msp.add_blockref("NAMEPLATE", (8500, 3000), dxfattribs={"rotation": 90})
    against_plate = msp.add_mtext(
        "检修通道", dxfattribs={"style": "CN", "char_height": 250, "layer": "P-TEXT"}
    )
    against_plate.dxf.attachment_point = 5
    against_plate.dxf.insert = (8625, 3600)

    # ── planted 5: a partition line through a sensor's ATTRIB ─────────────
    sensor_ref = msp.add_blockref("SENSOR", (6500, 13000))
    sensor_ref.add_auto_attribs({"ID": "TEMP-01"})
    msp.add_line((7000, 11500), (7000, 14500), dxfattribs={"layer": "P-PIPE"})

    # ── clean control: three valves, well spaced ──────────────────────────
    for index, x in enumerate((4500.0, 6000.0, 7500.0), start=1):
        ref = msp.add_blockref("VALVE", (x, 5000))
        ref.add_auto_attribs({"ID": f"V-{index:02d}"})

    # ── axis lines and bubbles (clean: the number sits inside the bubble) ─
    for index, x in enumerate((0.0, 12000.0, 24000.0), start=1):
        msp.add_line((x, -1200), (x, 17200), dxfattribs={"layer": "P-AXIS"})
        for y in (-1500.0, 17500.0):
            msp.add_circle((x, y), 300, dxfattribs={"layer": "P-AXIS"})
            number = msp.add_mtext(
                str(index), dxfattribs={"style": "CN", "char_height": 250, "layer": "P-AXIS"}
            )
            number.dxf.attachment_point = 5
            number.dxf.insert = (x, y)
    for letter, y in (("A", 0.0), ("B", 8000.0), ("C", 16000.0)):
        msp.add_line((-1200, y), (25200, y), dxfattribs={"layer": "P-AXIS"})
        for x in (-1500.0, 25500.0):
            msp.add_circle((x, y), 300, dxfattribs={"layer": "P-AXIS"})
            number = msp.add_mtext(
                letter, dxfattribs={"style": "CN", "char_height": 250, "layer": "P-AXIS"}
            )
            number.dxf.attachment_point = 5
            number.dxf.insert = (x, y)

    # ── planted 4: a multileader whose text a model label sits on ─────────
    # The leader's text box hangs *below* its insert and does not start at it:
    # measured at (14000,5750)-(15484,6000) with char_height 250. The label is
    # placed from those measured numbers, then `--inspect` confirms the overlap
    # before the assertion is trusted - placing it from the insert point alone
    # would have left the text clear and the defect unplanted.
    doc.mleader_styles.duplicate_entry("Standard", "ML")
    builder = msp.add_multileader_mtext("ML")
    builder.context.char_height = 250
    builder.set_content("冷冻水供水管")
    builder.build(insert=Vec2(14000, 6000))
    on_leader = msp.add_mtext(
        "接至空调机房", dxfattribs={"style": "CN", "char_height": 250, "layer": "P-TEXT"}
    )
    on_leader.dxf.attachment_point = 5
    on_leader.dxf.insert = (14700, 5880)

    # ── planted 6: `Ø` in the SHX style, which cannot draw it ─────────────
    shx_pipe = msp.add_mtext("Ø32 冷冻水管", dxfattribs={"char_height": 250, "layer": "P-PIPE"})
    shx_pipe.dxf.attachment_point = 5
    shx_pipe.dxf.insert = (16000, 7000)

    # clean control: the same `Ø` in the CN style does plot.
    cn_pipe = msp.add_mtext(
        "Ø32 冷冻水管", dxfattribs={"style": "CN", "char_height": 250, "layer": "P-PIPE"}
    )
    cn_pipe.dxf.attachment_point = 5
    cn_pipe.dxf.insert = (16000, 6300)

    # ── planted 7: a note on a switched-off layer ─────────────────────────
    hidden = msp.add_mtext(
        "施工说明：管道试压 1.6 MPa，保压 24h",
        dxfattribs={"style": "CN", "char_height": 250, "layer": "REF-NOTES"},
    )
    hidden.dxf.attachment_point = 5
    hidden.dxf.insert = (16000, 9200)

    # ── planted 8: the same tag twice at one point ────────────────────────
    # Kept clear of axis B (y=8000) and of the x=24000 axis: the duplicate must
    # be the only defect here, or it also reports a curve crossing and the
    # counts stop meaning anything.
    for _ in range(2):
        tag = msp.add_mtext(
            "V-01dup", dxfattribs={"style": "CN", "char_height": 250, "layer": "P-TEXT"}
        )
        tag.dxf.attachment_point = 5
        tag.dxf.insert = (20500, 11000)

    # ── planted 9 and 10: dimensions at the style's own tiny scale ────────
    for x in (13000.0, 16000.0, 19000.0):
        dim = msp.add_linear_dim(
            base=(x, -2400),
            p1=(x, 0),
            p2=(x + 3000, 0),
            dimstyle="SMALL",
            dxfattribs={"layer": "P-ANNO"},
        )
        dim.render()

    # ── title ────────────────────────────────────────────────────────────
    title = msp.add_mtext(
        "泵房设备平面图  1:50", dxfattribs={"style": "CN", "char_height": 450, "layer": "P-TEXT"}
    )
    title.dxf.attachment_point = 5
    title.dxf.insert = (12000, -3600)

    # ── paper layout: A2 at 1:50, so printed sizes are meaningful ────────
    layout = doc.layouts.new("A2-1to50")
    layout.page_setup(size=(594, 420), margins=(10, 10, 10, 10), units="mm")
    layout.add_viewport(
        center=(297, 210),
        size=(574, 400),
        view_center_point=(12000, 8000),
        view_height=20000,  # 400 mm x 50 = 20000 model units => 1:50
    )

    return doc


# ── the table, which only AutoCAD can author ────────────────────────────────


def add_table(path: str) -> tuple[bool, str]:
    """Add the equipment schedule through COM and save back as DXF.

    Works on a **copy** for the same reason ``tools/text_overlap/dwg.py`` does:
    ``SaveAs`` re-points the document it is called on, so it must never be called
    on a file the user might have open. See
    ``docs/20261120-dwg-saveas-repoint.md``.

    Returns ``(ok, note)``; ``note`` always says what happened, including a
    failure, so the caller can report the table path as untested instead of
    silently counting it as clean.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        return False, f"pywin32 unavailable: {exc}"

    try:
        pythoncom.CoInitialize()
    except Exception:  # pragma: no cover - already initialised
        pass

    try:
        from tools.text_overlap.dwg import _call

        app = _call(win32com.client.GetActiveObject, "AutoCAD.Application")
    except Exception as exc:
        return False, f"AutoCAD is not running ({type(exc).__name__}: {exc})"

    workdir = tempfile.mkdtemp(prefix="tc_d9_")
    source_copy = os.path.join(workdir, "drawing9_in.dxf")
    table_out = os.path.join(workdir, "drawing9_out.dxf")
    shutil.copy2(path, source_copy)

    document = None
    try:
        document = _call(app.Documents.Open, source_copy, True)
        actual = _call(lambda: document.FullName)
        if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(
            os.path.abspath(source_copy)
        ):
            _call(document.Close, False)
            return False, "AutoCAD opened a different document than the copy; abandoned"

        msp = _call(lambda: document.ModelSpace)
        rows, cols, row_h, col_w = 5, 3, 700.0, 2400.0
        # The insertion point must be a VARIANT array, not a tuple - the same
        # COM requirement `Table.Move` has (AGENTS.md section 10). A tuple gets
        # as far as argument checking and then returns E_INVALIDARG, which reads
        # like "bad argument count" and is not.
        from array import array

        from win32com.client import VARIANT

        point = VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8, array("d", [12000.0, 15000.0, 0.0])
        )
        table = _call(msp.AddTable, point, rows, cols, row_h, col_w)

        content = [
            ("设备表", "型号", "数量"),
            ("冷冻水泵", "PUMP-200", "2"),
            ("冷却水泵", "PUMP-250", "2"),
            ("板式换热器", "HEX-80", "1"),
            ("定压补水装置", "CPS-16", "1"),
        ]
        for r, row in enumerate(content):
            for c, value in enumerate(row):
                # `SetText`, not `SetTextString`: the latter's signature in this
                # build is not (row, col, text) and mangles a string into an int
                # parse. Measured on AutoCAD 2026; see docs/20261121-*.
                _call(table.SetText, r, c, value)
                _call(table.SetCellAlignment, r, c, 5)  # acMiddleCenter
                try:
                    _call(table.SetCellTextHeight, r, c, 250.0)
                except Exception:
                    pass  # not fatal; the scale check reports it if tiny
                try:
                    # Cells do not follow `AcDbText.StyleName`; this is the only
                    # lever. The style has to exist in *this* document (the DXF's
                    # `CN` came across with the copy), or AutoCAD says 未找到主键.
                    _call(table.SetCellTextStyle, r, c, "CN")
                except Exception:
                    pass  # the glyphless check will still report the cells

        _call(document.SaveAs, table_out, 61)  # ac2013_dxf
        return True, f"table added through AutoCAD ({rows}x{cols} equipment schedule)"
    except Exception as exc:
        return False, f"AutoCAD failed to add the table: {type(exc).__name__}: {exc}"
    finally:
        if document is not None:
            try:
                _call(document.Close, False)
            except Exception:  # pragma: no cover
                pass
        if os.path.isfile(table_out):
            shutil.move(table_out, path)
        shutil.rmtree(workdir, ignore_errors=True)


def add_cell_collision(path: str) -> tuple[bool, str]:
    """Put a label on top of a *measured* table cell.

    The cell's position is read back from the table AutoCAD just wrote, not
    guessed from the insertion point - a collision placed by arithmetic would
    only test the arithmetic.
    """
    from tools.text_overlap.overlap import _collect_texts

    doc = ezdxf.readfile(path)
    texts, _skipped, _own = _collect_texts(doc.modelspace())
    cells = [t for t in texts if t.via and t.text.strip()]
    if not cells:
        return False, "no table cell text was measured, so the table path is untested"

    # Pick a cell in the middle of the schedule: unmistakably inside the table.
    cell = sorted(cells, key=lambda t: (t.box[1], t.box[0]))[len(cells) // 2]
    left, bottom, right, top = cell.box
    label = doc.modelspace().add_mtext(
        "此处文字压住表格",
        dxfattribs={"style": "CN", "char_height": 250, "layer": "P-TEXT"},
    )
    label.dxf.attachment_point = 5
    label.dxf.insert = ((left + right) / 2.0, (bottom + top) / 2.0)

    out = os.path.join(tempfile.gettempdir(), "d9_cell.dxf")
    if os.path.exists(out):
        os.remove(out)
    doc.saveas(out)
    shutil.move(out, path)
    return True, f"placed a label on table cell {cell.text.strip()!r} at its measured centre"


# ── checks ──────────────────────────────────────────────────────────────────


def _apply_fixes(path: str) -> tuple[int, int]:
    """Apply every offered fix and re-check. Returns (applied, still_broken)."""
    report = detect(path)
    doc = ezdxf.readfile(path)
    steps: list[tuple[str, float, float]] = []
    deletes: list[str] = []
    for finding in report["findings"]:
        fix = finding.get("fix") or {}
        if fix.get("tool") == "entity_move":
            args = fix["args"]
            steps.append((args["handle"], args["dx"], args["dy"]))
        elif fix.get("tool") == "cad_batch":
            for step in fix["args"]["steps"]:
                args = step["args"]
                steps.append((args["handle"], args["dx"], args["dy"]))
        elif fix.get("tool") == "entity_delete":
            deletes.append(fix["args"]["handle"])

    moved: set[str] = set()
    for handle, dx, dy in steps:
        entity = doc.entitydb.get(handle)
        if entity is None:
            continue
        entity.translate(dx, dy, 0)
        moved.add(handle)
    for handle in deletes:
        entity = doc.entitydb.get(handle)
        if entity is not None:
            doc.modelspace().delete_entity(entity)

    out = os.path.join(HERE, "_Drawing9_fixed.dxf")
    if os.path.exists(out):
        os.remove(out)
    doc.saveas(out)
    after = detect(out)
    still = [
        f
        for f in after["findings"]
        if f["kind"] in ("text_text", "text_curve") and f["handle"] in (moved | set(deletes))
    ]
    os.remove(out)
    return len(steps) + len(deletes), len(still)


def _inspect(path: str) -> None:
    from tools.text_overlap.overlap import _collect_texts

    doc = ezdxf.readfile(path)
    texts, skipped, _own = _collect_texts(doc.modelspace())
    print(f"{len(texts)} text(s) measured, {len(skipped)} skipped")
    for text in sorted(texts, key=lambda t: (-t.box[3], t.box[0])):
        left, bottom, right, top = text.box
        via = text.via or "model space"
        print(
            f"  ({left:8.0f},{bottom:8.0f})-({right:8.0f},{top:8.0f})"
            f"  h={text.natural_height or 0:6.0f}  {via:<12} {text.text[:24]!r}"
        )
    for reason in skipped:
        print(f"  skipped: {reason}")


def main() -> int:
    doc = build()
    if os.path.exists(OUT):
        os.remove(OUT)
    doc.saveas(OUT)
    print(f"built {os.path.basename(OUT)}")

    if "--inspect" in sys.argv:
        _inspect(OUT)
        return 0

    table_note = "skipped (--no-table)"
    if "--no-table" not in sys.argv:
        ok, table_note = add_table(OUT)
        if ok:
            placed, place_note = add_cell_collision(OUT)
            table_note = f"{table_note}; {place_note}"
            if not placed:
                ok = False
    else:
        ok = False

    report = detect(OUT)
    kinds = report["by_kind"]
    print(
        f"  measured {report['texts_measured']} text entities "
        f"({report['texts_total']} in the space, {report['texts_in_blocks']} from "
        f"{report['containers']} container(s)), {report['curves']} curves\n"
        f"  {len(report['findings'])} finding(s): "
        + ", ".join(f"{k}={v}" for k, v in kinds.items() if v)
    )
    print(f"  table path: {table_note}")

    print("\nplanted defects - each must be found:")
    # A label laid on a table cell crosses the cell's grid lines as well as the
    # cell text, so the table path adds a second `text_curve`. That is the check
    # being right, not doubling up: the same label really does sit on both.
    for kind, expected in (
        ("text_text", 5 if ok else 4),
        ("text_curve", 2 if ok else 1),
        ("text_scale", 1),
        ("text_illegible", 1),
        ("text_hidden", 1),
        ("text_duplicate", 1),
        ("text_glyphless", 1),
    ):
        check(f"{kind} reported ({expected})", kinds[kind] == expected, f"got {kinds[kind]}")

    print("\nthe collisions must be the ones hidden inside containers:")
    # A collision row names one side in `text` and the other in `with.text`, and
    # which side is which depends on the pair. Searching only `text` misses half
    # the findings - it did, on the first run of this fixture.
    colliding = " ".join(
        (f.get("text") or "") + " " + ((f.get("with") or {}).get("text") or "")
        for f in report["findings"]
        if f["kind"] in ("text_text", "text_curve")
    )
    for needle, why in (
        ("P-01", "the pump's TAG ATTRIB"),
        ("DN100", "the text inside a block nested in a block"),
        ("立式泵组", "the text inside a rotated block"),
        ("冷冻水供水管", "the multileader's text"),
        ("TEMP-01", "the sensor's ATTRIB"),
    ):
        check(f"{why} is reported", needle in colliding, colliding[:160])
    if ok:
        check("the table cell collision is reported", "此处文字压住表格" in colliding, colliding[:160])

    print("\nclean controls - must stay silent:")
    # The glyphless row names the *style* in `style`, not in its text. Asserting
    # on the text alone would pass even if the CN copy were flagged, so check the
    # style field, which is what actually decides plotting.
    glyphless = [f for f in report["findings"] if f["kind"] == "text_glyphless"]
    check("exactly one glyphless row", len(glyphless) == 1, str(len(glyphless)))
    if glyphless:
        row = glyphless[0]
        check(
            "the glyphless row is the Standard-style `Ø` label",
            row.get("style") == "Standard" and "Ø32" in (row.get("text") or ""),
            f"style={row.get('style')!r} text={row.get('text')!r}",
        )
    # The CN copy is identical apart from its style. If the check looked at
    # characters rather than at styles, the CN copy would be unnamed only
    # because the report happened to show one row - so assert the row count is
    # one *and* that no row carries the CN style.
    check(
        "the CN-style `Ø` copy is not reported",
        all(f.get("style") != "CN" for f in glyphless),
        str([f.get("style") for f in glyphless]),
    )
    check("V-02 is not reported as colliding", "V-02" not in colliding, colliding[:160])
    axis_rows = [
        f
        for f in report["findings"]
        if f["kind"] == "text_curve" and "P-AXIS" in (f.get("with", {}).get("layer") or "")
    ]
    check("axis numbers inside their bubbles are not reported", not axis_rows, str(len(axis_rows)))
    if ok:
        cell_rows = [
            f
            for f in report["findings"]
            if f["kind"] == "text_text" and "此处文字压住表格" not in (f.get("text") or "")
            and ("设备表" in (f.get("text") or "") or "PUMP-200" in (f.get("text") or ""))
        ]
        check("undisturbed table cells are not reported", not cell_rows, str(len(cell_rows)))

    print("\nthe offered fixes must actually clear what they claim:")
    applied, failed = _apply_fixes(OUT)
    check("every applicable fix clears its finding", failed == 0, f"{failed} of {applied + failed}")
    print(f"         applied {applied} fix step(s)")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} -> {', '.join(FAILURES)}")
        return 1
    if not ok:
        print(
            "PARTIAL: every check that could run passed, but the TABLE path was NOT "
            f"exercised ({table_note}). Start AutoCAD and re-run before calling this done."
        )
        return 0
    print("PASS: every container-hidden defect found, every clean control quiet")
    return 0


if __name__ == "__main__":
    sys.exit(main())