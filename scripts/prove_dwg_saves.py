"""Contrast test: does Save() work on a DWG in the same AutoCAD session?

Copies the reference DWG to a scratch file, opens the COPY (never the
original - SaveAs/Save repoints the document, see
docs/20261120-dwg-saveas-repoint.md), makes one harmless edit, calls Save(),
and closes with Close(False). Proves DWG is unaffected by 0x80210063.

The original file's hash is checked before and after to prove it was untouched.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pythoncom
import win32com.client

SRC = r"D:\git_codes\test_Autocad_MCP\good_examples\20261119_gpu_datacenter_plan\20261119.dwg"
SCRATCH_DIR = r"D:\git_codes\test_Autocad_MCP\draw_test"
COPY = os.path.join(SCRATCH_DIR, "dwg_save_contrast.dwg")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hr_of(exc):
    if getattr(exc, "args", None) and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def main() -> int:
    if not os.path.exists(SRC):
        print(f"missing source: {SRC}")
        return 1

    src_hash_before = sha256(SRC)
    print(f"source sha256 (before) = {src_hash_before}")

    if os.path.exists(COPY):
        os.remove(COPY)
    shutil.copy2(SRC, COPY)
    print(f"copied to {COPY}  ({os.path.getsize(COPY)} B)")

    pythoncom.CoInitialize()
    doc = None
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        print(f"IsQuiescent = {app.GetAcadState().IsQuiescent}")

        # NOTE: the second argument of Documents.Open is ReadOnly. Passing True
        # opens the document read-only, and Save() then fails with the very same
        # 0x80210063 "保存文档时出错" as the DXF defect - a trap worth avoiding.
        doc = app.Documents.Open(COPY, False)
        print(f"opened: Name={doc.Name!r}")
        print(f"        FullName={doc.FullName!r}")
        print(f"        ReadOnly={doc.ReadOnly}")
        assert os.path.normcase(doc.FullName) == os.path.normcase(COPY), (
            "refusing to operate on a document that is not the copy")

        before = doc.ModelSpace.Count
        # Harmless edit: one tiny circle far from any geometry.
        import array
        from win32com.client import VARIANT

        doc.ModelSpace.AddCircle(
            VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, array.array("d", [0.0, 0.0, 0.0])),
            1.0,
        )
        after = doc.ModelSpace.Count
        print(f"entities: {before} -> {after}")

        print("=" * 76)
        print("CALLING Doc.Save()  <- exactly what Ctrl+S runs")
        print("=" * 76)
        try:
            doc.Save()
            print("  RESULT: Save() SUCCEEDED")
            print(f"  Saved = {doc.Saved}")
            ok = True
        except Exception as exc:
            hr = hr_of(exc)
            print(f"  RESULT: Save() FAILED hr={hr} "
                  f"{getattr(exc, 'strerror', exc)!r}")
            print(f"  excepinfo={getattr(exc, 'excepinfo', None)!r}")
            ok = False

        return 0 if ok else 2
    finally:
        if doc is not None:
            try:
                print(f"closing copy with Close(False); FullName={doc.FullName!r}")
                doc.Close(False)
            except Exception as exc:
                print(f"  close failed: {exc}")
        pythoncom.CoUninitialize()

        src_hash_after = sha256(SRC)
        print(f"source sha256 (after)  = {src_hash_after}")
        print(f"source untouched: {src_hash_before == src_hash_after}")


if __name__ == "__main__":
    raise SystemExit(main())