"""Verify text placement at all nine MTEXT attachment points, against AutoCAD.

Builds a scratch drawing of nine labels - one per attachment point - plus one
rotated 90 degrees, asks AutoCAD for each one's ``GetBoundingBox``, writes the
drawing out as DXF, and compares ``tools.text_overlap``'s boxes with AutoCAD's.

Needs a running AutoCAD. Writes its fixtures beside itself:
``verify/anchors.dxf`` and ``verify/anchors_bb.csv``.

    .venv/Scripts/python.exe anchors.py
"""

from __future__ import annotations

import array
import os
import sys

import ezdxf
import pythoncom
from win32com.client import VARIANT, Dispatch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tools.text_overlap import calibrate, measure_text  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "verify", "anchors.dxf")
CSV = os.path.join(HERE, "verify", "anchors_bb.csv")
HEIGHT = 250.0
TEXT = "Anchor"


def vec(*values):
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, array.array("d", values))


def build() -> dict:
    app = Dispatch("AutoCAD.Application")
    doc = app.Documents.Add()
    msp = doc.ModelSpace
    try:
        doc.TextStyles.Add("CN").fontFile = r"C:\Windows\Fonts\simhei.ttf"
    except Exception:
        pass

    made = []
    for attachment in range(1, 10):
        entity = msp.AddMText(vec(attachment * 5000.0, 0, 0), 0.0, TEXT)
        entity.StyleName = "CN"
        entity.Height = HEIGHT
        entity.AttachmentPoint = attachment
        made.append((attachment, entity))

    rotated = msp.AddMText(vec(0, 50000.0, 0), 0.0, TEXT)
    rotated.StyleName = "CN"
    rotated.Height = HEIGHT
    rotated.AttachmentPoint = 1
    rotated.Rotation = 1.5707963267948966
    made.append(("rot90", rotated))

    truth = {}
    for key, entity in made:
        lo, hi = entity.GetBoundingBox()
        truth[entity.Handle] = (
            key,
            (min(lo[0], hi[0]), min(lo[1], hi[1]), max(lo[0], hi[0]), max(lo[1], hi[1])),
        )

    if os.path.exists(OUT):
        os.remove(OUT)
    doc.SaveAs(OUT, 61)
    doc.Close(False)

    with open(CSV, "w", encoding="utf-8") as f:
        for handle, (key, box) in truth.items():
            f.write("%s,%s,%.6f,%.6f,%.6f,%.6f\n" % (handle, key, *box))
    return truth


def main() -> int:
    print("building the probe drawing in AutoCAD ...")
    build()

    import csv

    truth = {}
    with open(CSV, encoding="utf-8") as f:
        for row in csv.reader(f):
            truth[row[0]] = tuple(map(float, row[2:6]))

    from ezdxf.tools.text_size import get_font_name

    doc = ezdxf.readfile(OUT)
    print(f"\n{'handle':8} {'acad w x h':24} {'mine w x h':24} {'drift':>8}")
    worst = 0.0
    for entity in doc.modelspace():
        handle = entity.dxf.handle
        if handle not in truth:
            continue
        box = truth[handle]
        mine = measure_text(entity, calibrate(get_font_name(entity)))
        if mine is None:
            print(f"{handle:8} NO BOX")
            continue
        drift = max(abs(mine[i] - box[i]) for i in range(4))
        worst = max(worst, drift)
        print(
            f"{handle:8} {box[2] - box[0]:9.1f} x {box[3] - box[1]:8.1f} "
            f"{mine[2] - mine[0]:9.1f} x {mine[3] - mine[1]:8.1f} {drift:8.2f}"
        )
    print(f"\nworst corner drift {worst:.2f} units on a {HEIGHT:.0f}-unit text")
    ok = worst <= HEIGHT * 0.05
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())