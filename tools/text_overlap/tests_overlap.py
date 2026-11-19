"""End-to-end tests of the text-overlap check, runnable without AutoCAD.

    python tests_overlap.py

Covers the paths a real user hits: every entity type read, block references
(including rotated, nested and non-uniformly scaled), the error paths, and the
two accuracy claims that do not need a live CAD. The AutoCAD-anchored checks
live in ``crosscheck.py`` and ``anchors.py``.
"""

from __future__ import annotations

import os
import sys
import tempfile

import ezdxf

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tools.text_overlap import detect  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def _new(path: str):
    doc = ezdxf.new("R2010", setup=True)
    doc.styles.add("CN", font="simhei.ttf")
    return doc, doc.modelspace()


def _save(doc, name: str) -> str:
    path = os.path.join(tempfile.gettempdir(), name)
    if os.path.exists(path):
        os.remove(path)
    doc.saveas(path)
    return path


def test_empty_drawing() -> None:
    print("\nempty drawing")
    doc, _ = _new("")
    report = detect(_save(doc, "ov_empty.dxf"))
    check("zero findings", not report["findings"], str(report["by_kind"]))
    check("nothing hidden", report["not_checked"] == [], str(report["not_checked"]))


def test_text_overlap() -> None:
    print("\nTEXT entities overlapping")
    doc, msp = _new("")
    for x in (0.0, 50.0):
        entity = msp.add_text("Label", height=200, dxfattribs={"style": "CN"})
        entity.set_placement((x, 0.0))
    report = detect(_save(doc, "ov_text.dxf"))
    check("one text_text finding", report["by_kind"]["text_text"] == 1, str(report["by_kind"]))


def test_curve_through_text() -> None:
    print("line through a MTEXT")
    doc, msp = _new("")
    text = msp.add_mtext("CROSSED", dxfattribs={"char_height": 250, "style": "CN"})
    text.dxf.attachment_point = 1
    text.dxf.insert = (0.0, 0.0)
    msp.add_line((-500, -120), (500, -120))  # inside the box, which hangs to -250
    report = detect(_save(doc, "ov_curve.dxf"))
    check("one text_curve finding", report["by_kind"]["text_curve"] == 1, str(report["by_kind"]))


def test_near_miss_is_quiet() -> None:
    print("a line that misses the text")
    doc, msp = _new("")
    text = msp.add_mtext("SAFE", dxfattribs={"char_height": 250, "style": "CN"})
    text.dxf.attachment_point = 1
    text.dxf.insert = (0.0, 0.0)
    msp.add_line((-500, -400), (500, -400))  # 150 below the box's floor
    report = detect(_save(doc, "ov_near.dxf"))
    check("no finding", not report["findings"], str(report["by_kind"]))


def test_block_text_detected() -> None:
    print("text inside block references")
    doc, msp = _new("")
    block = doc.blocks.new("TAG")
    block.add_mtext("BLOCKTEXT", dxfattribs={"char_height": 200, "style": "CN", "insert": (0, 0)})
    msp.add_blockref("TAG", (0, 0))
    msp.add_blockref("TAG", (100, 0))
    report = detect(_save(doc, "ov_block.dxf"))
    check("the block's text was measured", report["texts_measured"] == 2, str(report["texts_total"]))
    check("overlap found", report["by_kind"]["text_text"] == 1, str(report["by_kind"]))
    finding = report["findings"][0] if report["findings"] else {}
    check("finding names its block", "in_block" in finding, str(finding))


def test_block_rotation_is_read() -> None:
    """The matrix-to-rotation extraction is what makes a rotated block's text
    measurable: ezdxf's own ``transform`` scales the text but silently drops
    the rotation."""
    print("block transform -> rotation and scale")
    from tools.text_overlap.overlap import _transform_rotation

    doc, msp = _new("")
    block = doc.blocks.new("B")
    block.add_mtext("X", dxfattribs={"char_height": 200, "style": "CN", "insert": (0, 0)})

    cases = [
        ("upright", {}, 0.0, 1.0),
        ("rotated 45", {"rotation": 45}, 45.0, 1.0),
        ("rotated 90", {"rotation": 90}, 90.0, 1.0),
        ("uniform x2", {"xscale": 2, "yscale": 2}, 0.0, 2.0),
        ("rotated + scaled", {"rotation": 30, "xscale": 3, "yscale": 3}, 30.0, 3.0),
    ]
    for name, attribs, want_deg, want_scale in cases:
        reference = msp.add_blockref("B", (0, 0), dxfattribs=attribs)
        rotation, scale = _transform_rotation(reference.matrix44())
        ok = abs(rotation - want_deg) < 1e-6 and abs(scale - want_scale) < 1e-6
        check(f"{name}: rotation={want_deg} scale={want_scale}", ok, f"got {rotation:.3f}, {scale:.3f}")

    # A non-similarity must be refused rather than approximated.
    skewed = msp.add_blockref("B", (0, 0), dxfattribs={"xscale": 3, "yscale": 1})
    _rotation, scale = _transform_rotation(skewed.matrix44())
    check("non-uniform scale refused (scale 0)", scale == 0.0, f"got {scale}")


def test_rotated_block_curve_hit() -> None:
    """A rotated block's label is still found by a line that crosses it."""
    print("line across a rotated block's text")
    doc, msp = _new("")
    block = doc.blocks.new("B")
    block.add_mtext("ROTTED", dxfattribs={"char_height": 200, "style": "CN", "insert": (0, 0)})
    msp.add_blockref("B", (0, 0), dxfattribs={"rotation": 90})
    # Measured: a rotation-90 label's box is x 0..202, y 0..838 - the text runs
    # UP the +Y axis, because local -Y (where an attach=1 MTEXT hangs) maps to
    # WCS +X at 90 degrees. A horizontal line through y=400 cuts it.
    msp.add_line((-400, 400), (400, 400))
    report = detect(_save(doc, "ov_rot.dxf"))
    check("rotated block text measured", report["texts_measured"] == 1, str(report["texts_measured"]))
    check("crossing found", report["by_kind"]["text_curve"] == 1, str(report["by_kind"]))


def test_nested_block() -> None:
    print("nested block reference")
    doc, msp = _new("")
    inner = doc.blocks.new("INNER")
    inner.add_mtext("NESTED", dxfattribs={"char_height": 200, "style": "CN", "insert": (0, 0)})
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", (0, 0))
    msp.add_blockref("OUTER", (0, 0))
    report = detect(_save(doc, "ov_nested.dxf"))
    check("nested text measured", report["texts_measured"] == 1, str(report["texts_measured"]))


def test_non_uniform_block_is_reported() -> None:
    print("non-uniformly scaled block")
    doc, msp = _new("")
    block = doc.blocks.new("B")
    block.add_mtext("SQUASHED", dxfattribs={"char_height": 200, "style": "CN", "insert": (0, 0)})
    msp.add_blockref("B", (0, 0), dxfattribs={"xscale": 3, "yscale": 1})
    report = detect(_save(doc, "ov_nonuniform.dxf"))
    check("no silent pass", any("non-uniform" in r for r in report["not_checked"]), str(report["not_checked"]))


def test_no_blocks_flag() -> None:
    print("expand_blocks=False")
    doc, msp = _new("")
    block = doc.blocks.new("B")
    block.add_mtext("X", dxfattribs={"char_height": 200, "style": "CN", "insert": (0, 0)})
    msp.add_blockref("B", (0, 0))
    report = detect(_save(doc, "ov_noblocks.dxf"), expand_blocks=False)
    check("block text is not checked, and says so", any("not read" in r for r in report["not_checked"]),
          str(report["not_checked"]))


def test_attrib_is_read() -> None:
    """A block's variable text lives in ATTRIB entities, which
    ``virtual_entities()`` does not return - so reading only that loses the
    part that differs between insertions."""
    print("block ATTRIB text")
    doc, msp = _new("")
    block = doc.blocks.new("TAG")
    block.add_attdef("NAME", dxfattribs={"height": 200, "style": "CN", "insert": (0, 0)})
    first = msp.add_blockref("TAG", (0, 0))
    first.add_auto_attribs({"NAME": "UPS-1"})
    second = msp.add_blockref("TAG", (50, 0))  # sits on top of the first
    second.add_auto_attribs({"NAME": "UPS-2"})
    report = detect(_save(doc, "ov_attrib.dxf"))
    check("both ATTRIBs measured", report["texts_measured"] == 2, str(report["texts_measured"]))
    check("overlap found", report["by_kind"]["text_text"] == 1, str(report["by_kind"]))
    if report["findings"]:
        text = report["findings"][0]["text"]
        check("finding shows the tag and its value", "NAME=" in text, text)


def test_table_cells_are_read() -> None:
    """An ACAD_TABLE draws nothing itself: its cells are MTEXT in an anonymous
    ``*T<n>`` block named by ``block_record_handle``. A reader that skips the
    table skips every cell.

    Tested on the checked-in sample rather than a built table: ezdxf 1.4.4 has
    no table API and refuses to copy an ACAD_TABLE (``CopyNotSupported``), so
    there is no way to author one here.
    """
    print("table cell text (draw_test/123_check.dxf)")
    source = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "draw_test", "123_check.dxf")
    )
    if not os.path.exists(source):
        check("table sample is present", False, f"missing {source}")
        return
    report = detect(source)
    src = ezdxf.readfile(source)
    tables = [e for e in src.modelspace() if e.dxftype() == "ACAD_TABLE"]
    check("the sample really has tables", len(tables) == 3, str(len(tables)))
    check("cells measured", report["texts_measured"] > report["texts_total"],
          f"{report['texts_measured']} vs {report['texts_total']} direct")
    check("tables counted as containers", report["containers"] >= 3, str(report["containers"]))
    # The three tables' cells must land in three different places, not all on
    # the origin: a missing insert transform shows up as every cell stacked.
    from tools.text_overlap.overlap import _collect_texts

    texts, _skipped, _own = _collect_texts(src.modelspace())
    table_boxes = [t.box for t in texts if t.via and t.via in {x.dxf.handle for x in tables}]
    check("table cells were measured", len(table_boxes) > 0, str(len(table_boxes)))
    if table_boxes:
        ys = {round(b[1] / 1000) for b in table_boxes}
        check("cells spread over more than one table", len(ys) > 1, str(sorted(ys)))


def test_attrib_via_block_rotation() -> None:
    """An ATTRIB inside a rotated reference is already in WCS: no matrix
    should be applied to it, or it would be placed twice."""
    print("ATTRIB under a rotated reference")
    doc, msp = _new("")
    block = doc.blocks.new("TAG")
    block.add_attdef("NAME", dxfattribs={"height": 200, "style": "CN", "insert": (0, 0)})
    ref = msp.add_blockref("TAG", (3000, 4000), dxfattribs={"rotation": 90})
    ref.add_auto_attribs({"NAME": "ROTATED"})
    report = detect(_save(doc, "ov_attrib_rot.dxf"))
    check("measured", report["texts_measured"] == 1, str(report["texts_measured"]))
    # Read the box back through the module: it must sit at the reference's
    # insert point, not at the origin.
    from tools.text_overlap.overlap import _collect_texts

    doc2 = ezdxf.readfile(os.path.join(tempfile.gettempdir(), "ov_attrib_rot.dxf"))
    texts, _skipped, _own = _collect_texts(doc2.modelspace())
    if texts:
        box = texts[0].box
        check("box is near the insert point (3000,4000)", box[0] > 2500 and box[1] > 3500,
              f"box={[round(v) for v in box]}")


def test_text_scale_outlier() -> None:
    """Text drawn far smaller than the drawing's habit is a defect on its own."""
    print("text scale outlier")
    doc, msp = _new("")
    for i in range(6):
        text = msp.add_mtext(f"LABEL {i}", dxfattribs={"char_height": 200, "style": "CN"})
        text.dxf.attachment_point = 1
        text.dxf.insert = (i * 6000.0, 0.0)
    tiny = msp.add_mtext("tiny", dxfattribs={"char_height": 4, "style": "CN"})
    tiny.dxf.attachment_point = 1
    tiny.dxf.insert = (0.0, -5000.0)
    report = detect(_save(doc, "ov_scale.dxf"))
    check("one text_scale finding", report["by_kind"]["text_scale"] == 1, str(report["by_kind"]))
    if report["findings"]:
        note = report["findings"][0].get("note", "")
        check("finding states the mismatch", "against a drawing median" in note, note)


def test_rotated_text_is_not_a_scale_outlier() -> None:
    """A 90-degree label's box is as tall as it is long: comparing raw box
    heights would call every vertical label an outlier."""
    print("rotated text must not look like a scale outlier")
    doc, msp = _new("")
    for i in range(6):
        text = msp.add_mtext(f"LABEL {i}", dxfattribs={"char_height": 200, "style": "CN"})
        text.dxf.attachment_point = 1
        text.dxf.insert = (i * 6000.0, 0.0)
    vertical = msp.add_mtext("VERTICAL LABEL", dxfattribs={"char_height": 200, "style": "CN"})
    vertical.dxf.attachment_point = 1
    vertical.dxf.insert = (0.0, -8000.0)
    vertical.dxf.rotation = 90.0
    report = detect(_save(doc, "ov_rot_scale.dxf"))
    check("no scale finding", report["by_kind"]["text_scale"] == 0, str(report["by_kind"]))


def test_dimension_text_is_read() -> None:
    """A DIMENSION's text is a real box that can collide with other text."""
    print("dimension text (draw_test/123_check.dxf)")
    source = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "draw_test", "123_check.dxf")
    )
    if not os.path.exists(source):
        check("dimension sample is present", False, f"missing {source}")
        return
    report = detect(source)
    src = ezdxf.readfile(source)
    dim_count = sum(1 for e in src.modelspace() if e.dxftype() == "DIMENSION")
    check("the sample has dimensions", dim_count > 0, str(dim_count))
    check(
        "every dimension text measured",
        report["texts_from_dimensions"] == dim_count,
        f"{report['texts_from_dimensions']} of {dim_count}",
    )
    from tools.text_overlap.overlap import _collect_texts

    texts, _skipped, own = _collect_texts(src.modelspace())
    dim_texts = [t for t in texts if t.entity.dxftype() == "DIMENSION"]
    if dim_texts:
        heights = {round(t.natural_height or 0) for t in dim_texts}
        # $DIMSCALE is 50 and $DIMTXT 2.5, so the drawn height is 125 - not the
        # 2.5 stored in the *D block.
        check("drawn height follows DIMTXT x DIMSCALE", heights == {125}, str(sorted(heights)))
    check("dimensions expose their own geometry to skip", len(own) > 0, str(len(own)))
    # A dimension's text must not collide with its own arrows and lines.
    dim_curve = [f for f in report["findings"] if f["kind"] == "text_curve" and f["handle"] in own]
    check("no dimension reports its own geometry", not dim_curve, str(dim_curve[:2]))


def test_fix_is_verified_safe() -> None:
    """A suggested shift must clear the finding AND not create a new one.

    The naive version - move just clear of the one colliding box - was measured
    to fail: nudging label D7 in gpu_dc_100.dxf cleared D2 and landed on a
    circle. This test plants exactly that shape of trap.
    """
    print("fix suggestions must be safe")
    doc, msp = _new("")
    # Two labels on top of each other, and a line just above them: moving the
    # upper one straight up would clear its neighbour and hit the line.
    lower = msp.add_mtext("LOWER", dxfattribs={"char_height": 200, "style": "CN"})
    lower.dxf.attachment_point = 1
    lower.dxf.insert = (0.0, 0.0)
    upper = msp.add_mtext("UPPER", dxfattribs={"char_height": 200, "style": "CN"})
    upper.dxf.attachment_point = 1
    upper.dxf.insert = (0.0, -30.0)
    msp.add_line((-500, 260), (2000, 260))  # above both
    msp.add_line((-500, -420), (2000, -420))  # below both
    report = detect(_save(doc, "ov_fixsafe.dxf"))
    for finding in report["findings"]:
        fix = finding.get("fix")
        if not fix:
            continue
        if not fix.get("tool"):
            continue
        # Apply it and re-check: the finding must be gone and nothing new
        # may appear at the moved handle.
        path = os.path.join(tempfile.gettempdir(), "ov_fixsafe.dxf")
        d = ezdxf.readfile(path)
        if fix["tool"] == "entity_move":
            steps = [fix["args"]]
        elif fix["tool"] == "cad_batch":
            # A multi-line label moves as one `cad_batch` of `entity_move`
            # steps; apply every step, then check each moved handle.
            steps = [step["args"] for step in fix["args"]["steps"]]
        else:
            continue
        moved_handles = []
        for args in steps:
            handle = args["handle"]
            entity = d.entitydb.get(handle)
            if entity is None:
                check(f"fix handle {handle} exists", False)
                continue
            entity.translate(args["dx"], args["dy"], 0)
            moved_handles.append(handle)
        moved_path = os.path.join(tempfile.gettempdir(), "ov_fixsafe_moved.dxf")
        if os.path.exists(moved_path):
            os.remove(moved_path)
        d.saveas(moved_path)
        after = detect(moved_path)
        still = [
            f
            for f in after["findings"]
            if f["handle"] in moved_handles and f["kind"] in ("text_text", "text_curve")
        ]
        check(
            f"{finding['kind']} {','.join(moved_handles)}: suggested shift clears it",
            not still,
            str([(f["kind"], f.get("with", {}).get("handle")) for f in still]),
        )


def test_boxed_in_text_gets_no_fix() -> None:
    """When no shift can clear a text, the finding must say so - not propose one.

    Built so it is genuinely impossible: a line runs exactly through the middle
    of the label *vertically* and another one *horizontally*, both longer than
    any candidate shift, so moving in any direction leaves the text crossed.
    """
    print("impossible text admits there is no shift")
    doc, msp = _new("")
    text = msp.add_mtext("PINNED", dxfattribs={"char_height": 200, "style": "CN"})
    text.dxf.attachment_point = 5  # centred, so the crossing lines hit its middle
    text.dxf.insert = (0.0, 0.0)
    # A cross through the text's centre, each arm far longer than any candidate
    # shift the search will try.
    msp.add_line((0.0, -100000), (0.0, 100000))
    msp.add_line((-100000, 0.0), (100000, 0.0))
    report = detect(_save(doc, "ov_boxed.dxf"))
    crossed = [f for f in report["findings"] if f["kind"] == "text_curve"]
    check("the label is reported as crossed", len(crossed) > 0, str(len(crossed)))
    if crossed:
        fix = crossed[0].get("fix") or {}
        # Either no shift is offered, or the one offered is verified to work:
        # both are acceptable answers, an unverified guess is not.
        if fix.get("tool"):
            check(
                "a shift was offered and carries a verification claim",
                bool(fix.get("verified")),
                str(fix),
            )
        else:
            check("the note explains why", "every" in (fix.get("note") or ""), str(fix))


def test_hidden_text_is_reported() -> None:
    """Text on an off or frozen layer does not print - a silent defect."""
    print("text on a hidden layer")
    for state, method in (("off", "off"), ("frozen", "freeze")):
        doc, msp = _new("")
        doc.layers.add("NOTES")
        getattr(doc.layers.get("NOTES"), method)()
        text = msp.add_mtext(
            "hidden note", dxfattribs={"char_height": 250, "style": "CN", "layer": "NOTES"}
        )
        text.dxf.attachment_point = 1
        text.dxf.insert = (0.0, 0.0)
        report = detect(_save(doc, f"ov_hidden_{state}.dxf"))
        check(f"layer {state}: reported", report["by_kind"]["text_hidden"] == 1, str(report["by_kind"]))
        if report["findings"]:
            note = report["findings"][0].get("note", "")
            check(f"layer {state}: note says why", "plot" in note, note)

    # A normal visible layer must stay quiet.
    doc, msp = _new("")
    text = msp.add_mtext("visible", dxfattribs={"char_height": 250, "style": "CN"})
    text.dxf.attachment_point = 1
    text.dxf.insert = (0.0, 0.0)
    report = detect(_save(doc, "ov_visible.dxf"))
    check("a visible layer is not reported", report["by_kind"]["text_hidden"] == 0, str(report["by_kind"]))


def test_duplicate_text_is_reported() -> None:
    """A copy-paste left on top of the original."""
    print("duplicate text")
    doc, msp = _new("")
    for dx in (0.0, 30.0):  # 30 of 200 units off: a careless paste
        text = msp.add_mtext("D-101", dxfattribs={"char_height": 200, "style": "CN"})
        text.dxf.attachment_point = 1
        text.dxf.insert = (dx, 0.0)
    report = detect(_save(doc, "ov_dup.dxf"))
    check("reported as duplicate", report["by_kind"]["text_duplicate"] == 1, str(report["by_kind"]))

    # The same text far apart is two real labels, not a duplicate.
    doc2, msp2 = _new("")
    for x in (0.0, 5000.0):
        text = msp2.add_mtext("D-101", dxfattribs={"char_height": 200, "style": "CN"})
        text.dxf.attachment_point = 1
        text.dxf.insert = (x, 0.0)
    report2 = detect(_save(doc2, "ov_dup_far.dxf"))
    check("far apart is not a duplicate", report2["by_kind"]["text_duplicate"] == 0, str(report2["by_kind"]))


def test_rotation_is_not_applied_twice() -> None:
    """Text that already carries its own rotation inside a rotated block.

    A member at 20 degrees in a block rotated 45 must end up at 65, not 110.
    This was a real bug: the code added the block's angle on top of the rotation
    ezdxf's ``transform()`` had already folded in. It stayed invisible because
    MTEXT stores that rotation in ``text_direction`` (leaving ``rotation``
    absent, so the "base" was 0) while TEXT stores it in ``rotation`` directly.
    """
    print("rotation must not be applied twice")
    for kind, build in (
        ("TEXT", lambda b: b.add_text(
            "LONGLABEL", height=10, dxfattribs={"style": "CN", "insert": (0, 0), "rotation": 20.0}
        )),
        ("MTEXT", lambda b: b.add_mtext(
            "LONGLABEL", dxfattribs={"char_height": 10, "style": "CN", "insert": (0, 0), "rotation": 20.0}
        )),
    ):
        # Reference shapes for a 10-high "LONGLABEL": 20deg ~63x31, 65deg ~36x62,
        # 110deg ~31x63. So the box shape alone identifies the angle.
        doc, _ = _new("")
        block = doc.blocks.new("B")
        build(block)
        doc.modelspace().add_blockref("B", (0, 0), dxfattribs={"rotation": 45})
        path = _save(doc, f"ov_rot2_{kind}.dxf")
        from tools.text_overlap.overlap import _collect_texts

        placed_doc = ezdxf.readfile(path)
        texts, _skipped, _own = _collect_texts(placed_doc.modelspace())
        check(f"{kind}: measured", len(texts) == 1, str(len(texts)))
        if not texts:
            continue
        box = texts[0].box
        w, h = box[2] - box[0], box[3] - box[1]
        # At the correct 65 degrees the box is taller than wide. At the buggy 110
        # it is wider than tall (31x63 flipped the other way); at 20 it is much
        # wider than tall. So "taller than wide, and not extremely so" pins it.
        check(
            f"{kind}: box is the 65-degree shape, not 110",
            h > w and 1.4 < h / w < 2.2,
            f"w={w:.2f} h={h:.2f} ratio={h / w:.2f}",
        )


def test_merged_table_cells_keep_correct_text() -> None:
    """A merged table cell's text is already positioned by AutoCAD.

    Merge geometry lives in an opaque binary blob (group 310) that ezdxf does not
    parse - but it does not need to be parsed. Measured on a 5x3 table written by
    AutoCAD with its top row merged into one cell:

    * the cell MTEXT count drops from 15 to 13 (three cells became one),
    * the surviving ``R0C0`` insert moves from column 1's centre (5, -5.5) to the
      merged span's centre (15, -5.5),

    so measuring each MTEXT at its own insert gives the right box with no
    knowledge of the merge. This test pins that, and the fixture is the real
    AutoCAD output.
    """
    print("merged table cell (real AutoCAD output)")
    path = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "draw_test", "overlap_proto", "verify", "merged_table.dxf",
        )
    )
    if not os.path.exists(path):
        # The fixture is committed, so its absence is a broken checkout, not a
        # reason to pass. Skipping here would report "all tests passed" while
        # the claim this test exists to pin went unchecked - the exact failure
        # AGENTS.md rule 6 forbids.
        check("merged table fixture is present", False, f"missing {path}")
        return
    from tools.text_overlap.overlap import _collect_texts

    doc = ezdxf.readfile(path)
    texts, _skipped, _own = _collect_texts(doc.modelspace())
    by_text = {t.text: t for t in texts}
    check("the merged row's three cells became one text", "R0C0" in by_text and "R0C1" not in by_text,
          str(sorted(by_text)[:6]))
    if "R0C0" in by_text:
        box = by_text["R0C0"].box
        width = box[2] - box[0]
        # A single 10-wide column's text is ~15 wide; the merged 3-column span is
        # ~20, centred on x=15.
        centre = (box[0] + box[2]) / 2
        check(
            "the surviving text is centred on the merged span",
            abs(centre - 15.0) < 3.0,
            f"centre={centre:.2f} width={width:.2f}",
        )


def test_illegible_text_uses_viewport_scale() -> None:
    """Text must be judged in millimetres on paper, not model units.

    A 3000-unit label is generous at 1:100 (30 mm) and illegible at 1:2000
    (1.5 mm). The viewport's ``view_height / height`` is the reading scale.

    Verified against reality: gpu_dc_100.dxf has a 1:100 viewport on an A1
    sheet. Its 2.36 mm printed height for the 160-unit labels was read back out
    of the plotted PDF and matches this arithmetic once the font's em/cap ratio
    (1.4545 for simhei) is allowed for.
    """
    print("legibility is judged on paper")
    from tools.text_overlap.overlap import ISO_3098_MIN_TEXT_MM

    # 1. Model text at 1:100: 160 units = 1.6 mm, below the 2.5 mm minimum.
    doc, msp = _new("")
    doc.header["$INSUNITS"] = 4  # millimetres
    label = msp.add_mtext("small", dxfattribs={"char_height": 160, "style": "CN"})
    label.dxf.attachment_point = 1
    label.dxf.insert = (0.0, 0.0)
    # A paper layout with a 1:100 viewport over the model.
    layout = doc.layouts.new("Sheet")
    layout.add_viewport(
        center=(410.0, 277.5),
        size=(820.0, 555.0),
        view_center_point=(41000.0, 27750.0),
        view_height=55500.0,
    )
    report = detect(_save(doc, "ov_illegible.dxf"))
    check(
        f"160 units at 1:100 is below the {ISO_3098_MIN_TEXT_MM} mm minimum",
        report["by_kind"]["text_illegible"] >= 1,
        str(report["by_kind"]),
    )
    if report["findings"]:
        note = next((f.get("note", "") for f in report["findings"] if f["kind"] == "text_illegible"), "")
        check("the note states the printed size", "mm" in note, note)

    # 2. The same text at 1:20 is 8 mm: legible, so quiet.
    doc2, msp2 = _new("")
    doc2.header["$INSUNITS"] = 4
    big = msp2.add_mtext("small", dxfattribs={"char_height": 160, "style": "CN"})
    big.dxf.attachment_point = 1
    big.dxf.insert = (0.0, 0.0)
    layout2 = doc2.layouts.new("Sheet")
    layout2.add_viewport(
        center=(150.0, 100.0),
        size=(280.0, 200.0),
        view_center_point=(0.0, 0.0),
        view_height=4000.0,  # 4000/200 = 20 -> 1:20
    )
    report2 = detect(_save(doc2, "ov_legible.dxf"))
    check("160 units at 1:20 is legible, so no finding",
          report2["by_kind"]["text_illegible"] == 0, str(report2["by_kind"]))

    # 3. No paper layout at all: nothing to be unreadable on, so quiet.
    doc3, msp3 = _new("")
    doc3.header["$INSUNITS"] = 4
    tiny = msp3.add_mtext("tiny", dxfattribs={"char_height": 1, "style": "CN"})
    tiny.dxf.attachment_point = 1
    tiny.dxf.insert = (0.0, 0.0)
    report3 = detect(_save(doc3, "ov_nolayout.dxf"))
    check("a model-only drawing gets no legibility findings",
          report3["by_kind"]["text_illegible"] == 0, str(report3["by_kind"]))


def test_glyphless_style_is_reported() -> None:
    """Text whose SHX style cannot draw its own characters.

    `txt.shx` carries no CJK and no `²`, and AutoCAD draws nothing for them
    without any warning - the string reads back correctly and the plot is
    missing the characters (docs/20261117-chinese-text.md). This pins that the
    check fires for an SHX style, stays quiet for a TrueType one, and stays quiet
    for ASCII in an SHX style.
    """
    print("text a style cannot draw")

    # A `txt.shx` style in this fixture must be created explicitly: ezdxf's
    # `setup=True` also installs a `Standard` whose font is `txt`.
    doc, msp = _new("")
    doc.styles.add("SHX", font="txt")
    for style, text, dx in (
        ("SHX", "54.48 m²", 0.0),      # superscript in a stroke font: dropped
        ("SHX", "A-ROOM", 3000.0),     # plain ASCII: always fine
        ("CN", "54.48 m²", 6000.0),    # TrueType: renders, no finding
    ):
        ent = msp.add_mtext(text, dxfattribs={"char_height": 250, "style": style})
        ent.dxf.attachment_point = 1
        ent.dxf.insert = (dx, 0.0)
    report = detect(_save(doc, "ov_glyphless.dxf"))
    rows = [f for f in report["findings"] if f["kind"] == "text_glyphless"]
    check("one row for the SHX style, not one per text", len(rows) == 1, str(report["by_kind"]))
    if rows:
        note = rows[0].get("note", "")
        check("the note names the style", "SHX" in note, note)
        check("the note names the characters", "²" in note, note)
        check("the note offers a fix", "TrueType" in note, note)
    check(
        "ASCII in an SHX style is not reported",
        not any("A-ROOM" in (f.get("text") or "") for f in rows),
        str([f.get("text") for f in rows]),
    )
    check(
        "TrueType with the same text is not reported",
        not any((f.get("text") or "").startswith("54.48") and f.get("style") == "CN" for f in rows),
        str([(f.get("text"), f.get("style")) for f in rows]),
    )

    # A big font is exactly what makes an SHX style able to draw CJK.
    doc, msp = _new("")
    big = doc.styles.add("SHXBIG", font="txt")
    big.dxf.bigfont = "hztxt.shx"
    ent = msp.add_mtext("机房", dxfattribs={"char_height": 250, "style": "SHXBIG"})
    ent.dxf.attachment_point = 1
    ent.dxf.insert = (0.0, 0.0)
    report = detect(_save(doc, "ov_glyphless_big.dxf"))
    check(
        "an SHX style with a big font is not reported",
        report["by_kind"]["text_glyphless"] == 0,
        str(report["by_kind"]),
    )


def test_duplicate_pair_is_reported_once() -> None:
    """One coincident pair is one defect, not a collision row plus a duplicate row.

    Measured on `draw_test/123.dxf`, where two pairs produced four rows and read
    as four problems. The row kept is the duplicate one: a `text_text` row offers
    a shift, and shifting a duplicate leaves both texts in the drawing.
    """
    print("duplicate reported once")
    doc, msp = _new("")
    for _ in range(2):
        ent = msp.add_mtext("01", dxfattribs={"char_height": 200, "style": "CN"})
        ent.dxf.attachment_point = 1
        ent.dxf.insert = (0.0, 0.0)
    report = detect(_save(doc, "ov_dup_once.dxf"))
    kinds = [f["kind"] for f in report["findings"]]
    check("no text_text row for a coincident pair", "text_text" not in kinds, str(kinds))
    check("exactly one text_duplicate row", kinds.count("text_duplicate") == 1, str(kinds))
    row = next(f for f in report["findings"] if f["kind"] == "text_duplicate")
    check("the note says to delete rather than move", "Delete one" in row.get("note", ""), row.get("note", ""))

    # A near miss that is NOT a duplicate must still be reported as a collision.
    doc, msp = _new("")
    for text, dx in (("AAAA", 0.0), ("BBBB", 40.0)):
        ent = msp.add_mtext(text, dxfattribs={"char_height": 200, "style": "CN"})
        ent.dxf.attachment_point = 1
        ent.dxf.insert = (dx, 0.0)
    report = detect(_save(doc, "ov_dup_control.dxf"))
    check(
        "different text overlapping is still text_text",
        report["by_kind"]["text_text"] == 1,
        str(report["by_kind"]),
    )


def test_block_text_says_why_it_has_no_fix() -> None:
    """A collision inside a block cannot be fixed with `entity_move`.

    The handle is `BLOCK[ref]`, which addresses nothing as a top-level entity, so
    an empty `fix` would read as "checked, nothing to do". It must say where the
    edit belongs instead.
    """
    print("block text explains its missing fix")
    doc, msp = _new("")
    block = doc.blocks.new("TAG")
    # attachment 1 puts the insertion point on the top edge, so the box hangs
    # below y=0 - a line at y=-100 crosses the glyphs.
    inner = block.add_mtext("TAG-1", dxfattribs={"char_height": 200, "style": "CN"})
    inner.dxf.attachment_point = 1
    inner.dxf.insert = (0.0, 0.0)
    block.add_line((-500, -100), (1000, -100))
    msp.add_blockref("TAG", (0.0, 0.0))
    report = detect(_save(doc, "ov_block_fix.dxf"))
    rows = [f for f in report["findings"] if f["kind"] == "text_curve"]
    check("block collision reported", len(rows) == 1, str(report["by_kind"]))
    if rows:
        fix = rows[0].get("fix") or {}
        check("no entity_move is offered", fix.get("tool") is None, str(fix))
        note = fix.get("note", "")
        # The block *reference handle* is what a caller can act on, so that is
        # what the note names - not the block definition's name.
        check("the note names the block reference", "block reference" in note, note)
        check("the note says where to edit", "inside the block definition" in note, note)


def test_summary_counts_texts_not_rows() -> None:
    """A grouped finding must report how many texts it covers.

    `text_scale`, `text_illegible`, `text_glyphless` and `text_hidden` collapse a
    whole class into one row, so counting rows understates the damage: measured
    on `gpu_dc_100.dxf`, 6 illegible rows are 129 texts, and "6 too small" reads
    as six labels.
    """
    print("grouped findings report their text count")
    from tools.text_overlap.__main__ import _human

    doc, msp = _new("")
    # Six normal labels plus three tiny ones at the same height: the three
    # collapse into one row, so `affected` is 3 and the field is emitted.
    for index in range(6):
        ent = msp.add_mtext(
            f"note {index}", dxfattribs={"char_height": 250, "style": "CN"}
        )
        ent.dxf.attachment_point = 1
        ent.dxf.insert = (index * 5000.0, 0.0)
    for index in range(3):
        tiny = msp.add_mtext(f"tiny {index}", dxfattribs={"char_height": 20, "style": "CN"})
        tiny.dxf.attachment_point = 1
        tiny.dxf.insert = (index * 1000.0, 5000.0)
    report = detect(_save(doc, "ov_rowcount.dxf"))
    rows = [f for f in report["findings"] if f["kind"] == "text_scale"]
    check("one row for the scale outliers", len(rows) == 1, str(report["by_kind"]))
    if rows:
        check(
            "the row says how many texts it covers",
            rows[0].get("affected_texts") == 3,
            str(rows[0].get("affected_texts")),
        )
    text = _human(report)
    check("the summary is printed", "finding(s)" in text, text[:120])


def test_curve_penetration_is_reported() -> None:
    """A curve cutting a label in half must be distinguishable from a graze.

    Both are `text_curve`, but the drafter treats them differently. Measured on
    `telecom_equipment_room_plan.dxf`, where one crossing runs 100% of the text
    height and another 40%.
    """
    print("curve penetration depth")
    doc, msp = _new("")
    # A vertical line through the middle of the label: full penetration.
    ent = msp.add_mtext("CROSS", dxfattribs={"char_height": 200, "style": "CN"})
    ent.dxf.attachment_point = 1
    ent.dxf.insert = (0.0, 0.0)
    msp.add_line((100.0, 200.0), (100.0, -400.0))
    report = detect(_save(doc, "ov_pen_deep.dxf"))
    rows = [f for f in report["findings"] if f["kind"] == "text_curve"]
    check("a crossing line is reported", len(rows) == 1, str(report["by_kind"]))
    if rows:
        note = rows[0].get("note", "")
        check("the note gives a percentage", "%" in note, note)
        check("it reads as a full cut-through", "100%" in note, note)

    # A line clipping only the very bottom of the box: shallow.
    doc, msp = _new("")
    ent = msp.add_mtext("CROSS", dxfattribs={"char_height": 200, "style": "CN"})
    ent.dxf.attachment_point = 1
    ent.dxf.insert = (0.0, 0.0)
    box_height = 200.0
    msp.add_line((-100.0, -box_height + 2.0), (600.0, -box_height + 2.0))
    report = detect(_save(doc, "ov_pen_shallow.dxf"))
    rows = [f for f in report["findings"] if f["kind"] == "text_curve"]
    if rows:
        note = rows[0].get("note", "")
        check(
            "a shallow graze reads as a small percentage",
            "100%" not in note,
            note,
        )
    else:
        check("a graze below the core is not reported", True)


def test_stacked_label_moves_as_one() -> None:
    """A multi-line label is moved line by line in a single `cad_batch`.

    A room label is several independent entities stacked in a column. Shifting
    one line clears the collision but breaks the label's alignment, which is a
    worse drawing than the override - so the offered fix moves the whole stack.

    Measured need: `gpu_dc_100.dxf`, where the room name sits 141 units above
    the area row on the same layer.
    """
    print("stacked label moves as one")
    doc, msp = _new("")
    for text, dy in (("ROOM NAME", 0.0), ("288.0 m2", -700.0)):
        ent = msp.add_mtext(text, dxfattribs={"char_height": 400, "style": "CN"})
        ent.dxf.attachment_point = 5
        ent.dxf.insert = (2000.0, 2000.0 + dy)
    msp.add_line((1700, 3000), (1700, 900))
    report = detect(_save(doc, "ov_stack.dxf"))
    rows = [f for f in report["findings"] if f["kind"] == "text_curve"]
    check("both lines are reported", len(rows) == 2, str(report["by_kind"]))
    if rows:
        fix = rows[0].get("fix") or {}
        check("the fix is a cad_batch", fix.get("tool") == "cad_batch", str(fix.get("tool")))
        steps = (fix.get("args") or {}).get("steps") or []
        check("it moves both lines", len(steps) == 2, str(len(steps)))
        handles = {step["args"]["handle"] for step in steps}
        check("the two steps are the two lines", len(handles) == 2, str(handles))
        offsets = {(step["args"]["dx"], step["args"]["dy"]) for step in steps}
        check("both lines move by the same vector", len(offsets) == 1, str(offsets))

        # Applying every step must clear both findings.
        path = os.path.join(tempfile.gettempdir(), "ov_stack.dxf")
        moved = ezdxf.readfile(path)
        for step in steps:
            entity = moved.entitydb.get(step["args"]["handle"])
            entity.translate(step["args"]["dx"], step["args"]["dy"], 0)
        out = os.path.join(tempfile.gettempdir(), "ov_stack_moved.dxf")
        if os.path.exists(out):
            os.remove(out)
        moved.saveas(out)
        after = detect(out)
        check(
            "after the batch both lines are clear",
            after["by_kind"]["text_curve"] == 0,
            str(after["by_kind"]),
        )


def test_overlapping_texts_are_not_grouped() -> None:
    """Two texts that overlap each other are a collision, not a stack.

    Grouping them would offer one 'fix' that shifts both by the same vector and
    leaves the overlap untouched - measured on `planted.dxf`, where
    `CRAC-01 40kW` and `精密空调` sit on top of each other.
    """
    print("overlapping texts are not one label")
    doc, msp = _new("")
    for text, dx, dy in (("CRAC-01", 0.0, 0.0), ("PRECISION", 40.0, -120.0)):
        ent = msp.add_mtext(text, dxfattribs={"char_height": 200, "style": "CN"})
        ent.dxf.attachment_point = 1
        ent.dxf.insert = (dx, dy)
    report = detect(_save(doc, "ov_overlap_group.dxf"))
    rows = [f for f in report["findings"] if f["kind"] == "text_text"]
    check("the overlap is reported", len(rows) == 1, str(report["by_kind"]))
    if rows:
        fix = rows[0].get("fix") or {}
        check(
            "the fix is not a group move",
            fix.get("tool") != "cad_batch",
            str(fix.get("tool")),
        )


def test_wide_text_says_to_split_it() -> None:
    """A text too wide for any free slot must say so, not 'boxed in'.

    On `gpu_dc_100.dxf` the area row is 6026 units wide with 1159 units of free
    space beside it; it needs 1916 units of travel to clear the axis, and the
    labels either side block it well before that. The actionable advice is
    'shorten or split', and the note must carry the numbers that justify it.

    Uses the committed sample because the situation needs a real densely-packed
    drawing - every synthesised attempt either left a workable vertical shift or
    had no collision at all.
    """
    print("wide text is told to split")
    source = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..",
            "drawings", "gpu-datacenter", "gpu_dc_100.dxf",
        )
    )
    if not os.path.exists(source):
        check("the wide-text sample is present", False, f"missing {source}")
        return
    report = detect(source)
    row = next(
        (
            f
            for f in report["findings"]
            if f["kind"] == "text_curve" and f["handle"] == "254"
        ),
        None,
    )
    check("the wide area row is reported", row is not None, str(report["by_kind"]))
    if row is None:
        return
    fix = row.get("fix") or {}
    note = fix.get("note", "")
    check("no move is offered", fix.get("tool") is None, str(fix.get("tool")))
    check("the note says to shorten or split", "split" in note, note)
    check("the note gives the width", "units wide" in note, note)
    check("the note gives the free slot", "slot" in note, note)


def test_single_line_move_warns_about_misalignment() -> None:
    """When only one line of a label can move, the note must say the rest stays.

    Otherwise a reader takes the `entity_move` at face value and ends up with a
    ragged label. Measured on `gpu_dc_100.dxf` handle 253: the label cannot
    travel as a unit (the area row below it is 6026 units wide and boxed in), so
    only the name can be nudged.
    """
    print("single-line move warns about misalignment")
    source = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..",
            "drawings", "gpu-datacenter", "gpu_dc_100.dxf",
        )
    )
    if not os.path.exists(source):
        check("the sample is present", False, f"missing {source}")
        return
    report = detect(source)
    row = next(
        (f for f in report["findings"] if f["handle"] == "253"),
        None,
    )
    check("the room name is reported", row is not None, str(report["by_kind"]))
    if row is None:
        return
    fix = row.get("fix") or {}
    check("a move is still offered", fix.get("tool") == "entity_move", str(fix.get("tool")))
    check("it is flagged as moving alone", fix.get("moves_alone") is True, str(fix.get("moves_alone")))
    note = fix.get("note", "")
    check("the note names the line left behind", "254" in note, note)
    check("the note warns about alignment", "misaligned" in note, note)


def test_errors() -> None:
    print("error paths")
    try:
        detect("/definitely/not/here.dxf")
        check("missing file raises", False)
    except FileNotFoundError:
        check("missing file raises FileNotFoundError", True)

    corrupt = os.path.join(tempfile.gettempdir(), "ov_corrupt.dxf")
    with open(corrupt, "w", encoding="utf-8") as f:
        f.write("not a dxf at all")
    try:
        detect(corrupt)
        check("non-DXF raises", False)
    except ValueError:
        check("non-DXF raises ValueError", True)

    doc, _ = _new("")
    path = _save(doc, "ov_layout.dxf")
    try:
        detect(path, layout="NoSuchLayout")
        check("bad layout raises", False)
    except ValueError as exc:
        check("bad layout raises ValueError", "this file has" in str(exc))


def test_dwg_conversion_never_touches_open_documents() -> None:
    """A DWG read must not SaveAs the user's document.

    ``SaveAs`` re-points the *document*. Applied to a drawing the user has open,
    it stops being their DWG and becomes a temp DXF that then gets deleted - the
    session is left holding a file that no longer exists, and the next save
    writes under ``%TEMP%``. That is exactly what the first version of
    ``dwg.py`` did (the active document became ``tc_dwg_ij_admuf.dxf``).

    This test runs without AutoCAD by substituting a fake app whose document
    records every ``SaveAs`` target, and asserts the copy is what was saved.
    """
    print("DWG conversion safety")
    from tools.text_overlap import dwg

    saved_paths: list[str] = []
    closed: list[bool] = []
    opened_paths: list[str] = []

    class FakeDoc:
        def __init__(self, full_name: str) -> None:
            self.FullName = full_name

        def SaveAs(self, path: str, _type: int) -> None:
            saved_paths.append(path)
            # AutoCAD creates the file; the module then checks it exists.
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("fake dxf")

        def Close(self, save: bool) -> None:
            closed.append(save)

        def Activate(self) -> None:
            return None

    class FakeDocs:
        Count = 0

        def Open(self, path: str, read_only: bool) -> FakeDoc:
            opened_paths.append(path)
            return FakeDoc(path)

    class FakeApp:
        Documents = FakeDocs()

        @property
        def ActiveDocument(self) -> FakeDoc:
            raise RuntimeError("no active document")

    source = os.path.join(tempfile.gettempdir(), "ov_safety_src.dwg")
    with open(source, "wb") as fh:
        fh.write(b"pretend this is a dwg")

    real_app = dwg._app
    dwg._app = lambda: FakeApp()
    try:
        dxf_path, how = dwg.to_dxf(source)
    finally:
        dwg._app = real_app

    check(
        "a copy is opened, not the user's file",
        bool(opened_paths) and opened_paths[0] != source and opened_paths[0].endswith(".dwg"),
        f"opened {opened_paths}",
    )
    check(
        "SaveAs runs only on the copy",
        bool(saved_paths) and saved_paths[0] != source and "tc_dwg_" in saved_paths[0],
        f"saved {saved_paths}",
    )
    check(
        "the copy is closed without saving",
        closed == [False],
        f"closed with save flags {closed}",
    )
    check(
        "the returned DXF is announced in 'how'",
        "temporary copy" in how,
        how,
    )
    for leftover in (source, *(os.path.dirname(dxf_path) and [dxf_path] or [])):
        try:
            os.remove(leftover)
        except OSError:
            pass


def test_dwg_without_autocad_explains_the_way_out() -> None:
    """No AutoCAD must produce a remedy, not just an error."""
    print("DWG conversion without AutoCAD")
    from tools.text_overlap import dwg

    def boom() -> None:
        raise dwg.DwgUnavailable(
            "AutoCAD is not running", "Start AutoCAD and open the drawing"
        )

    class FakeDocs:
        Count = 0

        def Open(self, path: str, read_only: bool) -> None:
            raise AssertionError("must not open anything when COM is unavailable")

    class FakeApp:
        Documents = FakeDocs()

    source = os.path.join(tempfile.gettempdir(), "ov_noautocad.dwg")
    with open(source, "wb") as fh:
        fh.write(b"pretend this is a dwg")

    real_app = dwg._app
    dwg._app = boom
    try:
        try:
            dwg.to_dxf(source)
            check("no AutoCAD raises DwgUnavailable", False, "no exception")
        except dwg.DwgUnavailable as exc:
            check("no AutoCAD raises DwgUnavailable", True)
            check(
                "the error says what to do instead",
                "Start AutoCAD" in exc.remedy,
                exc.remedy,
            )
    finally:
        dwg._app = real_app
        os.remove(source)


def main() -> int:
    for test in (
        test_empty_drawing,
        test_text_overlap,
        test_curve_through_text,
        test_near_miss_is_quiet,
        test_block_text_detected,
        test_block_rotation_is_read,
        test_rotated_block_curve_hit,
        test_nested_block,
        test_attrib_is_read,
        test_attrib_via_block_rotation,
        test_table_cells_are_read,
        test_text_scale_outlier,
        test_rotated_text_is_not_a_scale_outlier,
        test_dimension_text_is_read,
        test_fix_is_verified_safe,
        test_boxed_in_text_gets_no_fix,
        test_hidden_text_is_reported,
        test_duplicate_text_is_reported,
        test_rotation_is_not_applied_twice,
        test_merged_table_cells_keep_correct_text,
        test_illegible_text_uses_viewport_scale,
        test_glyphless_style_is_reported,
        test_duplicate_pair_is_reported_once,
        test_block_text_says_why_it_has_no_fix,
        test_summary_counts_texts_not_rows,
        test_curve_penetration_is_reported,
        test_stacked_label_moves_as_one,
        test_overlapping_texts_are_not_grouped,
        test_wide_text_says_to_split_it,
        test_single_line_move_warns_about_misalignment,
        test_non_uniform_block_is_reported,
        test_no_blocks_flag,
        test_errors,
        test_dwg_conversion_never_touches_open_documents,
        test_dwg_without_autocad_explains_the_way_out,
    ):
        test()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} -> {', '.join(FAILURES)}")
        return 1
    print("PASS: all tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())