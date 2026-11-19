"""Exhaustive save matrix for AutoCAD 2026 via COM.

Answers, for every realistic save path, exactly which succeed and which raise
0x80210063. Motivated by a challenge to the claim "any existing DXF cannot be
saved": draw_test/ holds many DXFs that were written successfully, so the claim
needs to be scoped by *how* the file got there, not by the extension alone.

Every case is isolated:
  * a scratch copy is made first; the source is never touched
  * the case opens its own file, edits it, saves, closes with Close(False)
  * after each case the on-disk entity count is read back with ezdxf

Run:  .venv/Scripts/python.exe scripts/save_matrix.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pythoncom
import win32com.client

SCRATCH = r"D:\git_codes\test_Autocad_MCP\draw_test\_save_matrix"
DXF_SRC = r"D:\git_codes\test_Autocad_MCP\good_examples\20261119_gpu_datacenter_plan\20261119.dxf"
DWG_SRC = r"D:\git_codes\test_Autocad_MCP\good_examples\20261119_gpu_datacenter_plan\20261119.dwg"
AC2013_DXF = 61
AC1032_DWG = 64


def hr_of(exc):
    a = getattr(exc, "args", None)
    return a[0] if a and isinstance(a[0], int) else None


def fmt_hr(hr):
    if hr is None:
        return "-"
    return f"{hr} ({hr & 0xFFFFFFFF:#010x})"


def excepinfo_of(exc):
    info = getattr(exc, "excepinfo", None)
    if not info:
        return None
    return tuple(info)


def entity_count(path):
    """Read the file back with ezdxf - independent of AutoCAD."""
    try:
        import ezdxf
        doc = ezdxf.readfile(path)
        return len(list(doc.modelspace()))
    except Exception as exc:
        return f"<{type(exc).__name__}: {exc}>"


def fresh(name):
    p = os.path.join(SCRATCH, name)
    if os.path.exists(p):
        os.remove(p)
    return p


def add_circle(doc):
    import array
    from win32com.client import VARIANT
    doc.ModelSpace.AddCircle(
        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                array.array("d", [0.0, 0.0, 0.0])),
        7.0,
    )


RPC_E_CALL_REJECTED = -2147418111


def _call(fn, attempts=15, delay=1.0):
    """Retry only the busy rejection, which AutoCAD answers immediately.

    Without this, closing a document right after a failed save can be refused
    and the scratch file stays locked.
    """
    import time
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            hr = hr_of(exc)
            if hr != RPC_E_CALL_REJECTED:
                raise
            time.sleep(delay)
    raise RuntimeError(f"AutoCAD still rejecting after {attempts} attempts")


def close_all_above(app, count):
    """Close every document beyond `count`, retrying the busy rejection.

    ``app.Documents`` is re-fetched on every read: a cached Documents dispatch
    turns into ``<unknown>.Count`` once the document set changes underneath it,
    which is a different failure from a busy rejection and must not be retried.
    """
    import time
    try:
        for _ in range(40):
            n = _call(lambda: app.Documents.Count)
            if n <= count:
                return
            doc = _call(lambda: app.Documents.Item(n - 1))
            _call(lambda d=doc: d.Close(False))
            time.sleep(0.2)
        print(f"  ! cleanup left documents open (count stayed above {count})")
    except Exception as exc:
        print(f"  ! cleanup could not close all documents: {exc}")


# ── the cases ───────────────────────────────────────────────────────────────


def case_new_dxf_saveas_then_save(app):
    """New empty drawing -> SaveAs a DXF -> edit -> Save (never closed)."""
    doc = app.Documents.Add()
    p = fresh("c1_new_saveas_then_save.dxf")
    doc.SaveAs(p, AC2013_DXF)
    add_circle(doc)
    doc.Save()
    doc.Close(False)
    return p


def case_new_dxf_saveas_close_reopen_save(app):
    """SaveAs -> close -> reopen from disk -> edit -> Save."""
    p = fresh("c2_saveas_close_reopen_save.dxf")
    doc = app.Documents.Add()
    doc.SaveAs(p, AC2013_DXF)
    doc.Close(False)
    doc = app.Documents.Open(p, False)
    add_circle(doc)
    doc.Save()
    doc.Close(False)
    return p


def case_open_dxf_save(app):
    """Copy an existing DXF -> Open it -> edit -> Save. The disputed path."""
    p = fresh("c3_open_then_save.dxf")
    import shutil
    shutil.copy2(DXF_SRC, p)
    doc = app.Documents.Open(p, False)
    add_circle(doc)
    doc.Save()
    doc.Close(False)
    return p


def case_open_dxf_saveas_same_path(app):
    """Copy -> Open -> edit -> SaveAs(the same path, 61)."""
    p = fresh("c4_open_then_saveas_same.dxf")
    import shutil
    shutil.copy2(DXF_SRC, p)
    doc = app.Documents.Open(p, False)
    add_circle(doc)
    doc.SaveAs(p, AC2013_DXF)
    doc.Close(False)
    return p


def case_open_dxf_saveas_new_path(app):
    """Copy -> Open -> edit -> SaveAs(a different, new path)."""
    p = fresh("c5_open_then_saveas_new_src.dxf")
    q = fresh("c5_open_then_saveas_new_dst.dxf")
    import shutil
    shutil.copy2(DXF_SRC, p)
    doc = app.Documents.Open(p, False)
    add_circle(doc)
    doc.SaveAs(q, AC2013_DXF)
    doc.Close(False)
    return q


def case_open_dwg_save(app):
    """Copy an existing DWG -> Open -> edit -> Save. The control case."""
    p = fresh("c6_open_dwg_then_save.dwg")
    import shutil
    shutil.copy2(DWG_SRC, p)
    doc = app.Documents.Open(p, False)
    add_circle(doc)
    doc.Save()
    doc.Close(False)
    return p


def case_new_dwg_saveas_then_save(app):
    """New -> SaveAs DWG -> edit -> Save."""
    p = fresh("c7_new_dwg_saveas_then_save.dwg")
    doc = app.Documents.Add()
    doc.SaveAs(p, AC1032_DWG)
    add_circle(doc)
    doc.Save()
    doc.Close(False)
    return p


def case_open_dxf_saveas_then_save(app):
    """Copy -> Open -> SaveAs(a new path) -> edit -> Save.

    This is the case that produces the DXFs in draw_test that DO exist: the
    document was re-pointed to a path it created this session, so the target
    is not "a DXF that was opened from disk".
    """
    p = fresh("c8_chain_src.dxf")
    q = fresh("c8_chain_dst.dxf")
    import shutil
    shutil.copy2(DXF_SRC, p)
    doc = app.Documents.Open(p, False)
    doc.SaveAs(q, AC2013_DXF)
    add_circle(doc)
    doc.Save()
    doc.Close(False)
    return q


def case_close_true_as_save(app):
    """Does Close(True) actually write the edit? (It is not a save.)"""
    p = fresh("c9_close_true.dxf")
    import shutil
    shutil.copy2(DXF_SRC, p)
    before = entity_count(p)
    doc = app.Documents.Open(p, False)
    add_circle(doc)
    doc.Close(True)  # pretending this saves
    after = entity_count(p)
    return p, before, after


CASES = [
    ("C1  new -> SaveAs(DXF) -> edit -> Save()", case_new_dxf_saveas_then_save),
    ("C2  new -> SaveAs(DXF) -> close -> open -> edit -> Save()",
     case_new_dxf_saveas_close_reopen_save),
    ("C3  copy -> Open(DXF) -> edit -> Save()", case_open_dxf_save),
    ("C4  copy -> Open(DXF) -> edit -> SaveAs(same path)", case_open_dxf_saveas_same_path),
    ("C5  copy -> Open(DXF) -> edit -> SaveAs(new path)", case_open_dxf_saveas_new_path),
    ("C6  copy -> Open(DWG) -> edit -> Save()   [control]", case_open_dwg_save),
    ("C7  new -> SaveAs(DWG) -> edit -> Save()", case_new_dwg_saveas_then_save),
    ("C8  copy -> Open(DXF) -> SaveAs(new) -> edit -> Save()",
     case_open_dxf_saveas_then_save),
]


def main() -> int:
    os.makedirs(SCRATCH, exist_ok=True)
    for src in (DXF_SRC, DWG_SRC):
        if not os.path.exists(src):
            print(f"missing source: {src}")
            return 1

    src_hashes = {s: hashlib.sha256(open(s, "rb").read()).hexdigest()
                  for s in (DXF_SRC, DWG_SRC)}

    pythoncom.CoInitialize()
    rows = []
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        print(f"IsQuiescent = {app.GetAcadState().IsQuiescent}")
        print(f"Documents already open: {app.Documents.Count}")
        print()

        for label, fn in CASES:
            before = app.Documents.Count
            try:
                result = fn(app)
                if isinstance(result, tuple):
                    path, before_n, after_n = result
                    rows.append((label, "OK", "-", "-",
                                 f"entities {before_n} -> {after_n}"))
                else:
                    rows.append((label, "OK", "-", "-", entity_count(result)))
            except Exception as exc:
                hr = hr_of(exc)
                info = excepinfo_of(exc)
                detail = ""
                if info:
                    detail = f"excepinfo={info!r}"
                rows.append((label, "FAIL", fmt_hr(hr),
                             getattr(exc, "strerror", str(exc))[:40], detail))
            finally:
                # Never leave a document open: a stuck doc poisons later cases
                # AND keeps a file lock that blocks cleanup. Retry the busy
                # rejection instead of swallowing it - swallowing is how the
                # C2 case left a document open and a scratch file locked.
                close_all_above(app, before)

        print("=" * 118)
        print("SAVE MATRIX - AutoCAD 2026, COM")
        print("=" * 118)
        for label, verdict, hr, msg, detail in rows:
            print(f"{verdict:4s} | {label}")
            if verdict == "FAIL":
                print(f"       hresult : {hr}")
                print(f"       message : {msg}")
                print(f"       {detail}")
            else:
                print(f"       on-disk entities: {detail}")
            print()

        # Close(True) is measured separately: it lies about success.
        print("=" * 118)
        print("C9  Close(True) as a save - does it write?")
        print("=" * 118)
        try:
            p, b, a = case_close_true_as_save(app)
            print(f"  entities before Close(True): {b}")
            print(f"  entities after  Close(True): {a}")
            print(f"  edit written? {b != a}")
        except Exception as exc:
            print(f"  FAIL {fmt_hr(hr_of(exc))} {getattr(exc, 'strerror', exc)}")

        print()
        print("=" * 118)
        print("SOURCE FILES UNTOUCHED?")
        print("=" * 118)
        for s, h in src_hashes.items():
            now = hashlib.sha256(open(s, "rb").read()).hexdigest()
            print(f"  {'OK ' if now == h else 'CHANGED'}  {os.path.basename(s)}")
        return 0
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())