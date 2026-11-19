"""Prove what Ctrl+S does on this exact DXF now that AutoCAD is quiescent.

Calls Document.Save() - byte for byte the call Ctrl+S makes - on the live
document. A failure writes nothing, so this cannot damage the drawing.

If it answers 0x80210063 the DXF defect is confirmed as the reason the user
cannot save from the AutoCAD UI, independent of the earlier busy state.
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pythoncom
import win32com.client

TARGET = "multi_save.dxf"


def hr_of(exc):
    if getattr(exc, "args", None) and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def main() -> int:
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")

        state = app.GetAcadState()
        print(f"GetAcadState.IsQuiescent = {state.IsQuiescent}")

        docs = app.Documents
        print(f"Documents.Count = {docs.Count}")
        target_doc = None
        for i in range(docs.Count):
            d = docs.Item(i)
            print(f"  [{i}] {d.Name!r}")
            if d.Name == TARGET:
                target_doc = d
        if target_doc is None:
            print(f"{TARGET} is not open; nothing to test.")
            return 1

        print("=" * 80)
        print(f"TARGET: {target_doc.FullName!r}")
        print(f"  Saved   = {target_doc.Saved}")
        print(f"  ReadOnly= {target_doc.ReadOnly}")
        print("=" * 80)
        print("CALLING Document.Save()  <- exactly what Ctrl+S runs")
        try:
            target_doc.Save()
            print("  RESULT: Save() SUCCEEDED")
            print(f"  Saved now = {target_doc.Saved}")
            return 0
        except Exception as exc:
            hr = hr_of(exc)
            info = getattr(exc, "excepinfo", None)
            print("  RESULT: Save() FAILED")
            print(f"    hresult : {hr}")
            if hr is not None:
                print(f"    unsigned: {hr & 0xFFFFFFFF:#010x}")
            print(f"    strerror: {getattr(exc, 'strerror', None)!r}")
            print(f"    excepinfo: {info!r}")
            if info:
                for idx, part in enumerate(info):
                    print(f"      excepinfo[{idx}] = {part!r}")
            return 2
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())