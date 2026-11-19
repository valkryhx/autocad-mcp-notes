"""Confirm the DWG cases in the save matrix actually wrote to disk.

ezdxf cannot read DWG, so the matrix could only report "Save() returned OK" for
C6/C7. This reads the file-level evidence instead: mtime and size must move past
the moment the case ran, and the entity count is read back through AutoCAD.

Read-only with respect to drawing content.
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pythoncom
import win32com.client

SCRATCH = r"D:\git_codes\test_Autocad_MCP\draw_test\_save_matrix"
TARGETS = [
    ("C6  Open(DWG) -> edit -> Save()", "c6_open_dwg_then_save.dwg"),
    ("C7  new -> SaveAs(DWG) -> edit -> Save()", "c7_new_dwg_saveas_then_save.dwg"),
]
DXF_TARGETS = [
    ("C1  new -> SaveAs(DXF) -> edit -> Save()", "c1_new_saveas_then_save.dxf"),
    ("C5  Open(DXF) -> edit -> SaveAs(new)", "c5_open_then_saveas_new_dst.dxf"),
    ("C8  Open(DXF) -> SaveAs(new) -> edit -> Save()", "c8_chain_dst.dxf"),
]


def main() -> int:
    print("=" * 84)
    print("ON-DISK EVIDENCE")
    print("=" * 84)
    now = time.time()
    for label, name in TARGETS + DXF_TARGETS:
        p = os.path.join(SCRATCH, name)
        if not os.path.exists(p):
            print(f"  MISSING  {name}")
            continue
        st = os.stat(p)
        age = now - st.st_mtime
        print(f"  {name}")
        print(f"    {st.st_size} B, mtime {time.strftime('%H:%M:%S', time.localtime(st.st_mtime))}"
              f"  ({age:.0f} s ago)")
        print(f"    written during the matrix run: {age < 300}")

    # Count entities in the DWGs through AutoCAD, which can read them.
    print()
    print("=" * 84)
    print("DWG ENTITY COUNTS read back through AutoCAD")
    print("=" * 84)
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        for label, name in TARGETS:
            p = os.path.join(SCRATCH, name)
            if not os.path.exists(p):
                continue
            try:
                doc = app.Documents.Open(p, True)  # True = read-only: we only read
                n = doc.ModelSpace.Count
                print(f"  {name}: {n} entities")
                doc.Close(False)
            except Exception as exc:
                print(f"  {name}: could not open ({exc})")
    finally:
        pythoncom.CoUninitialize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())