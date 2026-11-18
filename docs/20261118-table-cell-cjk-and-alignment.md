# 原生 TABLE 的两处缺陷：单元格不居中 + 中文空白（已修上游）

> 记录日期：2026-11-18
> 环境：AutoCAD 2026 `25.1s (LMS Tech)`、autocad-mcp-pro 1.8.0
> 相关文档：[`AGENTS.md`](../AGENTS.md) · [`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md) · [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md)

---

## 1. 现象

用 `entity_create_table` 建原生 TABLE：

1. **单元格文字贴在上边缘**，看起来"悬浮"在行线上方
2. **中文单元格全空白**，但英文单元格正常

第 2 条尤其反直觉：`GetTextString` 读回来内容是对的，DXF 里文字也在，屏幕上就是看不见。

---

## 2. 根因

### 2.1 顶部对齐

`AddTable` 创建的单元格默认 `acTopLeft`。原源码建表时只设了列宽、行高、文字、字高，**没设对齐**：

```python
table.SetText(row_index, column_index, value)
table.SetCellTextHeight(row_index, column_index, layout.text_height)
# ← 缺 SetCellAlignment
```

### 2.2 单元格有自己的文字样式

**关键事实：TABLE 单元格不跟随 `AcDbText.StyleName`，它走自己的 `SetCellTextStyle`。**

`AddTable` 把所有单元格放在 `Standard` 样式上，而 `Standard` 的字体是 `txt.shx` —— **没有 CJK 字形，也没有 `²` `Ø` `±` `°`**。AutoCAD 遇到无字形字符静默跳过，所以中文/上标在屏幕上什么都不显示。

实测确认（pywin32 直连 AutoCAD 2026）：

| 探测 | 结果 |
|---|---|
| 新建表的单元格样式 | `GetCellTextStyle(0,0)` → **`Standard`** |
| 设置方法 | `SetCellTextStyle`，DISPID **72** |
| 设置后 | `GetCellTextStyle` → `CN` |
| DXF 导出 | 设了的单元格 `style=CN`，没设的 `style=None` |

---

## 3. 处理（上游源码 1.8-24）

### 3.1 居中

```python
table.SetCellAlignment(row_index, column_index, 5)   # 5 = acMiddleCenter
```

### 3.2 中文单元格

新增两个辅助函数：

```python
_com_needs_cjk_style(cells)
    # 任一单元格含 > 0x7F 的字符就返回 True
    # （中文、m²、Ø、±、° 全都在这个集合里）

_com_cell_textstyle_name(doc)
    # ① 先复用图纸里已有的 CJK 字体样式
    # ② 没有就用第一个本机存在的 CJK 字体建 MCP-CJK
    # ③ 一个都没有 → 返回 None，调用方降级
```

建表流程：

```python
cell_style = None
if _com_needs_cjk_style(layout.cells):
    cell_style = _com_cell_textstyle_name(_acad_doc())
    if cell_style is None:
        log.warning("... this AutoCAD has no CJK font ...")
...
    table.SetCellAlignment(row_index, column_index, 5)
    if cell_style is not None:
        table.SetCellTextStyle(row_index, column_index, cell_style)
```

**行为设计**：

| 情况 | 行为 |
|---|---|
| 纯 ASCII 表 | 保持 `Standard`，行为**完全不变** |
| 含中文 / `m²` / `Ø` | 自动指向 CJK 样式 |
| 图纸已有 `CN` 之类样式 | **复用**，不重复建 |
| 席位没有 CJK 字体 | 警告但**不失败**，表格照常写入 |

CJK 字体优先级：`simhei.ttf` → `simsun.ttc` → `msyh.ttc` → `simkai.ttf` → `simfang.ttf`。

---

## 4. 实测证据（AutoCAD 实机）

建一张图，同时放 ASCII 表和中文表：

```text
=== TABLE 8D (ASCII) ===
   'NAME'         style=None       attach=5
   'GPU RACK'     style=None       attach=5

=== TABLE A0 (中文) ===
   '设备名称'      style=MCP-CJK    attach=5
   'GPU 机柜'     style=MCP-CJK    attach=5
   '288.0 m²'    style=MCP-CJK    attach=5
```

图纸里同时生成了样式：`MCP-CJK  font=simhei.ttf`

### 几何居中验证（不只看 attach 属性）

从 DXF 的表格网格线算出每行边界，比对文字 y 与行中心：

```text
=== TABLE 8D  行边界: [12000, 10800, 9600, 8400] ===
   'NAME'      y=11400.0  行中心=11400.0  偏差=+0.0  OK
   'GPU RACK'  y=10200.0  行中心=10200.0  偏差=+0.0  OK

=== TABLE A0  行边界: [5000, 3800, 2600, 1400, 200] ===
   '设备名称'    y= 4400.0  行中心= 4400.0  偏差=+0.0  OK
   '288.0 m²'  y=  800.0  行中心=  800.0  偏差=+0.0  OK
```

**11 个单元格全部偏差 +0.0。**

### 对照：修复前

同一 AutoCAD 里建两个表，一个不设对齐、一个设：

| 表 | 单元格 | y | attach | 判定 |
|---|---|---|---|---|
| 未设 | `row-b` | **-2401.5** | **2**（顶部） | 贴行上沿 |
| 设了 | `row-b` | **-3000.0** | **5**（正中） | 精确行中心 |

行范围 -2400..-3600，中心 -3000。修复前差 **600**（半个行高）。

---

## 5. 无效的尝试

| 尝试 | 结果 |
|---|---|
| 给 `Standard` 样式设字体后再建表 | 能绕，但改动了图纸的默认样式，副作用大 |
| 靠 `SetText` 后 `AcDbText.StyleName` | **无效**——单元格不跟随实体样式 |
| 用 `entity_create_text` 替代 | 可行但失去 TABLE 的网格、列宽、行高能力 |
| agent 侧改用「手绘线 + MTEXT」 | 有效但**把负担推给每个调用方**，应当修在 MCP 侧 |

---

## 6. 预防

1. **TABLE 单元格的样式和对齐都要显式设置**，`AddTable` 的默认值两个都不合适。
2. **判断中文是否显示，不能看 `GetTextString`**（它总有内容），要看单元格的 `style` 指向的字体是否有 CJK 字形。
3. **验证居中要看几何**（文字 y vs 行中心），不能只看 `attachment_point` 属性。
4. 含 `m²`/`Ø`/`±`/`°` 的表**同样需要 CJK 样式**，这些字符 `txt.shx` 也没有。
5. MCP 已自动处理；调用方无需再关心。旧版本仍需手动 `SetCellTextStyle`。

---

*2026-11-18 记录。两处缺陷都修在 MCP 服务端，调用方不再需要绕路。*
