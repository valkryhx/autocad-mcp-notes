"""The workaround's lifetime: SaveAs to a new name, then when does Save() break?

Matrix C5/C8 showed SaveAs(new path) works and the document can then Save().
The practical question for a drafter is: does that last? Two follow-ups:

  D1  reopen the file C5 produced, edit, Save()   -> does the defect come back?
  D2  SaveAs again to yet another new name, then Save()  -> does that work too?

Answers decide whether "SaveAs to a new name" is a one-off rescue or a repeated
ritual.
"""
from __future__ import annotations

import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pythoncom
import win32com.client

SCRATCH = r"D:\git_codes\test_Autocad_MCP\draw_test\_save_matrix"
SRC = r"D:\git_codes\test_Autocad_MCP\good_examples\20261119_gpu_datacenter_plan\20261119.dxf"
AC2013_DXF = 61


def hr_of(exc):
    a = getattr(exc, "args", None)
    return a[0] if a and isinstance(a[0], int) else None


def excepinfo_of(exc):
    info = getattr(exc, "excepinfo", None)
    return tuple(info) if info else None


def add_circle(doc, r=7.0):
    import array
    from win32com.client import VARIANT
    doc.ModelSpace.AddCircle(
        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                array.array("d", [0.0, 0.0, 0.0])),
        r,
    )


def attempt(label, fn):
    try:
        detail = fn()
        print(f"  OK    {label}")
        if detail:
            print(f"        {detail}")
        return True
    except Exception as exc:
        hr = hr_of(exc)
        print(f"  FAIL  {label}")
        print(f"        hresult : {hr} ({hr & 0xFFFFFFFF:#010x})" if hr else "        ?")
        print(f"        excepinfo: {excepinfo_of(exc)!r}")
        return False


def main() -> int:
    os.makedirs(SCRATCH, exist_ok=True)
    p1 = os.path.join(SCRATCH, "d_rescue_1.dxf")
    p2 = os.path.join(SCRATCH, "d_rescue_2.dxf")
    for p in (p1, p2):
        if os.path.exists(p):
            os.remove(p)
    shutil.copy2(SRC, p1)

    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        print(f"IsQuiescent = {app.GetAcadState().IsQuiescent}")
        print("=" * 84)
        print("D0  the case we already know fails: Open(existing DXF) -> edit -> Save()")
        print("=" * 84)
        doc = app.Documents.Open(p1, False)
        add_circle(doc)
        attempt("Save() on a DXF opened from disk", lambda: doc.Save())

        print("=" * 84)
        print("D1  rescue: SaveAs to a NEW name, then edit, then Save()")
        print("=" * 84)
        attempt(f"SaveAs({os.path.basename(p2)})", lambda: doc.SaveAs(p2, AC2013_DXF))
        add_circle(doc, 9.0)
        attempt("Save() after being re-pointed to the new file", lambda: doc.Save())
        attempt("Save() again (second time on the re-pointed doc)", lambda: doc.Save())
        doc.Close(False)

        print("=" * 84)
        print("D2  reopen that rescued file, edit, Save() - does the defect return?")
        print("=" * 84)
        doc = app.Documents.Open(p2, False)
        add_circle(doc, 11.0)
        ok = attempt("Save() on the reopened rescued file", lambda: doc.Save())

        print("=" * 84)
        print("D3  rescue it again to yet another new name")
        print("=" * 84)
        p3 = os.path.join(SCRATCH, "d_rescue_3.dxf")
        if os.path.exists(p3):
            os.remove(p3)
        attempt(f"SaveAs({os.path.basename(p3)})", lambda: doc.SaveAs(p3, AC2013_DXF))
        add_circle(doc, 13.0)
        attempt("Save() after second rescue", lambda: doc.Save())
        doc.Close(False)

        print("=" * 84)
        print("VERDICT")
        print("=" * 84)
        if not ok:
            print("  The rescue is only good for the session it was made in.")
            print("  Every reopen of a DXF from disk needs a fresh SaveAs.")
        else:
            print("  Unexpected: Save() worked on a reopened rescued file.")
        return 0
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())