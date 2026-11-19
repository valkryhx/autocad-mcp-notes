"""Render a DXF to SVG through ezdxf's own backend, and read the colours back.

Why this exists: `view_zoom_and_screenshot` returns a blank picture for a live
AutoCAD document on this machine. Measured 2026-11-19: both `source: "window"`
and `source: "export_snapshot"` came back empty, and a direct GDI `GetPixel` on
AutoCAD's frame read `RGB(255,255,255)` - the drawing area is GPU-composited and
is not on the GDI surface. There is no way to photograph that window.

The SVG backend does not need the window at all: it renders the DXF's own
geometry and the layer table's colours. That makes it the right tool for "is
layer X the colour I set, and how many entities use it" - a question worth
answering precisely, unlike "does this look right to a human", which only the
operator can answer.

What it CANNOT do: show glyph problems. A missing font makes ezdxf fall back
silently, so a `m²` that AutoCAD refuses to draw still renders here. Judging
text display still needs the operator's eyes.

    python scripts/render_svg.py FILE.dxf [-o out.svg]
    python scripts/render_svg.py FILE.dxf --layer A-FURN-E-N
    python scripts/render_svg.py FILE.dxf --expect A-FURN-E-N=#ff7f00

`--expect LAYER=#rrggbb` exits 1 when the layer's colour in the SVG is not that
value - a check a build can gate on, unlike an eyeball.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ezdxf pulls in numpy, whose bundled OpenBLAS aborts when it cannot reserve its
# default thread arenas. One thread apiece keeps it inside a normal process.
import os

for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(var, "1")

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
from ezdxf.addons.drawing.layout import Page
from ezdxf.addons.drawing.svg import SVGBackend

#: ACI -> sRGB, for the palette entries this project uses. AutoCAD's full palette
#: is larger; these are the ones a layer set picks from.
ACI_RGB = {
    1: "#ff0000", 2: "#ffff00", 3: "#00ff00", 4: "#00ffff",
    5: "#0000ff", 6: "#ff00ff", 7: "#ffffff", 8: "#808080", 9: "#c0c0c0",
    30: "#ff7f00", 40: "#ffbf00", 250: "#333333", 251: "#505050",
    252: "#696969", 253: "#828282", 254: "#bebebe",
}


def render(path: str, page: tuple[float, float] = (297.0, 210.0)) -> str:
    doc = ezdxf.readfile(path)
    backend = SVGBackend()
    config = Configuration(background_policy=BackgroundPolicy.BLACK)
    Frontend(RenderContext(doc), backend, config=config).draw_layout(
        doc.modelspace(), finalize=True
    )
    return backend.get_string(Page(*page))


def svg_colours(svg: str) -> dict[str, int]:
    """Every colour the SVG defines, with how many elements use it.

    ezdxf writes the colours once into `<defs><style>` as CSS classes and
    references them by class, so counting hex codes in the body would report
    zero. The class table is the honest source: class -> colour, then the body
    count of `class="Cn"`.
    """
    class_to_colour: dict[str, str] = {}
    for match in re.finditer(
        r"\.(C\d+)\s*\{[^}]*?(?:stroke|fill):\s*(#[0-9a-fA-F]{6})", svg
    ):
        cls, colour = match.group(1), match.group(2).lower()
        class_to_colour.setdefault(cls, colour)

    counts: Counter[str] = Counter()
    for cls, colour in class_to_colour.items():
        n = svg.count(f'class="{cls}"')
        if n:
            counts[colour] += n
    return dict(counts)


def layer_colours(doc) -> dict[str, str]:
    """Layer name -> #rrggbb, from the ACI table."""
    out = {}
    for layer in doc.layers:
        aci = layer.dxf.color
        if aci in ACI_RGB:
            out[layer.dxf.name] = ACI_RGB[aci]
        elif aci < 256:
            # ACI 10..249: the 24-hue wheel, 10 steps of brightness. Approximated
            # only where it matters (a check would otherwise silently skip it).
            out[layer.dxf.name] = f"aci:{aci}"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="DXF to render")
    ap.add_argument("-o", "--out", help="write the SVG here")
    ap.add_argument("--layer", help="report only this layer's colour")
    ap.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="LAYER=#rrggbb",
        help="exit 1 unless this layer renders in that colour (repeatable)",
    )
    ap.add_argument("--page", default="297x210", help="page size in mm, WxH")
    args = ap.parse_args(argv)

    page = tuple(float(v) for v in args.page.lower().split("x"))
    svg = render(args.path, page)

    out = args.out
    if out is None:
        out = str(Path(args.path).with_suffix(".svg"))
    Path(out).write_text(svg, encoding="utf-8")

    doc = ezdxf.readfile(args.path)
    colours = layer_colours(doc)
    used = svg_colours(svg)

    print(f"file   : {args.path}")
    print(f"svg    : {out}  ({len(svg)} bytes)")
    print(f"paths  : {svg.count('<path')}   text elements: {svg.count('<text')}")

    print("\nlayers and their colours:")
    for name, colour in sorted(colours.items()):
        n = used.get(colour, 0)
        shown = f"{n} element(s)" if n else "no element"
        mark = " <-- asked" if args.layer == name else ""
        print(f"  {name:16s} {colour:9s} {shown}{mark}")

    print("\ncolours the SVG actually draws:")
    for colour, n in sorted(used.items(), key=lambda kv: -kv[1]):
        print(f"  {colour}  x{n}")

    if not svg.count("<text"):
        print(
            "\nnote: no <text> element - ezdxf outlines text into <path>, so the"
            "\n      absence is normal. It also means a missing-glyph problem does"
            "\n      NOT show here; only the operator's screen shows that."
        )

    failures = []
    for item in args.expect:
        if "=" not in item:
            ap.error(f"--expect wants LAYER=#rrggbb, got {item!r}")
        name, want = item.split("=", 1)
        want = want.lower()
        got = colours.get(name)
        # The layer's colour may be defined but unused (empty layer); the
        # assertion is about the layer, not about entities on it.
        ok = got == want
        print(f"\n{'PASS' if ok else 'FAIL'}  {name}: want {want}, layer table says {got}")
        if not ok:
            failures.append(name)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())