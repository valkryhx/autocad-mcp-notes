"""Render a DXF with matplotlib, and report what actually landed in the image.

Why: on this machine `view_zoom_and_screenshot` cannot photograph AutoCAD (its
drawing area is GPU-composited and absent from the GDI surface), so the only
proof that a layout renders at all is to draw the DXF ourselves. The SVG path
(`render_svg.py`) proves geometry; this one proves PIXELS, which is a different
claim - a backend can emit valid SVG and still produce a black rectangle.

The trap this tool exists to avoid: `import numpy` on this box intermittently
dies with

    OpenBLAS error: Memory allocation still failed after 10 retries

That is MEMORY PRESSURE, not a version defect - measured 2026-11-19, free RAM
was 0.7 GB with AutoCAD holding 1.4 GB private. numpy and matplotlib were both
already the newest releases on PyPI, so upgrading fixes nothing. The answer is
fewer BLAS threads (below) and a machine that is not already full.

    python scripts/render_mpl.py FILE.dxf [-o out.png] [--dpi 100]
    python scripts/render_mpl.py FILE.dxf --layer A-FURN-E-N
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Before numpy loads: one thread per BLAS pool keeps the arena reservation
# small. setdefault, so an explicit choice in the environment still wins.
import os

for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(var, "1")

import matplotlib

matplotlib.use("Agg")           # no display, no GUI thread, fewer buffers
import matplotlib.pyplot as plt  # noqa: E402
import ezdxf                     # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import (  # noqa: E402
    BackgroundPolicy,
    Configuration,
)
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402

#: Same ACI table as render_svg.py, kept separate on purpose: this file must
#: not import the SVG module, or a failure in one path would hide the other.
ACI_RGB = {
    1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255),
    5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255), 8: (128, 128, 128),
    9: (192, 192, 192), 30: (255, 127, 0), 40: (255, 191, 0),
    250: (51, 51, 51), 251: (80, 80, 80), 252: (105, 105, 105),
    253: (130, 130, 130), 254: (190, 190, 190),
}


def fitted_size(doc, long_side_in: float = 14.0) -> tuple[float, float]:
    """A figure whose aspect ratio matches the drawing's extents.

    A fixed 14x10 figure does not "just work": `finalize` fits the content into
    the canvas, so a square drawing inside a 1.4:1 canvas is letterboxed and
    loses ~30% of its pixels. Measured on server_room_v2 (11200x12100 units):
    a 14x10 figure at 110 dpi produced only 488x528 px.
    """
    from ezdxf import bbox

    extents = bbox.extents(doc.modelspace())
    if not extents.has_data:
        return (long_side_in, long_side_in)
    w = extents.extmax.x - extents.extmin.x
    h = extents.extmax.y - extents.extmin.y
    if w <= 0 or h <= 0:
        return (long_side_in, long_side_in)
    if w >= h:
        return (long_side_in, long_side_in * h / w)
    return (long_side_in * w / h, long_side_in)


def render(path: str, out: str, dpi: int = 100,
           long_side_in: float = 14.0) -> dict:
    """Draw the modelspace to PNG. Returns measurements about the result."""
    doc = ezdxf.readfile(path)
    size = fitted_size(doc, long_side_in)
    fig = plt.figure(figsize=size, facecolor="black")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("black")
    ax.set_axis_off()

    ctx = RenderContext(doc)
    # adjust_figure=False is essential. ezdxf's `finalize()` otherwise calls
    # `plt.figaspect()` and calls `set_size_inches()` on OUR figure, replacing
    # the size we chose with its own ~4.8 in default. Measured on this drawing:
    # 13x14 in @ 150 dpi should be 1950x2100 px but came out 666x720.
    backend = MatplotlibBackend(ax, adjust_figure=False)
    config = Configuration(background_policy=BackgroundPolicy.BLACK)
    Frontend(ctx, backend, config=config).draw_layout(doc.modelspace(),
                                                      finalize=True)
    # The axes must fill the canvas exactly; `finalize` leaves a small margin.
    ax.set_position([0, 0, 1, 1])
    fig.savefig(out, dpi=dpi, facecolor="black")
    plt.close(fig)
    return {"entities": len(doc.modelspace()),
            "bytes": Path(out).stat().st_size,
            "figsize": size}


def image_stats(out: str) -> dict:
    """How much of the PNG is actually painted, and in which colours.

    A renderer that silently draws nothing produces a uniformly black file that
    is still a valid PNG of a plausible size, so "the file exists" proves
    nothing. Counting distinct colours is the cheap honest test: a real plan has
    several, a blank canvas has one.
    """
    from PIL import Image

    with Image.open(out) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        # getdata() is deprecated in Pillow 14 (2027-10-15); the flat-bytes
        # route works on every version without a warning.
        raw = rgb.tobytes()
    # Three bytes per pixel; count them without building a tuple per pixel,
    # which on a 2000x2000 canvas is four million objects.
    colour_counts: Counter[tuple[int, int, int]] = Counter(
        (raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)
    )
    colours = colour_counts
    painted = sum(n for c, n in colours.items() if c != (0, 0, 0))
    return {
        "size": (width, height),
        "distinct_colours": len(colours),
        "painted_px": painted,
        "painted_pct": 100.0 * painted / (width * height),
        "top": colours.most_common(8),
    }


def layer_colours(doc) -> dict[str, str]:
    out = {}
    for layer in doc.layers:
        aci = layer.dxf.color
        if aci in ACI_RGB:
            out[layer.dxf.name] = "#%02x%02x%02x" % ACI_RGB[aci]
        elif aci < 256:
            out[layer.dxf.name] = f"aci:{aci}"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="DXF to render")
    ap.add_argument("-o", "--out", help="write the PNG here")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--layer", help="report only this layer's colour")
    args = ap.parse_args(argv)

    out = args.out or str(Path(args.path).with_suffix(".mpl.png"))
    try:
        made = render(args.path, out, args.dpi)
    except MemoryError:
        print("FAILED: out of memory before drawing. Free RAM, do not upgrade.")
        return 2

    stats = image_stats(out)
    doc = ezdxf.readfile(args.path)
    colours = layer_colours(doc)

    print(f"file    : {args.path}")
    print(f"png     : {out}  ({made['bytes']} bytes)")
    print(f"entities: {made['entities']}")
    print(f"figure  : {made['figsize'][0]:.1f}x{made['figsize'][1]:.1f} in "
          f"@ {args.dpi} dpi")
    print(f"image   : {stats['size'][0]}x{stats['size'][1]}  "
          f"{stats['distinct_colours']} distinct colours  "
          f"{stats['painted_pct']:.1f}% painted")

    print("\nlayers and their colours:")
    for name, colour in sorted(colours.items()):
        mark = " <-- asked" if args.layer == name else ""
        print(f"  {name:16s} {colour}{mark}")

    print("\nthe colours actually on the canvas (top 8):")
    for (r, g, b), n in stats["top"]:
        print(f"  #{r:02x}{g:02x}{b:02x}  x{n}")

    if stats["distinct_colours"] <= 1:
        print("\nFAILED: the canvas is one flat colour - nothing was drawn.")
        return 1
    if stats["painted_pct"] < 0.5:
        print("\nWARNING: under 0.5% of the canvas is painted; check the extents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())