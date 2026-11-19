# -*- coding: utf-8 -*-
"""20261119.dxf 版面分区检查：各内容块互不重叠。

为什么需要这个：文字交叠检查只管文字压文字 / 文字压线，不管
"几何压几何"。这一轮真实踩到——单柜详图整个画在标题栏上面，
`tools.text_overlap` 报 0 findings，只有看图才看得出来。
所以版面块级重叠必须单独验。

块＝一组图层+位置上的内容。这里按"版面区块"定义矩形，互相测交叠。
"""
from __future__ import annotations

import sys

import ezdxf
from ezdxf.bbox import extents

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PATH = "draw_test/20261119.dxf"
SHEET_W, SHEET_H = 29700.0, 21000.0
M = 1250.0
doc = ezdxf.readfile(PATH)
msp = doc.modelspace()


def block_box(layers, x_range=None, y_range=None):
    """某些图层上、落在给定范围内的图元的合并包围盒。"""
    pts = []
    for e in msp:
        if e.dxf.layer not in layers:
            continue
        try:
            b = extents([e])
        except Exception:
            continue
        cx = (b.extmin.x + b.extmax.x) / 2
        cy = (b.extmin.y + b.extmax.y) / 2
        if x_range and not (x_range[0] <= cx <= x_range[1]):
            continue
        if y_range and not (y_range[0] <= cy <= y_range[1]):
            continue
        pts.append((b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y))
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[2] for p in pts), max(p[3] for p in pts))


def overlap(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1, (x1 - x0) * (y1 - y0))


# 版面区块：按内容性质 + 位置分组。
# y_range 必须收到该块的**真实**跨度，切太宽会把邻块吞进来误报
# （配置表曾用 6600..12000，把详图标题 13864 之外的空白也算成了表）。
BLOCKS = {
    "图名区":    dict(layers={"A-TITLE", "A-TEXT"}, y_range=(17400, 21000)),
    "平面图":    dict(layers={"A-RACK", "A-WALL", "A-WALL-IN", "A-CHANNEL"},
                      x_range=(0, 19800), y_range=(4000, 17800)),
    "图例":      dict(layers={"A-TITLE", "A-TEXT", "A-RACK", "A-GPU",
                             "A-CHANNEL"},
                      x_range=(0, 19800), y_range=(2000, 4000)),
    "设计说明":  dict(layers={"A-TITLE", "A-TEXT"},
                      x_range=(19900, 29000), y_range=(14500, 17800)),
    "配置表":    dict(layers={"A-TABLE", "A-TITLE", "A-TEXT"},
                      x_range=(19900, 29000), y_range=(6800, 9900)),
    "单柜详图":  dict(layers={"A-RACK", "A-GPU", "A-TITLE", "A-TEXT"},
                      x_range=(19900, 29000), y_range=(10800, 14200)),
    "标题栏":    dict(layers={"A-TITLE", "A-TEXT"},
                      x_range=(19400, 29000), y_range=(M, 4300)),
}

print(f"file: {PATH}\n")
boxes = {}
for name, spec in BLOCKS.items():
    b = block_box(spec["layers"], spec.get("x_range"), spec.get("y_range"))
    boxes[name] = b
    if b:
        print(f"  {name:<9} X {b[0]:>6.0f}..{b[2]:<6.0f} "
              f"Y {b[1]:>6.0f}..{b[3]:<6.0f}")
    else:
        print(f"  {name:<9} <空>")

print("\n块间交叠：")
names = [n for n, b in boxes.items() if b]
bad = []
for i, a in enumerate(names):
    for b in names[i + 1:]:
        ov = overlap(boxes[a], boxes[b])
        if ov:
            bad.append((a, b, ov))
            print(f"  × {a} 与 {b} 交叠 "
                  f"X {ov[0]:.0f}..{ov[2]:.0f} Y {ov[1]:.0f}..{ov[3]:.0f} "
                  f"面积 {ov[4]:.0f}")

print(f"\n图框内边 X {M}..{SHEET_W - M}  Y {M}..{SHEET_H - M}")
out = [(n, b) for n, b in boxes.items() if b and (
    b[0] < M - 1 or b[1] < M - 1 or b[2] > SHEET_W - M + 1
    or b[3] > SHEET_H - M + 1)]
for n, b in out:
    print(f"  × {n} 越出版心: X {b[0]:.0f}..{b[2]:.0f} Y {b[1]:.0f}..{b[3]:.0f}")

print(f"\n结论: {'版面分区无交叠、无越框' if not bad and not out else '存在版面容斥问题'}")
sys.exit(0 if not bad and not out else 1)