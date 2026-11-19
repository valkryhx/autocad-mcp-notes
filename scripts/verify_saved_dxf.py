"""Read the DXF back from disk and prove the saved entity is really there.

Reads with ezdxf (the MCP's own ezdxf install), not through AutoCAD, so this is
independent evidence that the file on disk holds the edit.
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import ezdxf

PATH = r"D:\git_codes\test_Autocad_MCP\draw_test\multi_save.dxf"


def main() -> int:
    doc = ezdxf.readfile(PATH)
    msp = doc.modelspace()
    all_ents = list(msp)
    circles = [e for e in msp if e.dxftype() == "CIRCLE"]
    print(f"file            : {PATH}")
    print(f"ezdxf version   : {ezdxf.__version__}")
    print(f"DXF version     : {doc.dxfversion}")
    print(f"entities (msp)  : {len(all_ents)}")
    print(f"layers          : {len(doc.layers)}")
    print(f"blocks          : {len(doc.blocks)}")
    print(f"circles         : {len(circles)}")
    for c in circles:
        ctr = c.dxf.center
        print(f"  handle={c.dxf.handle} center=({ctr.x}, {ctr.y}) r={c.dxf.radius} "
              f"layer={c.dxf.layer}")

    found = any(
        abs(c.dxf.center.x - 100.0) < 1e-6
        and abs(c.dxf.center.y - 100.0) < 1e-6
        and abs(c.dxf.radius - 50.0) < 1e-6
        for c in circles
    )
    print()
    print(f"ASSERT center=(100,100) r=50 present on disk: {found}")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())