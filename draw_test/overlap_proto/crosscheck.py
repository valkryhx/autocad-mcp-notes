"""Cross-check ``tools.text_overlap.textbox`` against AutoCAD's own GetBoundingBox.

Builds a scratch drawing of known texts through COM, reads each one's box from
AutoCAD, writes the same drawing out as DXF, then measures the DXF entities
with the shipped module and reports the per-entity error.

    .venv/Scripts/python.exe crosscheck.py
"""

from __future__ import annotations

import array
import os
import sys

import ezdxf
from ezdxf.tools.text_size import get_font_name
import pythoncom
from win32com.client import VARIANT

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from tools.text_overlap import calibrate, measure_text  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify")
DXF = os.path.join(OUT_DIR, "probe_out.dxf")


def _vec(*values):
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, array.array("d", values))


def build():
    import win32com.client as wc

    app = wc.GetActiveObject("AutoCAD.Application")
    doc = app.Documents.Add()
    msp = doc.ModelSpace
    # The font must be given as a full path: a bare "simhei.ttf" raises a
    # file-handler error and a bare "simhei" leaves the style with no font at
    # all (so ezdxf falls back to a default face and every CJK width is wrong).
    styles = {
        "CN": r"C:\Windows\Fonts\simhei.ttf",
        "SUN": r"C:\Windows\Fonts\simsun.ttc",
        "YAHEI": r"C:\Windows\Fonts\msyh.ttc",
    }
    for name, font in styles.items():
        try:
            styles_ = doc.TextStyles.Add(name)
            styles_.fontFile = font
        except Exception:
            pass

    # (text, char height, style, rotation degrees)
    cases = [
        ("1", 400, "CN", 0),
        ("08", 160, "CN", 0),
        ("ABC", 400, "CN", 0),
        ("国", 400, "CN", 0),
        ("通信机房", 400, "CN", 0),
        ("column label", 250, "CN", 90),
        ("Design notes", 300, "SUN", 0),
        ("设备清单", 300, "SUN", 0),
        ("Room A", 350, "YAHEI", 0),
        ("line one\\Pline two", 265, "CN", 0),
        ("line one\\Pline two\\Pthree", 200, "CN", 0),
    ]
    handles = []
    for i, (text, height, style, rotation) in enumerate(cases):
        # Width argument 0 = no wrapping column, which is what group 41 = 0
        # means in the DXF too. A non-zero value makes AutoCAD box the text at
        # that column width, not at the text's own width.
        mtext = msp.AddMText(_vec(i * 20000.0, 0, 0), 0.0, text)
        try:
            mtext.StyleName = style
        except Exception:
            pass
        mtext.Height = height
        mtext.AttachmentPoint = 1
        if rotation:
            mtext.Rotation = rotation * 3.141592653589793 / 180.0
        handles.append((mtext, cases[i]))

    boxes = {}
    for mtext, _ in handles:
        lo, hi = mtext.GetBoundingBox()
        boxes[mtext.Handle] = (
            min(lo[0], hi[0]),
            min(lo[1], hi[1]),
            max(lo[0], hi[0]),
            max(lo[1], hi[1]),
        )

    # SaveAs without an explicit AcSaveAsType appends .dwg to a .dxf name;
    # 61 is ac2013_dxf, which keeps the extension given.
    if os.path.exists(DXF):
        os.remove(DXF)
    doc.SaveAs(DXF, 61)
    doc.Close(False)
    if not os.path.exists(DXF):
        raise FileNotFoundError("AutoCAD wrote no DXF for " + DXF)
    return boxes, DXF


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    boxes, path = build()
    print("AutoCAD wrote", path)
    doc = ezdxf.readfile(path)
    entities = {e.dxf.handle: e for e in doc.modelspace()}

    header = f"{'text':22} {'ch':>5} {'rot':>4}  {'acad w':>9} {'mine w':>9} {'w%':>7}  {'acad h':>8} {'mine h':>8} {'h%':>7}"
    print(header)
    print("-" * len(header))
    worst = 0.0
    rows = 0
    for handle, (truth, (text, height, style, rotation)) in _paired(boxes, entities):
        mine = measure_text(entities[handle], calibrate(get_font_name(entities[handle])))
        aw, ah = truth[2] - truth[0], truth[3] - truth[1]
        if mine is None:
            print(f"{text[:22]:22} {height:5} {rotation:4}  NO BOX")
            continue
        mw, mh = mine[2] - mine[0], mine[3] - mine[1]
        ew = abs(mw - aw) / aw * 100 if aw else 0.0
        eh = abs(mh - ah) / ah * 100 if ah else 0.0
        worst = max(worst, ew, eh)
        rows += 1
        label = text.replace("\\P", "|")[:22]
        print(
            f"{label:22} {height:5} {rotation:4}  {aw:9.1f} {mw:9.1f} {ew:7.2f}  {ah:8.1f} {mh:8.1f} {eh:7.2f}"
        )
    print(f"\n{rows} texts, worst error {worst:.2f}%")


def _paired(boxes, entities):
    """Pair AutoCAD boxes with DXF entities: handles survive the DXF write."""
    for handle, box in boxes.items():
        if handle in entities:
            yield handle, (box, _describe(entities[handle]))


def _describe(entity):
    rotation = float(entity.dxf.get("rotation", 0.0) or 0.0)
    return (entity.plain_text(), float(entity.dxf.char_height), entity.dxf.style, rotation)


if __name__ == "__main__":
    main()