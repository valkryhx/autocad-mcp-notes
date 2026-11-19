# -*- coding: utf-8 -*-
"""20261119 GPU 机房平面布置图 —— 几何生成器

需求（用户 2026-11-19 提出）：
  4 个房间，每个房间 2 排机架，每个机架上 6 块 GPU。
  图名 20261119。

设计说明：
  · 比例 1:50，A1 图幅 (841×594 mm) → 模型空间 42050 × 29700 mm。
  · 机房内净尺寸 8000(X) × 6200(Y)；两排机柜面对面，中间 1800 封闭冷通道。
  · 单柜 600×1200，每排 10 柜；单柜沿进深分 6 格 = 6 台 GPU 服务器。
  · 全部文字使用 TrueType 样式 CN (simhei.ttf)——单体 .ttf，PDF 可嵌入。
  · 文字一律排在机柜/墙线之外的空白带内，绘图阶段就保证不压线、不互压；
    文字交叠检查是用来事后证明的，不是用来兜底的。

坐标：脚本内部用"平面局部坐标"，P() 统一加图纸偏移 (OX, OY)。
"""
from __future__ import annotations

import os
import sys

import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "draw_test", "20261119.dxf")

# ══════════════════════════════════════════════════════════════════
#  图纸与样式
# ══════════════════════════════════════════════════════════════════
DOC = ezdxf.new("R2018", setup=True)
DOC.header["$INSUNITS"] = 4          # mm
DOC.header["$LUNITS"] = 2
DOC.header["$LTSCALE"] = 50.0        # 虚线在 1:50 出图时可见
DOC.header["$MEASUREMENT"] = 1
MSP = DOC.modelspace()

STYLE = "CN"
DOC.styles.add(STYLE, font="simhei.ttf")     # 单体 ttf；.ttc 无法嵌入 PDF

LAYERS = {
    "A-FRAME":   (7, 50, "Continuous"),   # 图框
    "A-WALL":    (7, 50, "Continuous"),   # 墙体
    "A-WALL-IN": (7, 35, "Continuous"),   # 内隔墙
    "A-RACK":    (4, 25, "Continuous"),   # 机柜
    "A-GPU":     (30, 18, "Continuous"),  # GPU 单元分隔
    "A-CHANNEL": (3, 18, "DASHED"),       # 封闭冷通道
    "A-TEXT":    (7, 18, "Continuous"),   # 文字
    "A-DIM":     (2, 13, "Continuous"),   # 尺寸
    "A-TITLE":   (7, 35, "Continuous"),   # 标题栏 / 图名
    "A-TABLE":   (7, 18, "Continuous"),   # 配置表（COM 建表要这个层先存在）
    "A-EQUIP":   (2, 35, "Continuous"),   # 图例几何
}
for name, (color, lw, lt) in LAYERS.items():
    lay = DOC.layers.add(name, color=color, linetype=lt)
    lay.dxf.lineweight = lw

dimstyle = DOC.dimstyles.duplicate_entry("EZDXF", "ISO50")
dimstyle.dxf.dimtxt = 2.5
dimstyle.dxf.dimasz = 2.0
dimstyle.dxf.dimexe = 2.5
dimstyle.dxf.dimexo = 2.0
dimstyle.dxf.dimgap = 1.0
dimstyle.dxf.dimdec = 0
dimstyle.dxf.dimscale = 50.0
# EZDXF 模板的 dimlfac 是 100（给模板自带的毫米/厘米示例用的）。
# 继承过来会把 16680 显示成 1668000 —— 实测 drawing_critique 报
# dim_dimlfac_scaled。本图模型单位就是 mm，比例由 dimscale 承担。
dimstyle.dxf.dimlfac = 1.0

# ══════════════════════════════════════════════════════════════════
#  基元
# ══════════════════════════════════════════════════════════════════
# 平面局部坐标 → 图纸坐标。
# A2 版面（29700×21000）的实测分区，别凭感觉改：
#   图名       y 18250..19750
#   平面       y 4380..17000   ← OY + (OY0..OY1) = 6400 + (-240..12840)
#   图例       y 2600..5600（平面左下的走道空白带）
#   右栏       x 20050..27200，自上而下：说明 / 配置表 / 详图
OX, OY = 2360.0, 4620.0


def P(x, y):
    return (x + OX, y + OY)


def rect(x1, y1, x2, y2, layer, local=True):
    if local:
        x1, y1 = P(x1, y1)
        x2, y2 = P(x2, y2)
    return MSP.add_lwpolyline([(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                              close=True, dxfattribs={"layer": layer})


def line(x1, y1, x2, y2, layer, local=True):
    if local:
        x1, y1 = P(x1, y1)
        x2, y2 = P(x2, y2)
    return MSP.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})


def txt(s, x, y, h, layer="A-TEXT", rot=0.0, local=True, align="center"):
    """单行 TEXT，垂直居中。align: center / left / right。

    对齐态必须成对写全：只设 valign=2 而留 halign=0 是一种**混合对齐态**，
    DXF 里合法但语义模糊 —— AutoCAD 打开时会把插入点从组码 10 挪到组码 11，
    而 ezdxf 的测量代码按 `-(low+high)/2` 居中于组码 10，两者差半个字高。
    实测后果：同一份图，DXF 报 0 交叠、DWG 报 1 条，而且是真的差了 70 单位。
    所以这里一律走 set_placement 给出完整的 (halign, valign) 组合。
    """
    if local:
        x, y = P(x, y)
    ent = MSP.add_text(s, dxfattribs={
        "style": STYLE, "height": h, "layer": layer, "rotation": rot,
    })
    ent.set_placement((x, y), align={
        "center": TextEntityAlignment.MIDDLE_CENTER,
        "left": TextEntityAlignment.MIDDLE_LEFT,
        "right": TextEntityAlignment.MIDDLE_RIGHT,
    }[align])
    return ent


def mtext(s, x, y, h, layer="A-TEXT", width=0.0, local=True, attach=1):
    if local:
        x, y = P(x, y)
    mt = MSP.add_mtext(s, dxfattribs={
        "style": STYLE, "char_height": h, "layer": layer, "width": width,
    })
    mt.set_location((x, y), attachment_point=attach)
    return mt


def dim_h(x1, x2, y_base, y_from, layer="A-DIM"):
    d = MSP.add_linear_dim(base=P((x1 + x2) / 2, y_base),
                           p1=P(x1, y_from), p2=P(x2, y_from),
                           angle=0, dimstyle="ISO50",
                           dxfattribs={"layer": layer})
    d.render()
    return d


def dim_v(y1, y2, x_base, x_from, layer="A-DIM"):
    d = MSP.add_linear_dim(base=P(x_base, (y1 + y2) / 2),
                           p1=P(x_from, y1), p2=P(x_from, y2),
                           angle=90, dimstyle="ISO50",
                           dxfattribs={"layer": layer})
    d.render()
    return d


# ══════════════════════════════════════════════════════════════════
#  建筑（平面局部坐标）
# ══════════════════════════════════════════════════════════════════
T_EXT = 240.0            # 外墙厚
T_INT = 200.0            # 内隔墙厚

AX0, AX1 = 0.0, 8000.0           # 左列机房 A/C 内轮廓 X
BX0, BX1 = 8200.0, 16200.0       # 右列机房 B/D 内轮廓 X
CY0, CY1 = 0.0, 6200.0           # 下排机房 C/D 内轮廓 Y
AY0, AY1 = 6400.0, 12600.0       # 上排机房 A/B 内轮廓 Y

OX0, OX1 = AX0 - T_EXT, BX1 + T_EXT      # -240 .. 16440
OY0, OY1 = CY0 - T_EXT, AY1 + T_EXT      # -240 .. 12840

rect(OX0, OY0, OX1, OY1, "A-WALL")       # 外墙（外皮）
rect(AX0, CY0, BX1, AY1, "A-WALL")       # 外墙（内皮）
rect(AX1, CY0, BX0, AY1, "A-WALL-IN")    # 竖向内隔墙
rect(AX0, CY1, BX1, AY0, "A-WALL-IN")    # 横向内隔墙

# ══════════════════════════════════════════════════════════════════
#  机柜布置：每房 2 排 × 10 柜，单柜 6 格 GPU
# ══════════════════════════════════════════════════════════════════
RACK_W, RACK_D = 600.0, 1200.0
N_RACK = 10
ROW_LEN = RACK_W * N_RACK              # 6000
N_GPU = 6
GPU_PITCH = RACK_D / N_GPU             # 200

RACK_X0 = 1000.0                       # 机柜起始 X（左侧留 1000 走道）
ROW1_Y = 1000.0                        # 下排机柜底面（后侧留 1000 走道）
ROW2_Y = 4000.0                        # 上排机柜底面
COLD_Y0, COLD_Y1 = ROW1_Y + RACK_D, ROW2_Y     # 2200 .. 4000
GPU_TICK = 90.0                        # GPU 分隔线自柜边伸入长度

ROOMS = [
    ("A", (AX0, AY0)),
    ("B", (BX0, AY0)),
    ("C", (AX0, CY0)),
    ("D", (BX0, CY0)),
]

all_racks = []


def room_geometry(code, ox, oy):
    """在房间内轮廓左下角 (ox, oy) 处画 2 排 × 10 柜。

    这里的坐标仍是"平面局部坐标"（已含房间位移，但未加 OX/OY），
    所以所有基元都用 local=True —— 写成 local=False 会让整个房间漏掉图纸偏移。
    """
    for row in (1, 2):
        y0 = ROW1_Y if row == 1 else ROW2_Y
        for i in range(1, N_RACK + 1):
            x0 = ox + RACK_X0 + (i - 1) * RACK_W
            yb = oy + y0
            tag = f"{code}-{row}{i:02d}"
            rect(x0, yb, x0 + RACK_W, yb + RACK_D, "A-RACK")
            # 6 格 GPU 分隔：只画贴着柜内壁的短刻度。
            # 柜号竖排 90°，占柜宽中线 x 300±62，刻度止于 x 150 / 起于 x 450，
            # 两者不交；若柜号横排则要 375 宽，必然压线。
            for g in range(1, N_GPU):
                gy = yb + g * GPU_PITCH
                line(x0 + 60, gy, x0 + 60 + GPU_TICK, gy, "A-GPU")
                line(x0 + RACK_W - 60 - GPU_TICK, gy,
                     x0 + RACK_W - 60, gy, "A-GPU")
            t = txt(tag, x0 + RACK_W / 2, yb + RACK_D / 2, 125,
                    "A-TEXT", rot=90)
            all_racks.append((tag, t))

    # 封闭冷通道
    rect(ox + RACK_X0, oy + COLD_Y0, ox + RACK_X0 + ROW_LEN, oy + COLD_Y1,
         "A-CHANNEL")


for code, (rx, ry) in ROOMS:
    room_geometry(code, rx, ry)

    # 房间名 + 配置：冷通道正中，两行间距 400（远大于两行半高之和 188）
    cx = rx + RACK_X0 + ROW_LEN / 2
    cy = ry + (COLD_Y0 + COLD_Y1) / 2
    txt(f"机房 {code}", cx, cy + 210, 250, "A-TEXT")
    txt("2 排 × 10 柜 · 6 GPU/柜", cx, cy - 190, 125, "A-TEXT")

    # 排号：左侧 1000 走道内，旋转 90
    for row, y0 in ((1, ROW1_Y), (2, ROW2_Y)):
        txt(f"{code}{row} 排", rx + RACK_X0 / 2, ry + y0 + RACK_D / 2, 125,
            "A-TEXT", rot=90)

# ══════════════════════════════════════════════════════════════════
#  单柜详图（1:25 = 平面 1:50 的 2 倍）
#
#  位置经过实测修正：原先放在 DT_Y=3400，详图 Y 3400..5800 直接压在
#  标题栏（Y 1250..4250）上面 —— 交叠检查只查文字，报不出来，是看图发现的。
#  右栏自下而上：标题栏 1250..4250 / 配置表 6920..9200 / 详图 11000..13400
#  / 设计说明 14694..17380，四块互不相交。
# ══════════════════════════════════════════════════════════════════
DT_X, DT_Y = 20050.0, 11000.0     # 详图左下角（图纸坐标）
K = 2.0

txt("单柜详图  1:25", DT_X, DT_Y + RACK_D * K + 600, 190, "A-TITLE",
    local=False, align="left")
rect(DT_X, DT_Y, DT_X + RACK_W * K, DT_Y + RACK_D * K, "A-RACK", local=False)
for g in range(1, N_GPU):
    gy = DT_Y + g * GPU_PITCH * K
    line(DT_X, gy, DT_X + RACK_W * K, gy, "A-GPU", local=False)
for g in range(N_GPU):
    gy = DT_Y + (g + 0.5) * GPU_PITCH * K
    txt(f"GPU-{g + 1:02d}", DT_X + RACK_W * K / 2, gy, 70, "A-TEXT",
        local=False)
txt("（前维护面）", DT_X + RACK_W * K / 2, DT_Y - 420, 110, "A-TEXT",
    local=False)
# 详图旁注：放在详图右侧、且在详图自身的 Y 跨度内
for k, s in enumerate(("机柜 600×1200×2200", "单柜 6 台 GPU 服务器",
                       "前维护 · 上走线")):
    txt(s, DT_X + RACK_W * K + 800, DT_Y + 2000 - k * 420, 140,
        "A-TEXT", local=False, align="left")

# ══════════════════════════════════════════════════════════════════
#  尺寸（图外 / 走道空白带内）
# ══════════════════════════════════════════════════════════════════
dim_h(OX0, OX1, OY0 - 1000, OY0)                 # 总宽 16680
dim_v(OY0, OY1, OX0 - 1000, OX0)                 # 总高 13080
dim_h(AX0 + RACK_X0, AX0 + RACK_X0 + ROW_LEN,     # 一排机柜长 6000
      CY0 + 520, CY0 + ROW1_Y)
dim_v(AY0 + COLD_Y0, AY0 + COLD_Y1,               # 冷通道净宽 1800
      BX1 - 300, BX1 - 500)

# ══════════════════════════════════════════════════════════════════
#  图框 / 图名 / 图例 / 说明 / 标题栏（图纸坐标）
#
#  图幅选 A2 而不是 A1：1:50 下建筑 16680×13080，A1(42050×29700) 只用到
#  44% 宽，右栏三块内容被迫散落，纸面大片空白 —— 实测各层包围盒后改的。
#  A2 @ 1:50 = 29700×21000，平面占 56%×62%，右栏 9410 宽正好竖排三块。
# ══════════════════════════════════════════════════════════════════
SHEET_W, SHEET_H = 29700.0, 21000.0     # A2 @ 1:50
M = 1250.0                               # 装订边 25 mm
rect(0, 0, SHEET_W, SHEET_H, "A-FRAME", local=False)
rect(M, M, SHEET_W - M, SHEET_H - M, "A-FRAME", local=False)

# ── 图名（图框内左上，平面图上方）─────────────────────────────────
txt("20261119 GPU 机房平面布置图", M + 900, SHEET_H - M - 1500, 380,
    "A-TITLE", local=False, align="left")
txt("4 机房 × 2 排 × 10 柜 × 6 GPU = 480 块 GPU　　比例 1:50　　单位 mm",
    M + 900, SHEET_H - M - 2150, 140, "A-TEXT", local=False, align="left")

# ── 图例（平面正下方；平面底边 y=4380，标注占 4380-1000，图例放 1500..3600）
LG_X, LG_Y = 2360.0, 2600.0
txt("图例", LG_X, LG_Y + 940, 190, "A-TITLE", local=False, align="left")
LG_ITEMS = [
    ("A-RACK", "机柜 600×1200×2200"),
    ("A-GPU", "GPU 单元分隔（单柜 6 台）"),
    ("A-CHANNEL", "封闭冷通道（净宽 1800）"),
]
for k, (layer, label) in enumerate(LG_ITEMS):
    y = LG_Y + 480 - k * 340
    if layer == "A-CHANNEL":
        MSP.add_lwpolyline([(LG_X, y - 90), (LG_X + 420, y - 90),
                            (LG_X + 420, y + 90), (LG_X, y + 90)],
                           close=True, dxfattribs={"layer": layer})
    else:
        rect(LG_X, y - 90, LG_X + 420, y + 90, layer, local=False)
        if layer == "A-GPU":
            for g in (1, 2, 3):
                gy = y - 90 + g * 45
                line(LG_X, gy, LG_X + 90, gy, layer, local=False)
                line(LG_X + 330, gy, LG_X + 420, gy, layer, local=False)
    txt(label, LG_X + 640, y, 140, "A-TEXT", local=False, align="left")

# ── 设计说明（右栏上部，通栏到版心右缘）──────────────────────────
#     实测右栏 x>23250 有 8 条横向带全空 —— 说明宽 8600 只铺到 28650 的
#     一半宽度。加宽到 9100 并左移到版心边界，配合下面的表格一起铺满。
NT_X, NT_Y = 20050.0, 15800.0
NT_W = SHEET_W - M - NT_X - 300       # 到版心右缘，留 300 余量
txt("设计说明", NT_X, NT_Y + 1450, 190, "A-TITLE", local=False,
    align="left")
mt = mtext(
    "1. 本图为 20261119 GPU 机房平面布置图，比例 1:50，尺寸单位 mm。\n"
    "2. 共 4 个机房（A/B/C/D），单房 2 排机架 × 10 柜，全场共 80 柜。\n"
    "3. 单柜 6 台 GPU 服务器，全场共 480 块 GPU。\n"
    "4. 两排机柜面对面布置，中间为 1800 宽封闭冷通道。\n"
    "5. 机柜 600×1200×2200，前维护，采用上走线方式。\n"
    "6. 单柜功率 8 kW，全场 IT 负荷 640 kW。\n"
    "7. 走道净宽：后侧 1000，两侧 1000，均满足维护要求。",
    NT_X, NT_Y + 1250, 135, "A-TEXT", width=NT_W, local=False)
mt.dxf.line_spacing_factor = 1.6

# ══════════════════════════════════════════════════════════════════
#  机房配置表（用网格线 + TEXT 画，不依赖 TEXT 表格实体）
#
#  为什么不用原生 AcDbTable：ezdxf 1.4.4 没有 TABLE 写出 API，只能经
#  AutoCAD COM 的 AddTable 建；而 COM 在这一轮反复出现 RPC/保存失败、
#  文件锁与 <unknown>.Count，建表这一步成了整条流水线最脆的环节。
#  用网格线画的表在 DXF 里是普通 LWPOLYLINE + TEXT，任何引擎都能读写，
#  文字照样进得了交叠检查（原生 TABLE 的单元格在 *T 块里，检查反而更绕）。
# ══════════════════════════════════════════════════════════════════
TB_X, TB_Y = 20050.0, 9200.0         # 表左上角（图纸坐标，说明下方）
# 5 列合计铺到版心右缘（SHEET_W - M = 28450），而不是停在 28150
TB_COL_W = (1700.0, 1500.0, 1700.0, 1700.0, 1800.0)   # 合计 8400
TB_ROW_H = 380.0
TB_TXT_H = 130.0
TB_ROWS = [
    ["机房", "排数", "机柜数", "GPU 数", "功率 (kW)"],
    ["A", "2", "20", "120", "160"],
    ["B", "2", "20", "120", "160"],
    ["C", "2", "20", "120", "160"],
    ["D", "2", "20", "120", "160"],
    ["合计", "8", "80", "480", "640"],
]
TB_W = sum(TB_COL_W)
TB_H = TB_ROW_H * len(TB_ROWS)

# 表格锚点是左上角 TB_Y，向下生长到 TB_Y - TB_H。
# 表标题必须贴在表头上方：TB_Y + 500。写成 TB_Y + TB_H + 500 会让标题
# 浮在表格上方 2780 处，跟表格脱开 —— 实测包围盒看出来的。
txt("机房配置表", TB_X, TB_Y + 500, 200, "A-TITLE", local=False,
    align="left")

# 外框 + 内部分隔线（左上角锚点，向下生长）
rect(TB_X, TB_Y - TB_H, TB_X + TB_W, TB_Y, "A-TABLE", local=False)
cy = TB_Y
for r in range(1, len(TB_ROWS)):
    cy -= TB_ROW_H
    line(TB_X, cy, TB_X + TB_W, cy, "A-TABLE", local=False)
cx = TB_X
for c in range(1, len(TB_COL_W)):
    cx += TB_COL_W[c - 1]
    line(cx, TB_Y, cx, TB_Y - TB_H, "A-TABLE", local=False)

# 单元格文字：居中，行高 360 ≫ 字高 120，不与网格线相交
for r, row in enumerate(TB_ROWS):
    cy = TB_Y - r * TB_ROW_H - TB_ROW_H / 2
    cx = TB_X
    for c, val in enumerate(row):
        txt(val, cx + TB_COL_W[c] / 2, cy, TB_TXT_H, "A-TEXT", local=False)
        cx += TB_COL_W[c]

# ── 标题栏（右下）────────────────────────────────────────────────
TBW, TBH = 9000.0, 3000.0                  # 名称与配置表区分开
TBX = SHEET_W - M - TBW
TBY = M
rect(TBX, TBY, TBX + TBW, TBY + TBH, "A-TITLE", local=False)
line(TBX, TBY + 1000, TBX + TBW, TBY + 1000, "A-TITLE", local=False)
line(TBX, TBY + 2000, TBX + TBW, TBY + 2000, "A-TITLE", local=False)
line(TBX + 4500, TBY, TBX + 4500, TBY + 2000, "A-TITLE", local=False)

txt("20261119 GPU 机房平面布置图", TBX + 4500, TBY + 2500, 220,
    "A-TITLE", local=False)
for r, (k, v) in enumerate((("设计", "valkryhx"), ("制图", "Claude"))):
    y = TBY + 1500 - r * 1000
    txt(k, TBX + 200, y, 140, "A-TEXT", local=False, align="left")
    txt(v, TBX + 1400, y, 140, "A-TEXT", local=False, align="left")
for r, (k, v) in enumerate((("图号", "20261119"), ("比例", "1:50"))):
    y = TBY + 1500 - r * 1000
    txt(k, TBX + 4700, y, 140, "A-TEXT", local=False, align="left")
    txt(v, TBX + 5900, y, 140, "A-TEXT", local=False, align="left")

# ══════════════════════════════════════════════════════════════════
#  保存
# ══════════════════════════════════════════════════════════════════
os.makedirs(os.path.dirname(OUT), exist_ok=True)
DOC.saveas(OUT)

n_text = sum(1 for e in MSP if e.dxftype() == "TEXT")
n_mtext = sum(1 for e in MSP if e.dxftype() == "MTEXT")
print(f"saved: {OUT}")
print(f"entities: {len(MSP)}")
print(f"rooms: {len(ROOMS)}  racks: {len(all_racks)}  gpu/rack: {N_GPU}  "
      f"total GPU: {len(all_racks) * N_GPU}")
print(f"texts: {n_text} TEXT + {n_mtext} MTEXT")