"""Sensitivity test: plant known collisions, then require each one is found.

Each case is planted at a known location with a known handle, so a miss and a
false positive are both visible. The drawing is otherwise identical to
``clean.py``'s.

    .venv/Scripts/python.exe planted.py
"""

from __future__ import annotations

import os
import sys

import ezdxf

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tools.text_overlap import detect  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify", "planted.dxf")


def build() -> tuple[str, dict[str, str]]:
    doc = ezdxf.new("R2010", setup=True)
    doc.styles.add("CN", font="simhei.ttf")
    msp = doc.modelspace()
    planted = {}

    def label(text, x, y, h=200, attach=1):
        m = msp.add_mtext(text, dxfattribs={"char_height": h, "style": "CN"})
        m.dxf.attachment_point = attach
        m.dxf.insert = (x, y)
        return m.dxf.handle

    # 1. two labels on top of each other
    planted["two_labels_a"] = label("CRAC-01 40kW", 0, 0)
    planted["two_labels_b"] = label("精密空调", 0, -40)

    # 2. a line straight through a label
    #    attach=1 hangs the box BELOW its insert point, so the label at y=0
    #    occupies y=-250..0 and the crossing line must sit inside that band.
    planted["line_through"] = label("冷通道封闭", 5000, 0, h=250)
    msp.add_line((4500, -120), (7000, -120))

    # 3. a vertical wall through a label (the real defect seen in gpu_dc_100)
    planted["wall_through"] = label("UPS-2", 12000, 0, h=250)
    msp.add_line((12300, -1000), (12300, 1000))

    # 4. a long note crossed by a short axis label
    planted["long_note"] = label("1. 本图为机房平面布置图，比例 1:100，尺寸单位 mm。", 18000, 0, h=250)
    planted["short_over"] = label("A", 21000, 100, h=400)

    # 5. a rotated vertical label crossed by a horizontal line
    v = msp.add_mtext("竖向标签", dxfattribs={"char_height": 250, "style": "CN"})
    v.dxf.attachment_point = 5
    v.dxf.insert = (26000, 0)
    v.dxf.rotation = 90.0
    msp.add_line((25800, 400), (26200, 400))
    planted["rotated"] = v.dxf.handle

    # 6. a control: a label with clear space all round (must NOT be reported)
    planted["clean_control"] = label("隔离标签", 30000, 0, h=250)
    msp.add_line((29500, 3000), (30500, 3000))  # far above

    if os.path.exists(OUT):
        os.remove(OUT)
    doc.saveas(OUT)
    return OUT, planted


def main() -> int:
    path, planted = build()
    report = detect(path)
    found = report["findings"]
    print(f"planted.dxf: {report['texts_measured']} texts, {report['curves']} curves")
    print(f"  findings: {report['by_kind']}")

    by_handle = {}
    for f in found:
        by_handle.setdefault(f["handle"], []).append(f)
        if "with" in f:
            by_handle.setdefault(f["with"]["handle"], []).append(f)

    expected = [
        ("two_labels_a", "text_text"),
        ("two_labels_b", "text_text"),
        ("line_through", "text_curve"),
        ("wall_through", "text_curve"),
        ("long_note", "text_text"),
        ("rotated", "text_curve"),
    ]
    failures = []
    for name, kind in expected:
        handle = planted[name]
        hits = [f for f in by_handle.get(handle, []) if f["kind"] == kind]
        status = "FOUND" if hits else "MISSED"
        if not hits:
            failures.append(name)
        print(f"  {status:6} {name:16} ({kind}) handle={handle}")

    if by_handle.get(planted["clean_control"]):
        failures.append("clean_control (false positive)")
        print("  FALSE+ clean_control was reported")
    else:
        print("  OK     clean_control   (not reported, as intended)")

    print()
    if failures:
        print("FAILED:", ", ".join(failures))
        return 1
    print("PASS: every planted collision found, control clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())