"""Point every text entity at a TrueType style, so `m²` and CJK actually plot.

Why this is a script and not a tool call: no MCP tool changes the *style* of an
existing text entity, and `arch_room` labels are created with the current style
(`Standard` = txt.shx, which has no `²` glyph). `textbox`-side measurement is
fine; the defect is only visible at plot time.

Two passes, because they fix different things:
  1. retarget `Standard` itself at simsun.ttc - every entity using it follows,
     including the ones inside blocks;
  2. as a belt-and-braces check, count how many text entities still name a style
     whose font is an SHX file.

Run against the OPEN document (live AutoCAD), then verify from the saved file.
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pythoncom
import win32com.client

FONT = r"C:\Windows\Fonts\simsun.ttc"


def main() -> int:
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        doc = app.ActiveDocument
        print(f"document: {doc.Name}")

        styles = doc.TextStyles
        print(f"text styles: {styles.Count}")
        for i in range(styles.Count):
            st = styles.Item(i)
            print(f"  {st.Name!r:20s} font={st.fontFile!r}")

        std = styles.Item("Standard")
        print(f"\nStandard before: font={std.fontFile!r}")
        std.fontFile = FONT
        print(f"Standard after : font={std.fontFile!r}")

        # Re-read to confirm AutoCAD accepted it.
        std2 = styles.Item("Standard")
        print(f"Standard re-read: font={std2.fontFile!r}")

        doc.Regen(1)

        # Count texts whose style still names an SHX font.
        shx = []
        for style_i in range(styles.Count):
            st = styles.Item(style_i)
            ff = (st.fontFile or "")
            if ff.lower().endswith(".shx"):
                shx.append(st.Name)
        print(f"\nstyles still on an SHX font: {shx}")
        return 0
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())