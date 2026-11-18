# 表格（TABLE）单元格文字偏上：AddTable 默认顶部对齐

> 记录日期：2026-11-17
> 环境：AutoCAD 2026（`25.1s (LMS Tech)`）、`autocad-mcp-pro==1.8.0`（本地 venv 版）、Windows
> 发现场景：通信机房平面图的门 / 窗 / 房间三张明细表

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 第 10 节排错、第 11 节记录制度
> - [`20261117-chinese-text.md`](20261117-chinese-text.md) — 中文显示

---

## 1. 现象

表格的每个单元格里，文字都贴在格子的**上边缘**，看起来"悬浮"在行线上方，不居中。

用户反馈原话：**"表格里面的文字要往下居中，现在普遍的偏上了"**。

同时观察到**下面的房间表格子显得小**（相对上面两张）。

---

## 2. 根因

### 2.1 创建时没设对齐，AutoCAD 默认顶部对齐

`backends/com_backend.py` 的 `entity_create_table`（约 7469 行）原本只做三件事：

```python
for row_index, row in enumerate(layout.cells):
    table.SetRowHeight(row_index, layout.row_height)
    for column_index, value in enumerate(row):
        table.SetText(row_index, column_index, value)
        table.SetCellTextHeight(row_index, column_index, layout.text_height)
    # ← 这里没有 SetCellAlignment
```

`AddTable` 创建的单元格默认是**顶部对齐**，所以文字贴在行上沿。

### 2.2 行高会被字高自动撑大（第二个坑）

设置 `SetRowHeight(r, 350)` 后，实际行高并不等于 350：

| 字高 | 实际行高（数据行） | 总高 |
|---|---|---|
| 125 | **403** | 2259 |
| 100 | 350 | 2100 |

因为行高 = 字高 + 上下边距（实测 `VertCellMargin = 1.5`，但比例更大），**字高设大了行高就被撑开**，整张表变高，进而压到下面的表或图形。

这也是"调大行高反而不受控"的原因——设 700 得到 1086，设 500 得到 1086。

### 2.3 表格锚点是左上角，向下生长

`AddTable(point, ...)` 的 `point` 是**左上角**，表格向下、向右展开。所以：

- 加高表格 → 底部向下延伸 → 可能撞到下方的轴号圆圈或下一张表
- 移动表格必须用 `Move`，`InsertionPoint` 是**只读**的（赋值报 `com_error`）

---

## 3. 处理

### 3.1 已修源码（根本解决）

`backends/com_backend.py` → `entity_create_table`，在每格设置字高后补一行：

```python
table.SetCellTextHeight(row_index, column_index, layout.text_height)
# MEASURED on AutoCAD 2026: SetCellAlignment(row, col, 5) is acMiddleCenter,
# which centres the text both ways and is what a schedule is read as.
table.SetCellAlignment(row_index, column_index, 5)
```

`5` = `acMiddleCenter`（水平居中 + 垂直居中）。取值表：

| 值 | 常量 | 含义 |
|---|---|---|
| 1 | acTopLeft | 左上 |
| 4 | acMiddleLeft | 左中 |
| **5** | **acMiddleCenter** | **正中** |
| 7 | acBottomCenter | 下中 |
| 9 | acBottomRight | 右下 |

**注意**：改源码后必须重启 Claude Code（MCP 子进程重新拉起）才生效。已有图纸里的旧表格不会自动改变，需按 3.2 补。

### 3.2 修正已有图纸的表格

**MCP 工具没有设置单元格对齐的接口**（`entity_create_table` 只在创建时设置）。已有表格用 COM 直接改：

```python
import win32com.client
app = win32com.client.GetActiveObject("AutoCAD.Application")
doc = app.ActiveDocument

for ent in doc.ModelSpace:
    if ent.ObjectName != "AcDbTable":
        continue
    rows, cols = int(ent.Rows), int(ent.Columns)
    for r in range(rows):
        for c in range(cols):
            ent.SetCellAlignment(r, c, 5)      # 5 = MiddleCenter
doc.Regen(1)
```

本次实测：3 张表、79 个单元格全部设置成功，回读 `GetCellAlignment(r,c)` 全为 `5`。

### 3.3 移动表格必须用 Move（InsertionPoint 只读）

```python
from win32com.client import VARIANT
import pythoncom, array

p1 = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, array.array("d", [0.0, 0.0, 0.0]))
p2 = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, array.array("d", [0.0, dy, 0.0]))
ent.Move(p1, p2)
doc.Regen(1)
```

- `ent.InsertionPoint = (...)` → **失败**，属性只读
- `ent.Translate(...)` → **不存在**，`AttributeError`
- `ent.Move((0,0,0), (0,dy,0))` 传 Python 元组 → **失败**，`com_error`，必须用 `VARIANT` 包装的 `array('d', ...)`

### 3.4 排版建议（本次采用的）

三张表纵向排列，间距 200 单位，且左侧让开轴号圆圈：

| 表 | 列数 | 行高 | 位置 |
|---|---|---|---|
| 门表 | 6 | 350 | y 6350..8450 |
| 窗表 | 5 | 350 | y 4400..6150 |
| 房间表 | 3 | 550（加高） | y -1100..2200 |

- 表格左边界 `x=14200`，右侧轴号圆圈最大 `x=13800`（圆心 13500 + 半径 300），留 400 间隙
- 房间表加高到 550 后总高 3300，因此单独下移让位

### 3.5 无效尝试

| 尝试 | 结果 |
|---|---|
| `system_run_lisp` 批量设对齐 | 被拒：`vla-setcellalignment`、`vla-get-activedocument` 在 deny 列表，需 `DANGEROUS_COMMANDS_ENABLED=true` |
| 设 `SetRowHeight(700)` 想加高 | 实际变成 1086（被字高撑开），不受控 |
| 设 `SetRowHeight(500)` + 字高 200 | 实际仍是 1086，字高 200 太大 |
| `ent.InsertionPoint = (...)` 移动 | `com_error`，属性只读 |
| `ent.Move(元组, 元组)` | `com_error`，参数类型不对 |
| 把表格加到 3945 高再看 | 底部 y=-945，压到轴号圆圈和下一张表 |

---

## 4. 预防

1. **新表一律由修好的 `entity_create_table` 创建**（已加 `SetCellAlignment(...,5)`），不要手工拼 TABLE。
2. **调行高先降字高。** 字高 > 行高的 ~1/3 就会撑开行，设定值被覆盖。经验值：`row_height ≈ 2.8 × text_height`。
3. **改高之后必须回读实际值**：`GetRowHeight(r)` 才是事实，`SetRowHeight` 的入参只是意图。
4. **表格会长高。** 加高前先算：`总高 = Σ 实际行高`，确认底部不会撞到下方实体，必要时先上移或下移。
5. **移动表格用 `Move` + VARIANT 包装的数组**，别试 `InsertionPoint` 或 `Translate`。
6. **表格与轴号圆圈要留间距。** 圆圈半径 300（`:50` 图），左边界至少 `圆心x + 半径 + 400`。

---

## 5. 一条命令速查

```python
# 全部表格居中（COM）
import win32com.client
app = win32com.client.GetActiveObject("AutoCAD.Application")
doc = app.ActiveDocument
n = 0
for ent in doc.ModelSpace:
    if ent.ObjectName != "AcDbTable":
        continue
    for r in range(int(ent.Rows)):
        for c in range(int(ent.Columns)):
            ent.SetCellAlignment(r, c, 5)   # acMiddleCenter
            n += 1
doc.Regen(1)
print("cells centred:", n)
```

```python
# 回读验证（设定值 ≠ 实际值）
for ent in doc.ModelSpace:
    if ent.ObjectName == "AcDbTable":
        print(ent.Handle, "align:", ent.GetCellAlignment(0, 0),
              "rowH:", [round(ent.GetRowHeight(r)) for r in range(int(ent.Rows))])
```

---

*首次记录于 2026-11-17，来自通信机房平面图三张明细表的实测与源码修复。*