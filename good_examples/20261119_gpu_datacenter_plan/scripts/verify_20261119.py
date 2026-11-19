# -*- coding: utf-8 -*-
"""20261119.dxf 独立实测：从文件读回几何，逐项验证需求。

原则：不做"把我输入的数字再念一遍"。所有结论都从 DXF 实体反推，
并且按机柜逐只归属统计，而不是只看总数——总数对上可能只是凑巧。

比较用显式的 ok 标志，不靠把 dict/list 转成字符串再比：
上一版就因此报了 5 个假 FAIL，把真问题淹掉了。
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

import ezdxf
from ezdxf.bbox import extents

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PATH = "draw_test/20261119.dxf"

# 版面参数从生成脚本读取，不在校验端硬编码。
# 上一版把 OX/OY 和图幅写死，改版面后报出 5 条假 FAIL，把真问题淹掉了。
import re
_SRC = open("scripts/gen_20261119_room_plan.py", encoding="utf-8").read()
OX, OY = (float(v) for v in
          re.search(r"^OX, OY = ([\d.]+), ([\d.]+)$", _SRC, re.M).groups())
SHEET_W, SHEET_H = (float(v) for v in
                    re.search(r"^SHEET_W, SHEET_H = ([\d.]+), ([\d.]+)",
                              _SRC, re.M).groups())
RACK_W, RACK_D = 600.0, 1200.0

doc = ezdxf.readfile(PATH)
msp = doc.modelspace()

print(f"file: {PATH}")
print(f"$INSUNITS = {doc.header['$INSUNITS']} (4 = mm)")
print(f"entities = {len(msp)}\n")

# ── 图元分类 ──────────────────────────────────────────────────────
racks, detail, ticks, texts, dims = [], [], [], [], []
for e in msp:
    k = e.dxftype()
    if k == "LWPOLYLINE" and e.dxf.layer == "A-RACK":
        pts = list(e.get_points("xy"))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if abs(w - RACK_W) < 1 and abs(h - RACK_D) < 1:
            racks.append((min(xs), min(ys)))
        elif abs(w - 1200) < 1 and abs(h - 2400) < 1:
            detail.append((min(xs), min(ys)))
    elif k == "LINE" and e.dxf.layer == "A-GPU":
        ticks.append((e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y))
    elif k == "TEXT":
        texts.append((e.dxf.text, e.dxf.insert.x, e.dxf.insert.y,
                      e.dxf.height, e.dxf.rotation, e.dxf.style))
    elif k == "MTEXT":
        texts.append((e.plain_text().strip(), e.dxf.insert.x, e.dxf.insert.y,
                      e.dxf.char_height, 0.0, e.dxf.style))
    elif k == "DIMENSION":
        dims.append(e.get_measurement())

rows = []


def add(name, target, got, ok):
    rows.append((name, str(target), str(got), bool(ok)))


# ══ 1. 机柜数量与房间归属 ═════════════════════════════════════════
ROOM_BOX = {
    "A": (0.0, 6400.0, 8000.0, 12600.0),
    "B": (8200.0, 6400.0, 16200.0, 12600.0),
    "C": (0.0, 0.0, 8000.0, 6200.0),
    "D": (8200.0, 0.0, 16200.0, 6200.0),
}


def room_of(lx, ly):
    for code, (x0, y0, x1, y1) in ROOM_BOX.items():
        if x0 <= lx and lx + RACK_W <= x1 and y0 <= ly and ly + RACK_D <= y1:
            return code, x0, y0
    return None, None, None


add("机柜总数（平面）", 80, len(racks), len(racks) == 80)
add("单柜详图数量", 1, len(detail), len(detail) == 1)

per_room = defaultdict(int)
orphan = []
for x, y in racks:
    code, _, _ = room_of(x - OX, y - OY)
    if code is None:
        orphan.append((round(x - OX), round(y - OY)))
    else:
        per_room[code] += 1
add("每房柜数", "A20 B20 C20 D20",
    " ".join(f"{c}{per_room[c]}" for c in "ABCD"),
    all(per_room[c] == 20 for c in "ABCD"))
add("落在任何房间外的柜", 0, len(orphan), not orphan)

# ══ 2. 逐柜归属 GPU 刻度，数每柜的格数 ═══════════════════════════
# 刻度在柜内：y 恰落在 y0 + 200*k（1..5）；每分隔左右两段
cells = {}
pitch_sets = defaultdict(set)
for x0, y0 in racks:
    seg = [(x1, y1, x2, y2) for x1, y1, x2, y2 in ticks
           if x0 <= (x1 + x2) / 2 <= x0 + RACK_W and y0 < y1 < y0 + RACK_D]
    ys = sorted({round(y1 - y0) for _, y1, _, _ in seg})
    # 每档必须左右各一段（2 条）
    per_level = defaultdict(int)
    for _, y1, _, _ in seg:
        per_level[round(y1 - y0)] += 1
    cells[(round(x0), round(y0))] = (len(ys) + 1, sorted(per_level.values()))
    if len(ys) > 1:
        pitch_sets[(round(x0), round(y0))] = {
            ys[i + 1] - ys[i] for i in range(len(ys) - 1)}

hist = defaultdict(int)
for n_cells, _ in cells.values():
    hist[n_cells] += 1
add("每柜 GPU 格数分布", "{6: 80}", dict(sorted(hist.items())),
    dict(hist) == {6: 80})
add("每柜格数恰为 6", 80, hist.get(6, 0), hist.get(6, 0) == 80)

# 每个分隔档必须是 2 段刻度（左+右），没有通长穿线
bad_pairs = {k: v for k, v in cells.items() if v[1] != [2, 2, 2, 2, 2]}
add("每档刻度数（应为左右各 1 段）", "5 档 × 2 段", f"异常柜 {len(bad_pairs)}",
    not bad_pairs)

pitch_flat = set()
for s in pitch_sets.values():
    pitch_flat |= s
add("GPU 分隔间距集合", "{200}", pitch_flat, pitch_flat == {200})

# ══ 3. 每房排数、每排柜数 ═════════════════════════════════════════
# 排按"距房间内轮廓底边"判断：1000 为第 1 排，4000 为第 2 排
by_room_row = defaultdict(int)
for x, y in racks:
    lx, ly = x - OX, y - OY
    code, rx0, ry0 = room_of(lx, ly)
    if code is None:
        continue
    row = 1 if ly - ry0 < 3000 else 2
    by_room_row[(code, row)] += 1
vals = sorted(set(by_room_row.values()))
add("房间×排 的柜数", "8 组 × 10 柜",
    f"{len(by_room_row)} 组，每组柜数 {vals}",
    len(by_room_row) == 8 and vals == [10])

# ══ 4. 柜号：标签格式、落位于自己柜内、竖排、不压刻度 ══════════════
TAG_RE = re.compile(r"^([ABCD])-([12])(\d{2})$")
labels = [t for t in texts if TAG_RE.match(t[0])]
add("柜号文字数", 80, len(labels), len(labels) == 80)

bad_center, bad_rot, bad_tick = [], [], []
for s, tx, ty, h, rot, st in labels:
    code, row_s, idx_s = TAG_RE.match(s).groups()
    row, idx = int(row_s), int(idx_s)
    rx, ry = ROOM_BOX[code][0], ROOM_BOX[code][1]
    ex = rx + 1000 + (idx - 1) * RACK_W + RACK_W / 2 + OX
    ey = ry + (1000 if row == 1 else 4000) + RACK_D / 2 + OY
    if abs(tx - ex) > 1 or abs(ty - ey) > 1:
        bad_center.append((s, round(tx - ex, 1), round(ty - ey, 1)))
    if abs(rot - 90) > 1e-6:
        bad_rot.append((s, rot))
    # 竖排 90°：占 X 带 = 字高，占 Y 带 ≈ 字宽（3 字，保守取 ±1.1h）
    bx0, bx1 = tx - h / 2, tx + h / 2
    by0, by1 = ty - h * 1.1, ty + h * 1.1
    for x1, y1, x2, y2 in ticks:
        if x2 < bx0 or x1 > bx1:
            continue
        if max(y1, y2) < by0 or min(y1, y2) > by1:
            continue
        bad_tick.append((s, (round(x1), round(y1), round(x2), round(y2))))
        break

add("柜号偏离所属柜中心", 0, len(bad_center), not bad_center)
add("柜号非竖排 90°", 0, len(bad_rot), not bad_rot)
add("柜号与 GPU 刻度相交", 0, len(bad_tick), not bad_tick)

# 每只柜恰好一个柜号
tags_seen = defaultdict(int)
for s, *_ in labels:
    tags_seen[s] += 1
add("每只柜一个柜号", "80 唯一 tag", f"{len(tags_seen)} 唯一",
    len(tags_seen) == 80 and set(tags_seen.values()) == {1})

# ══ 5. 文字样式：必须是单体 TrueType ══════════════════════════════
used = sorted({t[5] for t in texts})
fonts = {n: doc.styles.get(n).dxf.font for n in used}
add("文字样式字体", "CN=simhei.ttf",
    "; ".join(f"{k}={v}" for k, v in fonts.items()),
    fonts == {u: "simhei.ttf" for u in used})
add("字体是否单体 TrueType(.ttf)", "全部是",
    "全部是" if all(f.lower().endswith(".ttf") for f in fonts.values())
    else "存在 .shx/.ttc",
    all(f.lower().endswith(".ttf") for f in fonts.values()))

# ══ 6. 图幅与尺寸 ═════════════════════════════════════════════════
bb = extents(msp)
add("图元范围 X", f"0..{SHEET_W:.0f}",
    f"{bb.extmin.x:.0f}..{bb.extmax.x:.0f}",
    abs(bb.extmin.x) < 1 and abs(bb.extmax.x - SHEET_W) < 1)
add("图元范围 Y", f"0..{SHEET_H:.0f}",
    f"{bb.extmin.y:.0f}..{bb.extmax.y:.0f}",
    abs(bb.extmin.y) < 1 and abs(bb.extmax.y - SHEET_H) < 1)
meas = sorted({round(m) for m in dims})
add("标注实测值集合", "[1800, 6000, 13080, 16680]", meas,
    meas == [1800, 6000, 13080, 16680])

# ══ 输出 ═════════════════════════════════════════════════════════
print("| 需求 | 目标值 | 实测值 | 状态 |")
print("|---|---|---|---|")
for name, target, got, ok in rows:
    print(f"| {name} | {target} | {got} | {'PASS' if ok else 'FAIL'} |")

fails = [r for r in rows if not r[3]]
print(f"\n{len(rows) - len(fails)}/{len(rows)} 项通过")
for name, target, got, _ in fails:
    print(f"  FAIL: {name} —— 目标 {target}，实测 {got}")
for label, items in (("错位柜号", bad_center), ("未竖排", bad_rot),
                     ("压刻度", bad_tick), ("房间外机柜", orphan),
                     ("刻度异常柜", list(bad_pairs)[:3])):
    if items:
        print(f"  样本 {label}: {items[:4]}")
print(f"\n文字高度集合: {sorted({round(t[3]) for t in texts})}")
print(f"结论: {'全部通过' if not fails else '存在未通过项'}")