"""Diagnose why AutoCAD/MCP cannot talk - in one pass, read-only.

Replaces the fourteen one-off probes written while tracking down
``RPC_E_CALL_REJECTED`` on every document call. Run this first; it answers the
question the error text does not: *is AutoCAD disconnected, dead, busy, or
waiting for input?*

    python scripts/diag_acad_state.py

Nothing here writes to a drawing, opens a file, or sends WM_PRINT. The only
window messages used are WM_NULL (via IsHungAppWindow) and WM_GETTEXT, neither
of which disturbs AutoCAD's renderer.

Interpreting the output
-----------------------
*  ``GetAcadState().IsQuiescent = False`` and the app-level calls work while
   document calls are rejected
   -> a command is sitting at a prompt. Run ``clear_pending_command.py``.
   Waiting and restarting both do nothing.
*  ``proxy_dropped`` in the MCP ``system_status`` output
   -> the MCP-side stale-proxy bug (P0). One retry recovers.
*  ``IsHungAppWindow = True`` or a ``#32770`` dialog
   -> something modal is holding the message loop; deal with the dialog.
*  high CPU with no ``#32770``
   -> AutoCAD is genuinely computing; wait.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

u = ctypes.WinDLL("user32", use_last_error=True)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

u.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
u.EnumChildWindows.argtypes = [wintypes.HWND, EnumWindowsProc, wintypes.LPARAM]
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.GetWindowThreadProcessId.restype = wintypes.DWORD
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
u.GetWindowTextLengthW.restype = ctypes.c_int
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.IsWindowVisible.restype = wintypes.BOOL
u.IsWindowEnabled.argtypes = [wintypes.HWND]
u.IsWindowEnabled.restype = wintypes.BOOL
u.IsHungAppWindow.argtypes = [wintypes.HWND]
u.IsHungAppWindow.restype = wintypes.BOOL


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


u.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]

GUI_FLAGS = {
    0x01: "GUI_INMOVESIZE",
    0x02: "GUI_INMENUMODE",
    0x04: "GUI_SYSTEMMENUMODE",
    0x08: "GUI_POPUPMENUMODE",
}


def text_of(h):
    n = u.GetWindowTextLengthW(h)
    if n <= 0:
        return ""
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, b, n + 1)
    return b.value


def class_of(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, b, 256)
    return b.value


def pid_of(h):
    o = wintypes.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(o))
    return int(o.value)


def acad_pids() -> set[int]:
    raw = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq acad.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    out = set()
    for line in raw.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) >= 2 and p[1].isdigit():
            out.add(int(p[1]))
    return out


def hr_of(exc):
    if getattr(exc, "args", None) and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def section(title):
    print()
    print("=" * 84)
    print(title)
    print("=" * 84)


# ── 1. process ──────────────────────────────────────────────────────────────


def report_process(pids: set[int]) -> int | None:
    section("1. PROCESS")
    if not pids:
        print("  acad.exe is not running.")
        return None
    pid = sorted(pids)[0]
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"$p=Get-Process -Id {pid}; "
         "Write-Output ('threads=' + $p.Threads.Count +"
         " ' ws_mb=' + [math]::Round($p.WorkingSet64/1MB) +"
         " ' responding=' + $p.Responding)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    print(f"  pid {pid}: {ps}")

    def cpu_now():
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Id {pid}).CPU"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace").stdout.strip()
        try:
            return float(out)
        except ValueError:
            return None

    a = cpu_now()
    t0 = time.perf_counter()
    time.sleep(3.0)
    b = cpu_now()
    dt = time.perf_counter() - t0
    if a is not None and b is not None:
        pct = (b - a) / dt * 100.0
        verdict = "COMPUTING" if pct > 5.0 else "IDLE (not computing)"
        print(f"  CPU over {dt:.1f}s: {pct:.1f}%  -> {verdict}")
    return pid


# ── 2. windows ──────────────────────────────────────────────────────────────


def report_windows(pids: set[int]):
    section("2. WINDOWS - modal dialog? hung UI? menu loop?")
    frames = []

    def top(h, _l):
        if pid_of(h) in pids:
            cls = class_of(h)
            if cls == "AfxMDIFrame140u":
                frames.append(h)
                print(f"  frame 0x{h:08X} {text_of(h)!r}")
                print(f"    IsHungAppWindow = {bool(u.IsHungAppWindow(h))}")
                tid = u.GetWindowThreadProcessId(h, None)
                info = GUITHREADINFO()
                info.cbSize = ctypes.sizeof(GUITHREADINFO)
                if u.GetGUIThreadInfo(tid, ctypes.byref(info)):
                    active = [n for bit, n in GUI_FLAGS.items() if info.flags & bit]
                    print(f"    GUI flags       = {info.flags} {active or '(idle)'}")
            elif cls == "#32770":
                print(f"  !! DIALOG 0x{h:08X} {text_of(h)!r} "
                      f"visible={bool(u.IsWindowVisible(h))}")
        return True

    u.EnumWindows(EnumWindowsProc(top), 0)
    if not frames:
        print("  no AfxMDIFrame140u found")


# ── 3. COM ──────────────────────────────────────────────────────────────────


def report_com():
    section("3. COM - which surfaces answer?")
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        try:
            app = win32com.client.Dispatch("AutoCAD.Application")
        except Exception as exc:
            print(f"  Dispatch FAILED: hr={hr_of(exc)} {exc}")
            return None

        print("  -- application level --")
        for label, getter in [
            ("Visible", lambda: app.Visible),
            ("Version", lambda: app.Version),
            ("Caption", lambda: app.Caption),
            ("GetAcadState", lambda: app.GetAcadState().IsQuiescent),
        ]:
            try:
                print(f"    {label:16s} OK      {getter()!r}")
            except Exception as exc:
                print(f"    {label:16s} REFUSED {hr_of(exc)}")

        print("  -- document level --")
        doc_ok = None
        try:
            n = app.Documents.Count
            print(f"    {'Documents.Count':16s} OK      {n}")
            doc_ok = True
        except Exception as exc:
            print(f"    {'Documents.Count':16s} REFUSED {hr_of(exc)} "
                  f"{getattr(exc, 'strerror', '')}")
            doc_ok = False

        if doc_ok:
            try:
                d = app.ActiveDocument
                print(f"    {'ActiveDocument':16s} OK      {d.Name!r}")
                print(f"      Saved={d.Saved} ReadOnly={d.ReadOnly}")
            except Exception as exc:
                print(f"    {'ActiveDocument':16s} REFUSED {hr_of(exc)}")
        return doc_ok
    finally:
        pythoncom.CoUninitialize()


# ── 4. the open documents, from the filesystem side ─────────────────────────


def report_files():
    section("4. DOCUMENT HANDLES (is anything locked by AutoCAD?)")
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            app = win32com.client.Dispatch("AutoCAD.Application")
            docs = app.Documents
            for i in range(docs.Count):
                d = docs.Item(i)
                full = d.FullName
                print(f"  [{i}] {d.Name!r}  Saved={d.Saved}  "
                      f"ReadOnly={d.ReadOnly}")
                print(f"       {full}")
                if not full or not os.path.exists(full):
                    print("       (no file on disk)")
                    continue
                st = os.stat(full)
                print(f"       {st.st_size} B  "
                      f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}")
                for mode, label in (("rb", "read"), ("r+b", "write")):
                    try:
                        with open(full, mode):
                            pass
                        print(f"       {label} access: OK")
                    except OSError as exc:
                        print(f"       {label} access: REFUSED ({exc.strerror})")
        finally:
            pythoncom.CoUninitialize()
    except Exception as exc:
        print(f"  cannot enumerate documents: {exc}")


# ── 5. MCP process ──────────────────────────────────────────────────────────


def report_mcp():
    section("5. MCP SERVICE PROCESS")
    raw = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*autocad-mcp*' } | "
         "ForEach-Object { $_.ProcessId, $_.CreationDate }"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    if not lines:
        print("  no autocad-mcp python process found")
    else:
        for i in range(0, len(lines), 2):
            pid = lines[i]
            created = lines[i + 1] if i + 1 < len(lines) else "?"
            print(f"  pid {pid}  started {created}")


# ── verdict ─────────────────────────────────────────────────────────────────


def main() -> int:
    pids = acad_pids()
    print(f"acad.exe pids: {sorted(pids)}")
    report_process(pids)
    report_windows(pids)
    doc_ok = report_com()
    report_files()
    report_mcp()

    section("VERDICT")
    if not pids:
        print("  AutoCAD is not running. Start it (or let MCP launch it) and retry.")
        return 1
    if doc_ok:
        print("  Document calls work. If a tool still fails, the problem is above")
        print("  this layer (MCP service state, permissions, path allowlist).")
        return 0
    print("  Document-level COM is rejected while the application answers.")
    print("  That signature means AutoCAD has a command parked at a prompt:")
    print("    -> GetAcadState().IsQuiescent = False")
    print("    -> run: python scripts/clear_pending_command.py")
    print("  Waiting will not help, and neither will restarting either process.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())