"""Draw a complete small plan with planted defects and clean controls, then check it.

This is the acceptance test that matters most: a checker is only useful if it
finds what is really wrong *and* stays quiet about what is fine. Two other
fixtures already cover those halves separately (`planted.py` for detection,
`clean.py` for quietness); this one puts both in the same drawing, drawn the way
a person would actually lay out a sheet - walls with a door opening, axis bubbles,
a room label stack, a rack row, a title, notes, dimensions, a paper layout.

Planted (each must be reported, with the right kind):

    1 text_text        two cabinet labels 150 units apart on a 250-high text
    2 text_curve       a partition wall running through a standby-plant label
    3 text_scale       dimension text drawn 2.5 units tall among 250-unit labels
    4 text_illegible   the same dimensions, 2.5 units at 1:50 = 0.05 mm on paper
    5 text_hidden      a note on a layer that is switched off
    6 text_duplicate   R-01 drawn twice at the same point
    7 text_glyphless   an area label in Standard (txt.shx), which cannot draw `²`

Clean controls (must stay silent):

    * axis numbers sitting inside their bubbles - normal drafting
    * a second area label in the CN style (simsun.ttc), which does draw `²`
    * the room label stack, well spaced
    * rack tags, well spaced
    * ASCII text in the SHX style

    python drawing8.py            # build, check, assert
    python drawing8.py --keep     # also leave Drawing8.dxf beside this file
"""

from __future__ import annotations

import os
import sys

import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tools.text_overlap import detect  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Drawing8.dxf")

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

    # A TrueType style: draws CJK and `²`.
    doc.styles.add("CN", font="simsun.ttc")
    # The stock SHX style stays as `Standard` with `txt` - it draws neither. This
    # is the setup a drawing made by hand usually has.

    for name, color in (
        ("A-WALL", 7),
        ("A-WALL-IN", 8),
        ("A-DOOR", 3),
        ("A-AXIS", 1),
        ("A-TEXT", 7),
        ("A-EQUIP", 4),
        ("A-ANNO", 2),
        ("REF-NOTES", 250),
    ):
        doc.layers.add(name, color=color)
    doc.layers.get("REF-NOTES").off()

    # Dimensions drawn at the style's own scale, which is what makes them tiny.
    dimstyle = doc.dimstyles.add("SMALL")
    dimstyle.dxf.dimtxt = 2.5
    dimstyle.dxf.dimscale = 1.0
    dimstyle.dxf.dimasz = 2.5
    dimstyle.dxf.dimexe = 0.625
    dimstyle.dxf.dimexo = 0.625

    msp = doc.modelspace()

    # ── walls, with a real door opening ────────────────────────────────────
    # Outer wall 20000 x 14000, thickness 200, door gap 1200 at y=0, x 8400-9600.
    wall = [
        ((0, 0), (8400, 0)),
        ((9600, 0), (20000, 0)),
        ((20000, 0), (20000, 14000)),
        ((20000, 14000), (0, 14000)),
        ((0, 14000), (0, 0)),
    ]
    for start, end in wall:
        msp.add_line(start, end, dxfattribs={"layer": "A-WALL"})
    # Inner face of the wall, so the plan reads as a wall with thickness.
    inner = [
        ((200, 200), (8400, 200)),
        ((9600, 200), (19800, 200)),
        ((19800, 200), (19800, 13800)),
        ((19800, 13800), (200, 13800)),
        ((200, 13800), (200, 200)),
    ]
    for start, end in inner:
        msp.add_line(start, end, dxfattribs={"layer": "A-WALL-IN"})

    # Door leaf and its swing arc, hinged at the opening's left jamb.
    msp.add_line((8400, 0), (8400, 1200), dxfattribs={"layer": "A-DOOR"})
    msp.add_arc(
        center=(8400, 0), radius=1200, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )

    # ── planted defect 2: a partition wall through a label ─────────────────
    # 250-unit label centred on x=7000, y=12000; the line runs right through it.
    msp.add_line((7000, 10800), (7000, 13200), dxfattribs={"layer": "A-WALL-IN"})
    standby = msp.add_mtext(
        "备用发电机组", dxfattribs={"style": "CN", "char_height": 250, "layer": "A-TEXT"}
    )
    standby.dxf.attachment_point = 5
    standby.dxf.insert = (7000, 12000)

    # ── axis lines and bubbles (clean: the number sits *inside* the bubble) ─
    axis_x = [0.0, 10000.0, 20000.0]
    axis_y = [0.0, 14000.0]
    for index, x in enumerate(axis_x, start=1):
        msp.add_line((x, -1200), (x, 15200), dxfattribs={"layer": "A-AXIS"})
        for y, label in ((-1500.0, str(index)), (15500.0, str(index))):
            msp.add_circle((x, y), 300, dxfattribs={"layer": "A-AXIS"})
            number = msp.add_mtext(
                label, dxfattribs={"style": "CN", "char_height": 250, "layer": "A-AXIS"}
            )
            number.dxf.attachment_point = 5
            number.dxf.insert = (x, y)
    for index, y in enumerate(axis_y, start=1):
        letter = "AB"[index - 1]
        msp.add_line((-1200, y), (21200, y), dxfattribs={"layer": "A-AXIS"})
        for x, side in ((-1500.0, 0), (21500.0, 1)):
            msp.add_circle((x, y), 300, dxfattribs={"layer": "A-AXIS"})
            number = msp.add_mtext(
                letter, dxfattribs={"style": "CN", "char_height": 250, "layer": "A-AXIS"}
            )
            number.dxf.attachment_point = 5
            number.dxf.insert = (x, y)

    # ── room label stack (clean: properly spaced) ─────────────────────────
    for text, y in (
        ("通信机房  TELECOM ROOM", 6600),
        ("R-01", 6200),
        ("54.48 m²", 5800),  # CN style, so `²` plots: must NOT be glyphless
    ):
        entity = msp.add_mtext(
            text, dxfattribs={"style": "CN", "char_height": 250, "layer": "A-TEXT"}
        )
        entity.dxf.attachment_point = 5
        entity.dxf.insert = (5000, y)

    # ── rack row (clean tags) + one rack whose tag a wall crosses ─────────
    for index in range(6):
        x = 12000 + index * 900
        msp.add_lwpolyline(
            [(x, 3000), (x + 800, 3000), (x + 800, 4200), (x, 4200)],
            close=True,
            dxfattribs={"layer": "A-EQUIP"},
        )
        tag = msp.add_mtext(
            f"K{index + 1:02d}",
            dxfattribs={"style": "CN", "char_height": 200, "layer": "A-EQUIP"},
        )
        tag.dxf.attachment_point = 5
        tag.dxf.insert = (x + 400, 3600)

    # ── planted defect 1: two cabinet labels 150 units apart ──────────────
    for text, y in (("配电柜 PD-1", 9000), ("配电柜 PD-2", 8850)):
        entity = msp.add_mtext(
            text, dxfattribs={"style": "CN", "char_height": 250, "layer": "A-TEXT"}
        )
        entity.dxf.attachment_point = 5
        entity.dxf.insert = (4000, y)

    # ── planted defect 6: the same tag twice, in the same place ───────────
    for _ in range(2):
        tag = msp.add_mtext(
            "R-01dup", dxfattribs={"style": "CN", "char_height": 250, "layer": "A-TEXT"}
        )
        tag.dxf.attachment_point = 5
        tag.dxf.insert = (16000, 10800)

    # ── planted defect 7: area in the SHX style, which cannot draw `²` ────
    # No style attribute means `Standard` = txt.shx.
    shx_area = msp.add_mtext(
        "18.60 m²", dxfattribs={"char_height": 250, "layer": "A-TEXT"}
    )
    shx_area.dxf.attachment_point = 5
    shx_area.dxf.insert = (16000, 6400)

    # A clean control in the same spot: ASCII in the SHX style is fine.
    shx_plain = msp.add_mtext(
        "UPS-A 40kVA", dxfattribs={"char_height": 250, "layer": "A-TEXT"}
    )
    shx_plain.dxf.attachment_point = 5
    shx_plain.dxf.insert = (16000, 5800)

    # ── planted defect 5: a note on a layer that is switched off ──────────
    # Centred in the free band between the inner wall face (x=200) and the
    # partition (x=7000). The note is 5000 units wide, so x=3600 spans
    # 1100-6100 and touches neither.
    hidden = msp.add_mtext(
        "施工说明：本层楼面活荷载 16 kN/m²",
        dxfattribs={"style": "CN", "char_height": 250, "layer": "REF-NOTES"},
    )
    hidden.dxf.attachment_point = 5
    hidden.dxf.insert = (3600, 11500)

    # ── planted defects 3 and 4: dimensions at the style's own tiny scale ─
    for index, x in enumerate((1200.0, 4200.0, 7200.0)):
        dim = msp.add_linear_dim(
            base=(x, -2400),
            p1=(x, 0),
            p2=(x + 3000, 0),
            dimstyle="SMALL",
            dxfattribs={"layer": "A-ANNO"},
        )
        dim.render()

    # ── title ────────────────────────────────────────────────────────────
    # Below the lower axis bubbles (which sit at y=-1500), well clear of them.
    title = msp.add_mtext(
        "通信机房平面图  1:50", dxfattribs={"style": "CN", "char_height": 450, "layer": "A-TEXT"}
    )
    title.dxf.attachment_point = 5
    title.dxf.insert = (10000, -3600)

    # ── paper layout, so printed size is meaningful (1:50 on A3) ─────────
    layout = doc.layouts.new("A3-1to50")
    layout.page_setup(size=(420, 297), margins=(10, 10, 10, 10), units="mm")
    layout.add_viewport(
        center=(210, 148),
        size=(400, 277),
        view_center_point=(10000, 7000),
        view_height=13850,  # 277 mm x 50 = 13850 model units => 1:50
    )

    return doc


def main() -> int:
    doc = build()
    path = OUT
    if os.path.exists(path):
        os.remove(path)
    doc.saveas(path)
    print(f"built {os.path.basename(path)}")

    report = detect(path)
    kinds = report["by_kind"]
    print(
        f"  measured {report['texts_measured']} texts, {report['curves']} curves\n"
        f"  {len(report['findings'])} finding(s): "
        + ", ".join(f"{k}={v}" for k, v in kinds.items() if v)
    )

    print("\nplanted defects - each must be found:")
    for kind, expected in (
        ("text_text", 1),
        ("text_curve", 1),
        ("text_scale", 1),
        ("text_illegible", 1),
        ("text_hidden", 1),
        ("text_duplicate", 1),
        ("text_glyphless", 1),
    ):
        check(f"{kind} reported ({expected})", kinds[kind] == expected, f"got {kinds[kind]}")

    print("\nclean controls - must stay silent:")
    glyphless_texts = " ".join(
        f.get("text", "") for f in report["findings"] if f["kind"] == "text_glyphless"
    )
    check(
        "the CN-style area label is not called glyphless",
        "54.48" not in glyphless_texts,
        glyphless_texts,
    )
    check(
        "ASCII in the SHX style is not called glyphless",
        "UPS-A" not in glyphless_texts,
        glyphless_texts,
    )
    axis_rows = [
        f
        for f in report["findings"]
        if f["kind"] == "text_curve" and "A-AXIS" in (f.get("with", {}).get("layer") or "")
    ]
    check("axis numbers inside their bubbles are not reported", not axis_rows, str(len(axis_rows)))
    curve_texts = " ".join(
        f.get("text", "") for f in report["findings"] if f["kind"] == "text_curve"
    )
    check(
        "the well-spaced room label is not reported",
        "通信机房" not in curve_texts and "54.48" not in curve_texts,
        curve_texts,
    )
    check(
        "rack tags are not reported",
        "K01" not in curve_texts and "K06" not in curve_texts,
        curve_texts,
    )

    print("\nthe offered fixes must actually clear what they claim:")
    cleared, failed = _apply_fixes(path)
    check("every applicable fix clears its finding", failed == 0, f"{failed} failed of {cleared + failed}")
    print(f"         applied {cleared + failed} fix step(s)")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} -> {', '.join(FAILURES)}")
        return 1
    print("PASS: Drawing8 is diagnosed completely and the clean controls stay quiet")
    if "--keep" not in sys.argv:
        pass  # the DXF is the point of the fixture, so it is kept either way
    return 0


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

    out = os.path.join(HERE, "_Drawing8_fixed.dxf")
    if os.path.exists(out):
        os.remove(out)
    doc.saveas(out)
    after = detect(out)

    still = [
        f
        for f in after["findings"]
        if f["kind"] in ("text_text", "text_curve")
        and (f["handle"] in moved or f["handle"] in deletes)
    ]
    os.remove(out)
    return len(steps) + len(deletes), len(still)


if __name__ == "__main__":
    sys.exit(main())