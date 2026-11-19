# -*- coding: utf-8 -*-
"""给 20261119.dxf 补机房配置表，并保存。

为什么要单独一步：ezdxf 1.4.4 没有 TABLE 写出 API（`add_table` 不存在），
原生 AcDbTable 只能经 AutoCAD COM 建。建完立刻回读边界验证没压图框。

用法：
    python scripts/add_20261119_table.py D:/.../20261119.dxf
"""
from __future__ import annotations

import sys
import time
from array import array

import pythoncom
import win32com.client
from win32com.client import VARIANT

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PATH = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\git_codes\test_Autocad_MCP\draw_test\20261119.dxf"

ROWS = [
    ["机房", "排数", "机柜数", "GPU 数", "功率 (kW)"],
    ["A", "2", "20", "120", "160"],
    ["B", "2", "20", "120", "160"],
    ["C", "2", "20", "120", "160"],
    ["D", "2", "20", "120", "160"],
    ["合计", "8", "80", "480", "640"],
]
COL_W = (1600.0, 1400.0, 1600.0, 1900.0, 2200.0)
TXT_H = 110.0
ROW_H = 310.0                       # ≈ 2.8 × 字高，避免被字撑开
X0, Y0 = 32000.0, 20000.0           # 锚点 = 左上角，向下向右生长
FRAME_R = 40800.0                   # 图框内边右界，表格不得越过

app = win32com.client.Dispatch("AutoCAD.Application")
doc = app.ActiveDocument
if doc.FullName.lower() != PATH.lower():
    raise SystemExit(f"活动文档不是目标文件: {doc.FullName}")


def vpt(x, y):
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                   array("d", [float(x), float(y), 0.0]))


def bounds(t):
    mn, mx = t.GetBoundingBox()
    return (float(mn[0]), float(mn[1])), (float(mx[0]), float(mx[1]))


# 已有表就先删掉，保证可重复执行
for e in list(doc.ModelSpace):
    if e.ObjectName == "AcDbTable" and e.Layer == "A-TABLE":
        print(f"删除旧表 {e.Handle}")
        e.Delete()

msp = doc.ModelSpace
# 插入点必须是 VARIANT 数组：元组会被接受形参数量后判无效（E_INVALIDARG）
tbl = msp.AddTable(vpt(X0, Y0), len(ROWS), len(COL_W),
                   ROW_H, TXT_H)
tbl.Layer = "A-TABLE"

for c, w in enumerate(COL_W):
    tbl.SetColumnWidth(c, w)
for r in range(len(ROWS)):
    # 先设字高再设行高：行高会被字高撑开，这个顺序才稳
    for c in range(len(COL_W)):
        tbl.SetCellTextHeight(r, c, TXT_H)
    tbl.SetRowHeight(r, ROW_H)

for r, row in enumerate(ROWS):
    for c, val in enumerate(row):
        tbl.SetText(r, c, str(val))      # 注意：不是 SetTextString
        tbl.SetCellTextStyle(r, c, "CN")  # 单元格不跟随 AcDbText.StyleName
        tbl.SetCellAlignment(r, c, 5)     # 5 = acMiddleCenter
        tbl.SetCellBackgroundColor(r, c, 0) if False else None

# 初建表头行加粗一点：不改字体，只加行高已经由 ROW_H 统一
doc.Regen(1)

(mnx, mny), (mxx, mxy) = bounds(tbl)
print(f"表格边界 X {mnx:.0f}..{mxx:.0f}  Y {mny:.0f}..{mxy:.0f}")
print("行高回读:", [round(tbl.GetRowHeight(r)) for r in range(int(tbl.Rows))])
print("单元格样式回读:",
      {(r, c): tbl.GetCellTextStyle(r, c)
       for r in range(int(tbl.Rows)) for c in range(int(tbl.Columns))
       if tbl.GetCellTextStyle(r, c) != "CN"} or "全部 CN")

if mxx > FRAME_R:
    dx = FRAME_R - mxx
    print(f"右界越框 {mxx - FRAME_R:.0f}，左移 {-dx:.0f}")
    tbl.Move(vpt(0, 0), vpt(dx, 0))
    doc.Regen(1)
    (mnx, mny), (mxx, mxy) = bounds(tbl)
    print(f"移动后 X {mnx:.0f}..{mxx:.0f}  Y {mny:.0f}..{mxy:.0f}")

doc.Save()
print(f"已保存 {doc.FullName}  saved={doc.Saved}")
