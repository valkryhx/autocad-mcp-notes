# -*- coding: utf-8 -*-
"""GPU 智算中心机房平面布置图 —— 几何生成器 (v3)

设计依据：
  GB 50174-2017《数据中心设计规范》
  T/GYJS 011-2025《智算中心设计规范》
  华为 AIDC 机房参考设计白皮书 / Vertiv 智算中心基础设施演进白皮书

规模：100 台 GPU 机柜（10 排 x 10 台），单柜 12 kW，IT 总负荷 1200 kW
      5 台精密空调（4+1 冗余），UPS 2N，独立电池室，监控值班室

坐标 mm；图幅 A1 (841x594)，出图 1:100 → 模型空间 84100 x 59400
所有文字均置于空白带内，不压图线。
"""
import ezdxf

DOC = ezdxf.new("R2018", setup=True)
DOC.header["$INSUNITS"] = 4
DOC.header["$LUNITS"] = 2
DOC.header["$DIMASSOC"] = 2
MSP = DOC.modelspace()

# 必须用单体 .ttf（simhei.ttf），不要用 .ttc 集合字体（simsun.ttc）。
# 实测：.ttc 在 PLOT 出 PDF 时文字被炸成几何线段（内容流 0 个文字指令），
# PDF 显示 "???" 且位置错位；.ttf 才能正常嵌入字形。
DOC.styles.add("CN", font="simhei.ttf")

LAYERS = {
    "A-WALL":     (7, 50, "Continuous"),
    "A-WALL-IN":  (7, 35, "Continuous"),
    "A-AXIS":     (1, 13, "CENTER"),
    "E-RACK":     (4, 25, "Continuous"),
    "E-RACK-PDU": (30, 25, "Continuous"),
    "E-CRAC":     (3, 35, "Continuous"),
    "E-UPS":      (2, 35, "Continuous"),
    "E-BATT":     (6, 25, "Continuous"),
    "A-FURN":     (8, 18, "Continuous"),
    "A-TEXT":     (7, 18, "Continuous"),
    "A-DIM":      (2, 13, "Continuous"),
    "A-TABLE":    (7, 18, "Continuous"),
    "A-HATCH":    (4, 13, "Continuous"),
    "A-FRAME":    (7, 50, "Continuous"),
    "A-TITLE":    (7, 35, "Continuous"),
    "A-DOOR":     (3, 25, "Continuous"),
}
for name, (color, lw, lt) in LAYERS.items():
    lay = DOC.layers.add(name, color=color, linetype=lt)
    lay.dxf.lineweight = lw

# ══ 版面偏移：平面图居中偏左（纸面中心 ~238mm），右侧留给表格 ═══════
# plan 坐标范围 X -2800..22000, Y -15600..18600 (含轴号与尺寸)
# 目标纸面范围 x 114..362, y 129..471（1:100）
OX, OY = 14400.0, 26800.0


def P(x, y):
    return (x + OX, y + OY)


def rect(x1, y1, x2, y2, layer, plan=True):
    if plan:
        x1, y1 = P(x1, y1)
        x2, y2 = P(x2, y2)
    return MSP.add_lwpolyline([(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                              close=True, dxfattribs={"layer": layer})


def line(x1, y1, x2, y2, layer, plan=True):
    if plan:
        x1, y1 = P(x1, y1)
        x2, y2 = P(x2, y2)
    return MSP.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})


def _mt(s, x, y, h, layer, rot, width, attach):
    mt = MSP.add_mtext(s, dxfattribs={
        "style": "CN", "char_height": h, "layer": layer,
        "rotation": rot, "width": width,
    })
    mt.set_location((x, y), attachment_point=attach)
    return mt


def txt(s, x, y, h, layer="A-TEXT", rot=0.0, plan=True, width=0.0):
    """居中 (attachment 5)"""
    if plan:
        x, y = P(x, y)
    return _mt(s, x, y, h, layer, rot, width, 5)


def txt_left(s, x, y, h, layer="A-TEXT", rot=0.0, plan=True, width=0.0):
    if plan:
        x, y = P(x, y)
    return _mt(s, x, y, h, layer, rot, width, 4)


def hatch(pts, layer, pattern="ANSI31", scale=250, color=4):
    h = MSP.add_hatch(color=color, dxfattribs={"layer": layer})
    h.set_pattern_fill(pattern, scale=scale)
    h.paths.add_polyline_path([P(*p) for p in pts], is_closed=True)
    return h


# ══════════════════════════════════════════════════════════════════════
#  建筑尺寸
# ══════════════════════════════════════════════════════════════════════
T = 240.0
RX0, RX1 = 0.0, 19200.0            # 建筑内轮廓 X
RY0, RY1 = -13000.0, 15000.0       # 建筑内轮廓 Y
MY0, MY1 = 0.0, 15000.0            # 主机房
CY0, CY1 = -2640.0, -240.0         # 走廊
EY1 = -2880.0                      # 设备区顶
SX1, SX2 = 7000.0, 13000.0         # 设备区隔墙

# 外墙（外皮 + 内皮）
rect(RX0 - T, RY0 - T, RX1 + T, RY1 + T, "A-WALL")
rect(RX0, RY0, RX1, RY1, "A-WALL")

# ── 内隔墙：在门洞处断开（参照 123.dwg 的画法）───────────────────────
# 门洞定义：(墙, 起点, 终点)；墙水平时给 x 范围，垂直时给 y 范围
DOORS_H = [   # (x1, x2)  在主机房/走廊隔墙 y=CY0..CY1 上
    (8800, 10600),
]
DOORS_V = []  # 设备区门在 y=EY1 墙上，也为水平墙

def hwall_with_doors(y1, y2, layer, doors):
    """画水平墙，在 doors 的 x 区间留洞并封口"""
    xs = sorted(doors)
    cur = RX0
    for dx1, dx2 in xs:
        if dx1 > cur:
            rect(cur, y1, dx1, y2, layer)
        # 门洞两侧封口
        line(dx1, y1, dx1, y2, layer)
        line(dx2, y1, dx2, y2, layer)
        cur = dx2
    if cur < RX1:
        rect(cur, y1, RX1, y2, layer)


# 主机房 / 走廊隔墙（双开门 1800 宽）
hwall_with_doors(CY1, CY0, "A-WALL-IN", [(8800, 10600)])
# 走廊 / 设备区隔墙（三樘门）
hwall_with_doors(EY1, CY0, "A-WALL-IN", [(2800, 3700), (9200, 10100), (15200, 16100)])
# 设备区竖向隔墙
rect(SX1, RY0, SX1 + T, EY1, "A-WALL-IN")
rect(SX2, RY0, SX2 + T, EY1, "A-WALL-IN")

# ── 门：门扇 LINE + 1/4 ARC，完全照 123.dwg 的画法 ──────────────────
# 123.dwg 实例：
#   LINE (3500,120)->(3500,1620)  ARC c=(3500,120) r=1500 a=90..180
#   → 铰点在墙线上，门扇垂直于墙，弧从门扇扫到门洞另一侧
def door_h(x_hinge, y_wall, w, opens_up=True, hinge_right=True, layer="A-DOOR"):
    """水平墙上的门。x_hinge 铰点 x，y_wall 墙面 y，w 门宽。"""
    if opens_up:
        line(x_hinge, y_wall, x_hinge, y_wall + w, layer)          # 门扇 (+Y)
        a0, a1 = (90, 180) if hinge_right else (0, 90)
    else:
        line(x_hinge, y_wall, x_hinge, y_wall - w, layer)          # 门扇 (-Y)
        a0, a1 = (180, 270) if hinge_right else (270, 360)
    MSP.add_arc(P(x_hinge, y_wall), w, a0, a1, dxfattribs={"layer": layer})


# 主机房双开门 1800（两扇各 900），向机房内（+Y）开
door_h(8800, CY0, 900, opens_up=True, hinge_right=False)   # 左扇，左铰
door_h(10600, CY0, 900, opens_up=True, hinge_right=True)   # 右扇，右铰
# 设备区三樘门 900，向室内（-Y）开
door_h(3700, EY1, 900, opens_up=False, hinge_right=True)
door_h(10100, EY1, 900, opens_up=False, hinge_right=True)
door_h(16100, EY1, 900, opens_up=False, hinge_right=True)

# ══════════════════════════════════════════════════════════════════════
#  轴网
# ══════════════════════════════════════════════════════════════════════
AX_X = [0, 7000, 13000, 19200]
AX_XL = ["1", "2", "3", "4"]
AX_Y = [RY0, EY1, CY0, 0, RY1]
AX_YL = ["A", "B", "C", "D", "E"]
BX0, BX1 = RX0 - T, RX1 + T
BY0, BY1 = RY0 - T, RY1 + T

for x, lab in zip(AX_X, AX_XL):
    line(x, BY0 - 1200, x, BY1 + 1200, "A-AXIS")
    for yy in (BY0 - 1650, BY1 + 1650):
        MSP.add_circle(P(x, yy), 600, dxfattribs={"layer": "A-AXIS"})
        txt(lab, x, yy, 400, "A-TEXT")

for y, lab in zip(AX_Y, AX_YL):
    line(BX0 - 1200, y, BX1 + 1200, y, "A-AXIS")
    for xx in (BX0 - 1650, BX1 + 1650):
        MSP.add_circle(P(xx, y), 600, dxfattribs={"layer": "A-AXIS"})
        txt(lab, xx, y, 400, "A-TEXT")

# ══════════════════════════════════════════════════════════════════════
#  GPU 机柜：10 排 x 10 台 = 100 台
#   每块 10 台 x 600 = 6000 宽；两块之间留 2400 交叉通道
#   5 排纵向，冷通道 1800、热通道 600
# ══════════════════════════════════════════════════════════════════════
RACK_W, RACK_D = 600.0, 1200.0
BLK_A_X, BLK_B_X = 2400.0, 10800.0
CROSS_X0, CROSS_X1 = 8400.0, 10800.0

ROW_Y = [2400, 5400, 7200, 10200, 12000]     # 5 排底面 Y
COLD_Y = [(3600, 5400), (8400, 10200)]
HOT_Y = [(6600, 7200), (11400, 12000)]

for ri, by in enumerate(ROW_Y):
    for bi, bx0 in enumerate((BLK_A_X, BLK_B_X)):
        rn = ri + 1 + bi * 5
        for i in range(10):
            x1 = bx0 + i * RACK_W
            rect(x1, by, x1 + RACK_W, by + RACK_D, "E-RACK")
            # 前脸细线（冷通道侧）
            fy = by + RACK_D if ri % 2 == 0 else by
            line(x1 + 80, fy, x1 + RACK_W - 80, fy, "E-RACK")
            txt(f"{i+1:02d}", x1 + RACK_W / 2, by + RACK_D / 2, 160, "A-TEXT")
        # 排号放两侧留白，避免压线
        lx = 1250.0 if bi == 0 else 18100.0
        txt(f"R{rn}", lx, by + RACK_D / 2, 360, "A-TEXT")

# 列头柜：每排末端各一台
for by in ROW_Y:
    for bx0 in (BLK_A_X + 6000, BLK_B_X + 6000):
        rect(bx0, by, bx0 + RACK_W, by + RACK_D, "E-RACK-PDU")
        txt("列头柜", bx0 + RACK_W / 2, by + RACK_D / 2, 150, "A-TEXT", rot=90)

# ── 冷热通道（网格填充 + 标注置于交叉通道内）──────────────────────────
for y1, y2 in COLD_Y:
    for bx0 in (BLK_A_X, BLK_B_X):
        hatch([(bx0, y1), (bx0 + 6000, y1), (bx0 + 6000, y2), (bx0, y2)],
              "A-HATCH", "ANSI31", 300, 4)
for y1, y2 in HOT_Y:
    for bx0 in (BLK_A_X, BLK_B_X):
        hatch([(bx0, y1), (bx0 + 6000, y1), (bx0 + 6000, y2), (bx0, y2)],
              "A-HATCH", "ANSI31", 170, 1)

# 通道标注：全部放在 2400 宽的交叉通道内（空白带），旋转 90 度
XLBL = (CROSS_X0 + CROSS_X1) / 2
for y1, y2 in COLD_Y:
    txt("封闭冷通道", XLBL, (y1 + y2) / 2, 230, "A-TEXT", rot=90)
for y1, y2 in HOT_Y:
    txt("热通道", XLBL, (y1 + y2) / 2, 220, "A-TEXT", rot=90)

# ══════════════════════════════════════════════════════════════════════
#  精密空调 5 台（上 3 + 下 2），标注写在本体内，避开风圈
# ══════════════════════════════════════════════════════════════════════
CRAC_W, CRAC_D = 2400.0, 1600.0
CRACS = [
    ("CRAC-1", 2400, 13400),
    ("CRAC-2", 8400, 13400),
    ("CRAC-3", 12800, 13400),
    ("CRAC-4", 2400, 200),
    ("CRAC-5", 12000, 200),
]
for name, x, y in CRACS:
    rect(x, y, x + CRAC_W, y + CRAC_D, "E-CRAC")
    for k in range(3):
        cx = x + CRAC_W / 2 + (k - 1) * 700
        cy = y + CRAC_D - 450
        MSP.add_circle(P(cx, cy), 260, dxfattribs={"layer": "E-CRAC"})
    txt(name, x + CRAC_W / 2, y + 480, 300, "A-TEXT")

# ══════════════════════════════════════════════════════════════════════
#  主机房名称（底部空白带，位于 CRAC-4 与 CRAC-5 之间）
# ══════════════════════════════════════════════════════════════════════
# 主机房名称 + 面积：放在 CRAC-4 与 CRAC-5 之间的底部空白带 (x 4800~12000, y 200~1800)
txt("GPU 智算机房", 8400, 1250, 430, "A-TEXT")
txt("288.0 m²     100 柜 × 12 kW", 8400, 620, 290, "A-TEXT")

# ══════════════════════════════════════════════════════════════════════
#  UPS 配电室
# ══════════════════════════════════════════════════════════════════════
for i, ux in enumerate((400, 2000, 3600, 5200)):
    rect(ux, -4300, ux + 1400, -3200, "E-UPS")
    txt(f"UPS-{i+1}", ux + 700, -3750, 250, "A-TEXT")

for i in range(8):
    px = 300 + i * 800
    rect(px, -12800, px + 800, -11800, "E-UPS")
    txt(f"AP{i+1}", px + 400, -12300, 180, "A-TEXT", rot=90)

for i in range(6):
    px = 900 + i * 900
    rect(px, -9900, px + 900, -8900, "E-UPS")
    txt(f"DP{i+1}", px + 450, -9400, 200, "A-TEXT", rot=90)

txt("UPS 配电室", 3500, -6800, 420, "A-TEXT")
txt("70.8 m²", 3500, -7450, 300, "A-TEXT")

# ══════════════════════════════════════════════════════════════════════
#  电池室（独立物理隔间）
# ══════════════════════════════════════════════════════════════════════
BAT_W, BAT_D = 800.0, 600.0
for r in range(2):
    byy = -5100 - r * 1500
    for i in range(6):
        bx = 7500 + i * BAT_W
        rect(bx, byy, bx + BAT_W, byy + BAT_D, "E-BATT")
    txt(f"蓄电池组 {r+1}", 7500 + 3 * BAT_W, byy - 400, 260, "A-TEXT")

txt("电池室", 10000, -8200, 420, "A-TEXT")
txt("60.7 m²   独立隔间", 10000, -8850, 300, "A-TEXT")

# ══════════════════════════════════════════════════════════════════════
#  监控值班室
# ══════════════════════════════════════════════════════════════════════
rect(13600, -3600, 18300, -3200, "A-FURN")
txt("监控大屏 4×4", 15950, -3400, 220, "A-TEXT")

rect(13500, -6400, 15900, -5500, "A-FURN")
txt("操作台", 14700, -5950, 260, "A-TEXT")
rect(16200, -6400, 18600, -5500, "A-FURN")
txt("操作台", 17400, -5950, 260, "A-TEXT")
for cx in (14000, 15400, 16700, 18100):
    MSP.add_circle(P(cx, -4950), 240, dxfattribs={"layer": "A-FURN"})

rect(14200, -10800, 17800, -9200, "A-FURN")
txt("会议桌", 16000, -10000, 300, "A-TEXT")

txt("监控值班室", 15950, -7600, 420, "A-TEXT")
txt("62.7 m²   7×24 值守", 15950, -8250, 300, "A-TEXT")

txt("走廊", 1600, -1540, 340, "A-TEXT")

# ══════════════════════════════════════════════════════════════════════
#  尺寸标注
# ══════════════════════════════════════════════════════════════════════
dims = DOC.dimstyles.add("DC")
for k, v in dict(dimtxt=280, dimasz=140, dimexe=190, dimexo=140,
                 dimgap=90, dimdec=0, dimlunit=2, dimtad=1,
                 dimtih=0, dimtoh=0, dimclrt=2, dimclre=2, dimclrd=2).items():
    setattr(dims.dxf, k, v)
dims.dxf.dimtxsty = "CN"


def dim_h(x1, x2, y, off):
    d = MSP.add_linear_dim(base=P((x1 + x2) / 2, y + off), p1=P(x1, y),
                           p2=P(x2, y), angle=0, dimstyle="DC",
                           dxfattribs={"layer": "A-DIM"})
    d.render()


def dim_v(y1, y2, x, off):
    d = MSP.add_linear_dim(base=P(x + off, (y1 + y2) / 2), p1=P(x, y1),
                           p2=P(x, y2), angle=90, dimstyle="DC",
                           dxfattribs={"layer": "A-DIM"})
    d.render()


dim_h(RX0, RX1, RY0, -2500)
dim_h(RX0, SX1, RY0, -1300)
dim_h(SX1, SX2, RY0, -1300)
dim_h(SX2, RX1, RY0, -1300)
dim_v(RY0, RY1, RX0, -2500)
dim_v(RY0, EY1, RX0, -1300)
dim_v(EY1, MY0, RX0, -1300)
dim_v(MY0, RY1, RX0, -1300)
dim_h(RX0, RX1, RY1, 1250)

# ══════════════════════════════════════════════════════════════════════
#  表格（手绘线 + MTEXT 正中）
# ══════════════════════════════════════════════════════════════════════
def draw_table(x, y, col_w, row_h, data, title, layer="A-TABLE", th=280, tth=340):
    n_rows = len(data)
    total_w, total_h = sum(col_w), row_h * n_rows

    rect(x, y - total_h, x + total_w, y, layer, plan=False)
    for i in range(1, n_rows):
        line(x, y - i * row_h, x + total_w, y - i * row_h, layer, plan=False)
    cx = x
    for w in col_w[:-1]:
        cx += w
        line(cx, y, cx, y - total_h, layer, plan=False)

    txt(title, x + total_w / 2, y + 560, tth, layer, plan=False)

    for ri, row in enumerate(data):
        cy = y - ri * row_h - row_h / 2
        cx = x
        for ci, cell in enumerate(row):
            txt(str(cell), cx + col_w[ci] / 2, cy,
                th * (1.08 if ri == 0 else 1.0), layer, plan=False)
            cx += col_w[ci]


eq_rows = [
    ["序号", "设备名称", "规格 / 参数", "数量", "单位"],
    ["1", "GPU 机柜", "600×1200×2200，12 kW/柜", "100", "台"],
    ["2", "列头柜", "600×1200，400 A", "10", "台"],
    ["3", "精密空调", "房间级风冷，400 kW", "5", "台"],
    ["4", "UPS 主机", "800 kVA 模块化，2N", "4", "台"],
    ["5", "蓄电池组", "12 V / 1000 Ah，15 min", "12", "组"],
    ["6", "配电柜 AP", "低压进线 / 联络", "8", "面"],
    ["7", "配电柜 DP", "UPS 输出 / 列头", "6", "面"],
]
draw_table(41500, 53500, [1100, 3400, 6600, 1400, 1200], 1050, eq_rows,
           "主要设备表  （表 1）")

area_rows = [
    ["区域名称", "面积 (m²)", "占比", "备注"],
    ["GPU 智算机房", "288.0", "54.5%", "100 柜，2.88 m²/柜"],
    ["UPS 配电室", "70.8", "13.4%", "2N 供电"],
    ["电池室", "60.7", "11.5%", "独立物理隔间"],
    ["监控值班室", "62.7", "11.9%", "7×24 值守"],
    ["走廊", "46.1", "8.7%", "连接各功能区"],
    ["合计", "528.4", "100%", "—"],
]
draw_table(41500, 43200, [3600, 2600, 2200, 5600], 1150, area_rows,
           "房间面积表  （表 2）")

par_rows = [
    ["项目", "设计取值", "依据"],
    ["单柜功率", "12 kW", "风冷高密度 < 25 kW"],
    ["IT 总负荷", "1200 kW", "100 柜 × 12 kW"],
    ["UPS 容量", "3200 kVA（2N）", "E ≥ 1.2 P"],
    ["后备时间", "≥ 15 min", "A 级数据中心"],
    ["冷负荷", "1600 kW", "IT 负荷 + 围护结构"],
    ["空调配置", "5 × 400 kW（4+1）", "冗余 N+1"],
    ["冷通道送风", "18~27 ℃", "GB 50174-2017"],
    ["主机房面积", "288 m²", "2.0~4.0 m²/柜"],
]
draw_table(41500, 34200, [3000, 3600, 7600], 1050, par_rows,
           "设计参数表  （表 3）")

# ══════════════════════════════════════════════════════════════════════
#  图例
# ══════════════════════════════════════════════════════════════════════
LX, LY = 41500, 22500
txt_left("图  例", LX, LY + 700, 400, "A-TEXT", plan=False)
legend = [
    ("E-RACK", "GPU 机柜 12 kW"),
    ("E-RACK-PDU", "列头柜"),
    ("E-CRAC", "精密空调 400 kW"),
    ("E-UPS", "UPS / 配电柜"),
    ("E-BATT", "蓄电池组"),
    ("A-FURN", "值班室家具"),
]
for i, (lay, name) in enumerate(legend):
    yy = LY - i * 1300
    rect(LX, yy - 750, LX + 1800, yy, lay, plan=False)
    txt_left(name, LX + 2300, yy - 375, 300, "A-TEXT", plan=False)

# 冷热通道图例
yy = LY - len(legend) * 1300
hatch([(LX, yy - 750), (LX + 1800, yy - 750), (LX + 1800, yy), (LX, yy)],
      "A-HATCH", "ANSI31", 200, 4)
rect(LX, yy - 750, LX + 1800, yy, "A-HATCH", plan=False)
txt_left("冷 / 热通道隔离", LX + 2300, yy - 375, 300, "A-TEXT", plan=False)

# ══════════════════════════════════════════════════════════════════════
#  设计说明
# ══════════════════════════════════════════════════════════════════════
NX, NY = 58000, 53500
txt_left("设 计 说 明", NX, NY, 400, "A-TEXT", plan=False)
notes = [
    "1. 本图为 GPU 智算中心机房平面布置图，比例 1:100，尺寸单位 mm。",
    "2. 机柜按 10 排 × 10 台布置，共 100 台，单柜功率 12 kW。",
    "3. 机柜面对面 / 背对背布置，冷、热通道全程封闭隔离。",
    "4. 精密空调 5 台（4+1 冗余），下送风、上回风。",
    "5. UPS 按 2N 配置，双路供电至列头柜，后备不小于 15 min。",
    "6. 蓄电池室为独立物理隔间，设独立通风与消防设施。",
    "7. 主机房楼面荷载不小于 16 kN/m²，梁下净高不小于 4.0 m。",
    "8. 主机房维持正压，与其他房间压差不小于 5 Pa。",
    "9. 设计依据：GB 50174-2017、T/GYJS 011-2025 及厂商白皮书。",
]
for i, s in enumerate(notes):
    txt_left(s, NX, NY - 1050 - i * 800, 265, "A-TEXT", plan=False)

# ══════════════════════════════════════════════════════════════════════
#  指北针
# ══════════════════════════════════════════════════════════════════════
nax, nay = 58000, 36000
MSP.add_circle((nax, nay), 900, dxfattribs={"layer": "A-TEXT"})
MSP.add_lwpolyline([(nax, nay + 1000), (nax - 380, nay - 460),
                    (nax, nay - 130), (nax + 380, nay - 460)],
                   close=True, dxfattribs={"layer": "A-TEXT"})
txt("N", nax, nay + 1580, 360, "A-TEXT", plan=False)

# ══════════════════════════════════════════════════════════════════════
#  图框 + 标题栏
# ══════════════════════════════════════════════════════════════════════
# A1 纸张 841x594，但 DWG To PDF.pc3 的可打印区只有 831x560（边距 5/5/17/17）。
# 图框若按 841x594 画，1:100 出图必然溢出被裁切。
# 故图框取 820x555，稳落在可打印区内。
FW, FH = 82000, 55500
M = 1000
rect(0, 0, FW, FH, "A-FRAME", plan=False)
rect(M, M, FW - M, FH - M, "A-FRAME", plan=False)

TBX1, TBY1 = FW - M, M
TBX0, TBY0 = TBX1 - 18000, TBY1 + 5600


def tline(x1, y1, x2, y2):
    line(x1, y1, x2, y2, "A-TITLE", plan=False)


# ── 标题栏 180 x 56 mm（纸面 y 10..66）─────────────────────────────
#   y 10..22  信息行：设计|CAD  比例|1:100  日期|2026-11-18
#   y 22..34  图名
#   y 34..46  工程名称
#   y 46..66  大标题（20mm 高）
rect(TBX0, TBY0, TBX1, TBY1, "A-TITLE", plan=False)
# 行分隔线：22 / 34 / 46（相对 TBY1）
for yy in (1200, 2400, 3600):
    tline(TBX0, TBY1 + yy, TBX1, TBY1 + yy)

# 信息行（y 10..22）分 6 格，每格 30mm
for xx in (3000, 6000, 9000, 12000, 15000):
    tline(TBX0 + xx, TBY1, TBX0 + xx, TBY1 + 1200)
# 图名/工程名称行（y 22..46）左侧标签列宽 60mm
tline(TBX0 + 6000, TBY1 + 1200, TBX0 + 6000, TBY1 + 3600)

# ── 大标题：46..66 行，中心 y=56 → TBY1+4600，字高 4.5mm ──────────
# 15 字 x 4.5 ≈ 68mm，在 180mm 宽内居中
txt("GPU 智算中心机房平面布置图", TBX0 + 9000, TBY1 + 4600, 450,
    "A-TITLE", plan=False)

# ── 工程名称：34..46 行，中心 y=40 → TBY1+3000 ────────────────────
txt("工程名称", TBX0 + 3000, TBY1 + 3000, 320, "A-TITLE", plan=False)
txt("GPU 智算中心机房工程", TBX0 + 12000, TBY1 + 3000, 320,
    "A-TITLE", plan=False)

# ── 图名：22..34 行，中心 y=28 → TBY1+1800 ────────────────────────
txt("图  名", TBX0 + 3000, TBY1 + 1800, 320, "A-TITLE", plan=False)
txt("主机房平面布置图", TBX0 + 12000, TBY1 + 1800, 320,
    "A-TITLE", plan=False)

# ── 信息行：中心 y=16 → TBY1+600，三组各占 60mm ───────────────────
rowA = [
    ("设计", "CAD"),
    ("比例", "1:100"),
    ("日期", "2026-11-18"),
]
for i, (lab, val) in enumerate(rowA):
    cx = TBX0 + i * 6000
    txt(lab, cx + 1500, TBY1 + 600, 260, "A-TITLE", plan=False)
    txt(val, cx + 4500, TBY1 + 600, 260, "A-TITLE", plan=False)

# 图名（平面图上方，纸面 y≈500mm → 模型 50000）
txt("GPU 智算中心机房平面布置图", 24000, 47600, 700, "A-TITLE", plan=False)
txt("比例 1:100        单位 mm", 24000, 46200, 380, "A-TITLE", plan=False)

# ══════════════════════════════════════════════════════════════════════
# 16. 图纸空间：Layout1 满幅视口，固定 1:100
#     这是标准 CAD 出图方式，比 "extents + 1:100" 可靠：
#     视口尺寸 820x555 mm（纸面），view_height=55500（模型mm）
#     → 缩放严格 = 55500/555 = 100，即 1:100
# ══════════════════════════════════════════════════════════════════════
if "Layout1" in DOC.layouts:
    LAY = DOC.layouts.get("Layout1")
else:
    LAY = DOC.layouts.new("Layout1")

# 清掉既有视口，重建一个满幅的
for _vp in list(LAY.query("VIEWPORT")):
    LAY.delete_entity(_vp)

LAY.add_viewport(
    center=(410.0, 277.5),           # 纸面 mm，图纸中心
    size=(820.0, 555.0),             # 纸面 mm，满幅
    view_center_point=(41000.0, 27750.0),   # 模型中心
    view_height=55500.0,             # 模型高度 → 缩放 100 = 1:100
)

OUT = r"D:/git_codes/test_Autocad_MCP/draw_test/gpu_dc_100.dxf"
DOC.saveas(OUT)
print("saved:", OUT)
print("entities:", len(MSP))
print("viewports in Layout1:", len(list(LAY.query("VIEWPORT"))))
