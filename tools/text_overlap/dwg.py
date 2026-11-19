"""Read a DWG by borrowing a running AutoCAD to write a temporary DXF.

Why this exists: the check itself is pure ezdxf and needs no AutoCAD. But a DWG
is not a DXF, and this machine has neither route to read one offline:

* ODA File Converter is not installed (that is what ezdxf's ``odafc`` add-on
  needs, and it is the only DWG path ezdxf has);
* ``accoreconsole.exe`` here reports ``Version W.60.0.0`` and "许可证无效", and
  with a ``/s`` script it hangs at the ``命令:`` prompt (``timeout`` exits 124).

So the one working route is a **running** AutoCAD, driven by COM.

## The rule this module is built around

**Never call ``SaveAs`` on a document the user has open.** ``SaveAs`` re-points
the *document*: if it is applied to the user's open drawing, that drawing stops
being the DWG and becomes our temporary DXF, which we then delete. The drawing
on disk is untouched, but the user's session is left holding a file that no
longer exists - and their next save writes to a path under ``%TEMP%``.

That happened on the first version of this module: the active document in
AutoCAD became ``tc_dwg_ij_admuf.dxf``. So the conversion now works on a **copy**
of the DWG in the temp directory, opens that copy, and ``SaveAs`` only ever runs
on a document whose ``FullName`` has been checked to be the copy. The user's
documents are neither saved, closed, nor re-pointed.
"""

from __future__ import annotations

import os
import shutil
import tempfile

#: `AcSaveAsType` for a 2013 DXF. This argument is **not** optional: without it
#: AutoCAD goes by the extension on its own terms and `SaveAs("x.dxf")` produces
#: `x.dxf.dwg`, which then fails to read as a DXF. Measured on AutoCAD 2026.
AC2013_DXF = 61

#: `RPC_E_CALL_REJECTED`. AutoCAD refuses a call while it is busy with something
#: else - a regeneration, a plot, the user mid-command - and the refusal is
#: immediate rather than queued. It is **not** a dead connection: the same call
#: succeeds a moment later. pywin32 exposes no message filter
#: (`pythoncom.CoRegisterMessageFilter` does not exist in this build), so the
#: retry has to be here.
RPC_E_CALL_REJECTED = -2147418111
#: How many times to re-ask, and how long to wait between asks. Chosen against
#: the measured behaviour: a busy AutoCAD cleared within two 1.5 s waits.
COM_RETRIES = 8
COM_RETRY_DELAY = 1.5


def _call(fn, *args, **kwargs):
    """Call a COM method, retrying while AutoCAD says it is busy.

    Only ``RPC_E_CALL_REJECTED`` is retried. Every other error is a real answer
    and is raised at once - retrying those would turn a clear failure into a
    slow one.
    """
    import time

    last: BaseException | None = None
    for _attempt in range(COM_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            hresult = getattr(exc, "hresult", None)
            if hresult is None:
                args_ = getattr(exc, "args", ())
                hresult = args_[0] if args_ and isinstance(args_[0], int) else None
            if hresult != RPC_E_CALL_REJECTED:
                raise
            last = exc
            time.sleep(COM_RETRY_DELAY)
    raise DwgUnavailable(
        f"AutoCAD kept refusing COM calls for {COM_RETRIES * COM_RETRY_DELAY:.0f} s "
        f"(RPC_E_CALL_REJECTED). Last error: {last}",
        "AutoCAD is busy or waiting on a dialog. Press ESC in AutoCAD (a modal "
        "state refuses every call while the process stays alive), then re-run. "
        "If it stays busy, save a DXF by hand and check that.",
    )


class DwgUnavailable(RuntimeError):
    """No route to read DWG on this machine.

    ``remedy`` names the thing the user can actually do, because "could not read
    the file" without that is a dead end.
    """

    def __init__(self, message: str, remedy: str) -> None:
        super().__init__(message)
        self.remedy = remedy


def _app():
    """The running AutoCAD, or raise with the remedies spelled out."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover - pywin32 is present here
        raise DwgUnavailable(
            f"pywin32 is not importable ({exc}), so a DWG cannot be read.",
            "Run the check on a DXF instead: drawing_save_as('whatever.dxf').",
        ) from exc

    try:
        pythoncom.CoInitialize()
    except Exception:  # pragma: no cover - already initialised
        pass

    try:
        # GetActiveObject, not Dispatch: Dispatch would *launch* a second AutoCAD
        # and then the check would work in a process the user is not looking at,
        # while a wedged first instance stayed wedged.
        return win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception as exc:
        raise DwgUnavailable(
            "AutoCAD is not running (or its COM automation server is not "
            f"responding: {type(exc).__name__}: {exc}).",
            "Start AutoCAD and open the drawing, or save a DXF first "
            "(SaveAs with AcSaveAsType 61). If AutoCAD *is* running, press ESC "
            "in it: a wedged modal state makes COM refuse every call while the "
            "process stays alive.",
        ) from exc


def _same_file(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _close_quietly(document) -> None:
    """Close our own document without saving, and never raise.

    Failure here is not fatal to the check, but it leaves a document open in the
    user's AutoCAD - which is exactly the kind of leftover someone blames on
    "the tool did something weird", so it is worth retrying and it is worth not
    masking a real error with a cleanup error.
    """
    try:
        _call(document.Close, False)
    except Exception:  # pragma: no cover - the DXF is already on disk
        pass


def to_dxf(path: str) -> tuple[str, str]:
    """Convert a DWG to a temporary DXF. Returns ``(dxf_path, how)``.

    Works on a copy, so the drawing the user has open is never saved, closed or
    re-pointed. ``how`` is a short human sentence saying what was done, so the
    caller can report it: a check that quietly moves the user's document is a
    check that gets blamed for something it did not do.

    The caller owns the returned DXF path and must delete it.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    app = _app()

    workdir = tempfile.mkdtemp(prefix="tc_dwg_")
    stem = os.path.splitext(os.path.basename(path))[0]
    dwg_copy = os.path.join(workdir, f"{stem}.dwg")
    dxf_out = os.path.join(workdir, f"{stem}.dxf")
    shutil.copy2(path, dwg_copy)

    try:
        previous = None
        try:
            previous = _call(lambda: app.ActiveDocument)
        except Exception:  # pragma: no cover - no active document
            previous = None

        document = None
        try:
            # `Documents.Open`'s return value is not trustworthy here: when the
            # call is made while AutoCAD is busy, pywin32 resolves the result to
            # a CDispatch whose `_username_` is "Open" - the *method*, not the
            # document. It has no `.SaveAs`, and `hasattr(opened, "SaveAs")` is
            # False. Re-resolving through `ActiveDocument` gives a real document.
            #
            # This is safe because the very next thing that happens is the
            # FullName check: if ActiveDocument turned out to be the user's
            # drawing rather than our copy, the save is abandoned. The identity
            # check, not the return value, is what protects the user.
            _call(app.Documents.Open, dwg_copy, True)  # ReadOnly=True
            document = _call(lambda: app.ActiveDocument)
        except Exception as exc:
            raise DwgUnavailable(
                f"AutoCAD could not open a copy of {os.path.basename(path)}: "
                f"{type(exc).__name__}: {exc}",
                "Open the drawing in AutoCAD by hand, or save a DXF "
                "(SaveAs, AcSaveAsType 61) and check that.",
            ) from exc

        # The safety check this whole module exists for. If SaveAs were applied
        # to any document but our copy, it would re-point the user's drawing.
        try:
            actual = _call(lambda: document.FullName)
        except Exception as exc:  # pragma: no cover
            actual = ""
            raise DwgUnavailable(
                f"could not confirm which document AutoCAD opened ({exc}).",
                "Save a DXF by hand and check that instead.",
            ) from exc
        if not _same_file(actual, dwg_copy):
            _close_quietly(document)
            raise DwgUnavailable(
                "AutoCAD opened a different file than the temporary copy "
                f"({actual!r}), so the save was abandoned rather than risk "
                "touching a document that is not ours.",
                "Save a DXF by hand and check that instead.",
            )

        try:
            _call(document.SaveAs, dxf_out, AC2013_DXF)
        except Exception as exc:
            raise DwgUnavailable(
                f"AutoCAD could not save {os.path.basename(path)} as DXF: "
                f"{type(exc).__name__}: {exc}",
                "Save it by hand (SaveAs, AcSaveAsType 61) and run the check on "
                "the DXF.",
            ) from exc
        finally:
            # Always close the copy without saving. This closes our document,
            # never one of the user's.
            _close_quietly(document)
            if previous is not None:
                try:
                    _call(previous.Activate)
                except Exception:  # pragma: no cover
                    pass

        if not os.path.isfile(dxf_out) or os.path.getsize(dxf_out) == 0:
            raise DwgUnavailable(
                f"AutoCAD reported success but wrote no DXF at {dxf_out}.",
                "Save the drawing as a DXF by hand and run the check on that.",
            )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    finally:
        try:
            os.remove(dwg_copy)
        except OSError:  # pragma: no cover
            pass

    how = (
        f"read {os.path.basename(path)} through the running AutoCAD, which "
        "converted a temporary copy to DXF"
    )
    return dxf_out, how


def can_read_dwg() -> tuple[bool, str]:
    """Whether a DWG can be read right now, and why not. For diagnostics."""
    try:
        import win32com.client  # noqa: F401
    except ImportError as exc:
        return False, f"pywin32 missing: {exc}"
    try:
        _app()
    except DwgUnavailable as exc:
        return False, str(exc)
    return True, "AutoCAD is running, so a DWG can be read through it"