"""False-positive test: a drawing built to be clean must report zero findings.

Every text is placed with a clear gap from its neighbours and from all
geometry, so any finding here is a false positive.

    .venv/Scripts/python.exe clean.py
"""

from __future__ import annotations

import os
import sys

import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tools.text_overlap import detect  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify", "clean.dxf")


def build() -> str:
    doc = ezdxf.new("R2010", setup=True)
    doc.styles.add("CN", font="simhei.ttf")
    msp = doc.modelspace()

    # A 6 x 4 grid of cells, 4000 apart. Each cell holds a box outline and a
    # label well inside it; nothing is closer than 600 units to anything else.
    for row in range(4):
        for col in range(6):
            x, y = col * 4000.0, row * 4000.0
            msp.add_lwpolyline(
                [(x, y), (x + 3000, y), (x + 3000, y + 3000), (x, y + 3000)],
                close=True,
            )
            label = "Rack" if col % 2 else "机柜"
            text = msp.add_mtext(label, dxfattribs={"char_height": 200, "style": "CN"})
            text.dxf.attachment_point = 5
            text.dxf.insert = (x + 1500, y + 1500)

    # Isolated notes with clear space around them.
    for i, note in enumerate(("Design notes", "尺寸单位 mm", "Scale 1:100")):
        text = msp.add_mtext(note, dxfattribs={"char_height": 250, "style": "CN"})
        text.dxf.attachment_point = 1
        text.dxf.insert = (30000.0, 6000.0 - i * 2000.0)

    if os.path.exists(OUT):
        os.remove(OUT)
    doc.saveas(OUT)
    return OUT


def main():
    path = build()
    report = detect(path)
    print("clean.dxf: ", report["texts_measured"], "texts measured")
    print("  by_kind:", report["by_kind"])
    findings = report["findings"]
    if not findings:
        print("  PASS: zero findings on a clean drawing")
        return 0
    print(f"  FAIL: {len(findings)} false positive(s)")
    for f in findings:
        print("   ", f)
    return 1


if __name__ == "__main__":
    sys.exit(main())