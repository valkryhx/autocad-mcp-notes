"""Clear a pending AutoCAD command so automation (and Ctrl+S) works again.

Strategy, in order of intrusiveness:
  1. PostMessage ESC to every plausible keyboard target inside the frame.
  2. If GetAcadState still says not quiescent, briefly foreground AutoCAD and
     send a real ESC with keybd_event, then restore the previous foreground
     window.

Only ESC is sent: it cancels a pending command and cannot modify a drawing.
Verifies with GetAcadState.IsQuiescent before and after each step.
"""
from __future__ import annotations

import ctypes
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
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.PostMessageW.restype = wintypes.BOOL
u.SetForegroundWindow.argtypes = [wintypes.HWND]
u.SetForegroundWindow.restype = wintypes.BOOL
u.GetForegroundWindow.restype = wintypes.HWND
u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.IsWindowVisible.restype = wintypes.BOOL

WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002


def class_of(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, b, 256)
    return b.value


def text_of(h):
    n = u.GetWindowTextLengthW(h)
    if n <= 0:
        return ""
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, b, n + 1)
    return b.value


def pid_of(h):
    o = wintypes.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(o))
    return int(o.value)


def kids(h):
    out = []
    u.EnumChildWindows(h, EnumWindowsProc(lambda k, _l: (out.append(k), True)[1]), 0)
    return out


def acad_pids():
    import subprocess
    raw = subprocess.run(["tasklist", "/FI", "IMAGENAME eq acad.exe", "/FO",
                          "CSV", "/NH"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    out = set()
    for line in raw.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) >= 2 and p[1].isdigit():
            out.add(int(p[1]))
    return out


def quiescent():
    """-> (is_quiescent or None, detail)"""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        try:
            st = app.GetAcadState()
            return bool(st.IsQuiescent), "GetAcadState ok"
        except Exception as exc:
            hr = exc.args[0] if getattr(exc, "args", None) else None
            return None, f"GetAcadState failed hr={hr} {getattr(exc,'strerror',exc)}"
    finally:
        pythoncom.CoUninitialize()


def docs_reachable():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        try:
            return True, f"Documents.Count={app.Documents.Count}"
        except Exception as exc:
            hr = exc.args[0] if getattr(exc, "args", None) else None
            return False, f"hr={hr} {getattr(exc, 'strerror', exc)}"
    finally:
        pythoncom.CoUninitialize()


def main():
    pids = acad_pids()
    frames = []

    def cb(h, _l):
        if pid_of(h) in pids and class_of(h) == "AfxMDIFrame140u":
            frames.append(h)
        return True

    u.EnumWindows(EnumWindowsProc(cb), 0)
    print(f"acad pids={sorted(pids)} frames={[hex(f) for f in frames]}")
    if not frames:
        return 1

    q, d = quiescent()
    ok, dd = docs_reachable()
    print(f"BEFORE: IsQuiescent={q} ({d}) | docs_reachable={ok} ({dd})")

    # Candidate keyboard targets: frame, every visible child, deepest viewports.
    targets = []
    for f in frames:
        targets.append(f)
        targets.extend(kids(f))
    # also walk two levels deeper for the drawing viewport
    for t in list(targets):
        targets.extend(kids(t))
    uniq = []
    for t in targets:
        if t not in uniq:
            uniq.append(t)
    print(f"keyboard targets to try: {len(uniq)}")

    print("=" * 80)
    print("STEP 1: PostMessage ESC to every candidate")
    print("=" * 80)
    for t in uniq:
        u.PostMessageW(t, WM_KEYDOWN, VK_ESCAPE, 1)
        u.PostMessageW(t, WM_KEYUP, VK_ESCAPE, 0xC0000001)
    time.sleep(1.2)
    q, d = quiescent()
    ok, dd = docs_reachable()
    print(f"  after post: IsQuiescent={q} | docs_reachable={ok} ({dd})")
    if ok:
        print("  ==> RECOVERED by posted ESC.")
        return 0

    print("=" * 80)
    print("STEP 2: foreground AutoCAD, real ESC, restore focus")
    print("=" * 80)
    prev_fg = u.GetForegroundWindow()
    print(f"  previous foreground 0x{prev_fg:08X} {text_of(prev_fg)!r}")
    frame = frames[0]
    shown = u.SetForegroundWindow(frame)
    print(f"  SetForegroundWindow -> {bool(shown)}")
    time.sleep(0.7)
    for _ in range(3):
        u.keybd_event(VK_ESCAPE, 0, 0, 0)
        u.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.4)
    time.sleep(0.8)
    q, d = quiescent()
    ok, dd = docs_reachable()
    print(f"  after real ESC: IsQuiescent={q} | docs_reachable={ok} ({dd})")

    if prev_fg:
        u.SetForegroundWindow(prev_fg)
        print(f"  restored foreground to 0x{prev_fg:08X}")

    if ok:
        print("  ==> RECOVERED by real ESC.")
        return 0
    print("=" * 80)
    print("Still wedged. AutoCAD will have to be restarted.")
    print("Unsaved work: check the window title for '*' BEFORE killing acad.exe.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())