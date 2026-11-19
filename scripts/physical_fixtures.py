"""Build fixtures for the physical-collision check, and prove it fires.

A check that never fires is indistinguishable from no check. Three fixtures:

  blocked.dxf   a rack sitting in a door's swing (the real defect measured on
                231.dxf before it was fixed: row at x=11300, leaf sweeps to
                12500). Must report `opening_blocked`.
  clash.dxf     two racks in the same footprint. Must report `solid_overlap`.
  clean.dxf     the same rack grid, clear of the door. Must report nothing.

The clean fixture matters as much as the others: the first version of the check
reported 47 clashes for 48 adjacent racks, because a shared edge counted as an
overlap. Every rack in a row touches its neighbour exactly.

Run:  .venv/Scripts/python.exe scripts/physical_fixtures.py [--out DIR]
"""
from __future__ import annotations

import argparse
import math
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import ezdxf

RACK_W, RACK_D = 600.0, 1200.0
DOOR_LAYER = "A-DOOR-E-N"
FURN_LAYER = "A-FURN-E-N"


def _layers(doc):
    for name, color in ((DOOR_LAYER, 3), (FURN_LAYER, 5)):
        if name not in doc.layers:
            doc.layers.add(name, color=color)


def _rack(msp, x, y, layer=FURN_LAYER, tag=None):
    pts = [(x, y), (x + RACK_W, y), (x + RACK_W, y + RACK_D), (x, y + RACK_D)]
    pl = msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    if tag:
        msp.add_text(
            tag, height=125, dxfattribs={"layer": layer}
        ).set_placement((x + RACK_W / 2, y + RACK_D / 2))
    return pl


def _door(msp, hinge, radius, start_deg, end_deg):
    """A leaf line plus the swing arc - the shape arch_opening draws."""
    hx, hy = hinge
    leaf_end = (
        hx + radius * math.cos(math.radians(start_deg)),
        hy + radius * math.sin(math.radians(start_deg)),
    )
    msp.add_line((hx, hy), leaf_end, dxfattribs={"layer": DOOR_LAYER})
    msp.add_arc(
        center=(hx, hy),
        radius=radius,
        start_angle=start_deg,
        end_angle=end_deg,
        dxfattribs={"layer": DOOR_LAYER},
    )


def build_blocked(path):
    """A rack row running into the door swing. The defect that was measured.

    Geometry copied from the real door (D3 on wall W_RIGHT of 231.dxf): the
    wall is vertical at x=12500, the hinge sits at the TOP of the opening
    (y=2000), the leaf is drawn OPEN pointing west (-X, 180 deg), and the arc
    sweeps from there to the closed position along the wall (south, 270 deg).
    That quarter is x 11300..12500 by y 800..2000 - the lower-left quadrant.

    Getting this wrong is easy and the check will look broken: sweeping 90..180
    instead covers the UPPER-left quadrant, which is empty, and a rack below
    the hinge is never reported.
    """
    doc = ezdxf.new("R2013")
    _layers(doc)
    msp = doc.modelspace()
    _door(msp, (12500, 2000), 1200, 180, 270)
    _rack(msp, 10700, 400, tag="R-OK01")    # clear of the swing
    _rack(msp, 11300, 400, tag="R-BAD")     # <-- inside the swing
    doc.saveas(path)
    return path


def build_clash(path):
    """Two racks occupying the same footprint."""
    doc = ezdxf.new("R2013")
    _layers(doc)
    msp = doc.modelspace()
    _rack(msp, 1000, 1000, tag="R-A")
    _rack(msp, 1100, 1050, tag="R-B")       # 500x1150 of it shared
    doc.saveas(path)
    return path


def build_clean(path):
    """The corrected layout: a 6-rack row that just fits, clear of the door."""
    doc = ezdxf.new("R2013")
    _layers(doc)
    msp = doc.modelspace()
    _door(msp, (12500, 2000), 1200, 180, 270)    # same door as `blocked`
    # 6 racks from 7050 to 10650 - the corrected positions from 231.dxf.
    for k in range(6):
        _rack(msp, 7050 + k * RACK_W, 400, tag=f"R-OK{k + 1:02d}")
    doc.saveas(path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="draw_test/_physical_fixtures")
    args = ap.parse_args(argv)

    from pathlib import Path

    # `tools` lives at the repo root; a script run from scripts/ does not see it.
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    paths = {
        "blocked": build_blocked(str(out / "blocked.dxf")),
        "clash": build_clash(str(out / "clash.dxf")),
        "clean": build_clean(str(out / "clean.dxf")),
    }
    for name, p in paths.items():
        print(f"wrote {name}: {p}")

    print()
    from tools.text_overlap import detect

    expected = {
        "blocked": {"opening_blocked"},
        "clash": {"solid_overlap"},
        "clean": set(),
    }
    failures = []
    for name, p in paths.items():
        report = detect(p)
        kinds = {f["kind"] for f in report["findings"]
                 if f["kind"] in ("opening_blocked", "solid_overlap")}
        ok = kinds == expected[name]
        print(f"{'PASS' if ok else 'FAIL'}  {name}: expected {expected[name] or '{}'}, "
              f"got {kinds or '{}'}")
        for f in report["findings"]:
            if f["kind"] in ("opening_blocked", "solid_overlap"):
                print(f"        {f['kind']}: {f.get('note','')}")
        if not ok:
            failures.append(name)
    print()
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("3/3 fixtures behave as specified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())