"""Run the code from the skill's references/saving-formats.md section 3.

The point is that the doc's snippets are executable, not illustrative. Each
block here is copied from the doc; if the doc's advice is wrong, this fails.

  3.4  new drawing straight to DXF
  3.5  an existing DXF you must iterate on, both the fix and the round trip
  3.6  DWG saves freely
  3.7  the three forbidden saves (asserted to be bad, not used)
"""
from __future__ import annotations

import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pythoncom
import win32com.client

SCRATCH = r"D:\git_codes\test_Autocad_MCP\draw_test\_skill_doc_check"
SRC_DXF = (r"D:\git_codes\test_Autocad_MCP\good_examples"
           r"\20261119_gpu_datacenter_plan\20261119.dxf")
AC2013_DXF, AC1032_DWG = 61, 64

results: list[tuple[str, bool, str]] = []


def check(label, fn):
    try:
        detail = fn()
        results.append((label, True, detail or ""))
        print(f"  PASS  {label}")
        if detail:
            print(f"        {detail}")
    except Exception as exc:
        a = getattr(exc, "args", None)
        hr = a[0] if a and isinstance(a[0], int) else None
        info = getattr(exc, "excepinfo", None)
        msg = f"hr={hr} ({hr & 0xFFFFFFFF:#010x})" if hr else str(exc)
        if info and len(info) > 2:
            msg += f" excepinfo={info[2]!r}"
        results.append((label, False, msg))
        print(f"  FAIL  {label}")
        print(f"        {msg}")


def entities(path):
    import ezdxf
    return len(list(ezdxf.readfile(path).modelspace()))


def fresh(name):
    p = os.path.join(SCRATCH, name)
    if os.path.exists(p):
        os.remove(p)
    return p


def main() -> int:
    os.makedirs(SCRATCH, exist_ok=True)
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        base = app.Documents.Count

        # ── 3.4 ──────────────────────────────────────────────────────────
        print("\n3.4  new drawing straight to DXF")

        def doc_34():
            p = fresh("ex34_new.dxf")
            doc = app.Documents.Add()
            doc.SaveAs(p, AC2013_DXF)          # 61 = ac2013_dxf
            import array
            from win32com.client import VARIANT
            doc.ModelSpace.AddCircle(
                VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                        array.array("d", [0.0, 0.0, 0.0])), 50.0)
            doc.Save()                          # OK: path came from SaveAs
            doc.Close(False)                    # never Close(True)
            return f"{entities(p)} entity on disk"

        check("Add -> SaveAs -> Save -> Close(False)", doc_34)

        # ── 3.5 ──────────────────────────────────────────────────────────
        print("\n3.5  an existing DXF you must iterate on")

        def doc_35_wrong():
            """The doc says this fails. Prove the failure is the DXF one.

            A raised exception is the expected result here, so it is caught and
            inspected rather than propagated: only 0x80210063 counts as proof.
            """
            p = fresh("ex35_bad.dxf")
            shutil.copy2(SRC_DXF, p)
            doc = app.Documents.Open(p, False)
            import array
            from win32com.client import VARIANT
            doc.ModelSpace.AddCircle(
                VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                        array.array("d", [0.0, 0.0, 0.0])), 50.0)
            try:
                doc.Save()
            except Exception as exc:
                info = getattr(exc, "excepinfo", None)
                code = info[4] if info and len(info) > 4 else None
                doc.Close(False)
                assert code == -2145320861, (
                    f"expected 0x80210063, got {code!r} ({exc})")
                return "Save() raised 0x80210063 as documented"
            doc.Close(False)
            raise AssertionError("Save() unexpectedly succeeded on an opened DXF")

        check("Save() on an opened DXF is refused (as documented)", doc_35_wrong)

        def doc_35_right():
            p = fresh("ex35_src.dxf")
            q = fresh("ex35_fresh.dxf")
            shutil.copy2(SRC_DXF, p)
            doc = app.Documents.Open(p, False)
            doc.SaveAs(q, AC2013_DXF)          # re-point to a NEW path
            import array
            from win32com.client import VARIANT
            for r in (50.0, 60.0):             # save twice: proves it is repeatable
                doc.ModelSpace.AddCircle(
                    VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                            array.array("d", [0.0, 0.0, 0.0])), r)
                doc.Save()
            doc.Close(False)
            n = entities(q)
            base_n = entities(SRC_DXF)
            assert n == base_n + 2, f"expected {base_n + 2}, got {n}"
            return f"{base_n} -> {n} entities, two Saves() both direct"

        check("SaveAs(new path) then Save() twice", doc_35_right)

        def doc_35_roundtrip():
            p = fresh("ex35_rt.dxf")
            shutil.copy2(SRC_DXF, p)
            before = entities(p)
            doc = app.Documents.Open(p, False)
            import array
            from win32com.client import VARIANT
            doc.ModelSpace.AddCircle(
                VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                        array.array("d", [0.0, 0.0, 0.0])), 50.0)
            tmp = p + ".tmp.dxf"
            if os.path.exists(tmp):
                os.remove(tmp)
            doc.SaveAs(tmp, AC2013_DXF)        # a path this doc did not Open
            doc.Close(False)                   # releases the lock on p
            shutil.move(tmp, p)                # target now writable
            after = entities(p)
            assert after == before + 1, f"expected {before + 1}, got {after}"
            return f"{before} -> {after} entities on the original filename"

        check("round trip to keep the same filename", doc_35_roundtrip)

        # ── 3.6 ──────────────────────────────────────────────────────────
        print("\n3.6  DWG saves freely")

        def doc_36():
            p = fresh("ex36.dwg")
            doc = app.Documents.Add()
            doc.SaveAs(p, AC1032_DWG)
            import array
            from win32com.client import VARIANT
            for r in (10.0, 20.0, 30.0):       # repeated in-place saves
                doc.ModelSpace.AddCircle(
                    VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                            array.array("d", [0.0, 0.0, 0.0])), r)
                doc.Save()
            assert doc.ReadOnly is False, "ReadOnly must be False for a real test"
            doc.Close(False)
            return f"{os.path.getsize(p)} B written, 3 saves, no fallback"

        check("DWG: SaveAs then Save() x3", doc_36)

        # ── 3.7 ──────────────────────────────────────────────────────────
        print("\n3.7  the forbidden saves")

        def doc_37a():
            p = fresh("ex37_close_true.dxf")
            shutil.copy2(SRC_DXF, p)
            before = entities(p)
            doc = app.Documents.Open(p, False)
            import array
            from win32com.client import VARIANT
            doc.ModelSpace.AddCircle(
                VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                        array.array("d", [0.0, 0.0, 0.0])), 50.0)
            doc.Close(True)                    # pretends to save
            after = entities(p)
            assert after == before, (
                f"Close(True) DID write ({before} -> {after}); the doc is wrong")
            return f"Close(True) discarded the edit ({before} -> {after}), as documented"

        check("Close(True) silently discards edits", doc_37a)

        def doc_37b():
            p = fresh("ex37_type.dxf")
            doc = app.Documents.Add()
            doc.SaveAs(p)                       # no type argument
            doc.Close(False)
            actual = p + ".dwg"                 # x.dxf -> x.dxf.dwg
            got = os.path.exists(actual)
            for stray in (p, actual):
                if os.path.exists(stray):
                    os.remove(stray)
            assert got, "expected SaveAs('x.dxf') to write 'x.dxf.dwg'"
            return "SaveAs('x.dxf') without a type wrote 'x.dxf.dwg', as documented"

        check("SaveAs without a type appends .dwg", doc_37b)

    finally:
        try:
            app = win32com.client.Dispatch("AutoCAD.Application")
            while app.Documents.Count > base:
                app.Documents.Item(app.Documents.Count - 1).Close(False)
        except Exception:
            pass
        pythoncom.CoUninitialize()

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    passed = sum(1 for _, ok, _ in results if ok)
    for label, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            print(f"        {detail}")
    print(f"\n{passed}/{len(results)} assertions passed")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())