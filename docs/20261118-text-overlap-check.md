# 文字与图形交叠检查：ezdxf 能不能做，怎么做才准

> 记录日期：2026-11-18
> 环境：AutoCAD 2026 (25.1s LMS Tech) / Python 3.11.15 / ezdxf 1.4.4 / matplotlib 3.11.2 / fontTools 4.63.0
> 样例：`draw_test/gpu_dc_100.dxf`（310 个 MTEXT、377 条曲线）、`draw_test/flange_test.dxf`、`draw_test/telecom_equipment_room_plan_fixed.dxf`、`draw_test/123_check.dxf`

> **相关文档**
> - [`AGENTS.md`](../AGENTS.md) — 使用规范总纲
> - [`20261117-chinese-text.md`](20261117-chinese-text.md) — 文字样式与字形
> - [`20261118-pdf-plot-fixes.md`](20261118-pdf-plot-fixes.md) — 出图链路

---

## 结论先放这里

**ezdxf 作为后端可以实现文字交叠检查，但不能用它自带的包围盒。** 需要自己按字形轮廓算文字框，并按字体标定；做完之后在 310 个真实 MTEXT 上与 AutoCAD 逐一对齐：

| 指标 | 结果 |
|---|---|
| 文字框宽度 vs AutoCAD | **完全一致**（simhei / simsun，已标定字体） |
| 文字框高度 vs AutoCAD | 偏差 ≤ 2.9% |
| 9 种 MTEXT 对齐点 + 旋转 90°，角点位置 | 偏差 ≤ 2.9 单位（字高 250） |
| 310 个真实 MTEXT 的框尺寸误差 | 89% ≤3%，97% ≤5%，98.4% ≤8% |
| 310 个真实 MTEXT 的**位置**误差 | **锚点中位数 0.000，最大 0.000（282/282 全为 0）** |

检测器本身（六类检查）：

| 验收项 | 结果 |
|---|---|
| 干净图纸（27 个文字，全部留足间距） | **0 条**误报 |
| 植入 6 类已知缺陷 | **6/6 全部检出** |
| 对照组（间距充足的标签） | 未被误报 |
| `gpu_dc_100.dxf` 全图 310 文字 | **12 条**，逐条核实均为真缺陷（2 互压 + 4 穿线 + 6 出图过小） |
| `text_illegible` 对真实出图 PDF 交叉验证 | 计数 10 与 100 完全吻合 |

产物：
- `tools/text_overlap/textbox.py` — 文字框测量（已标定）
- `tools/text_overlap/overlap.py` — 六类检查 + 安全位移搜索
- `tools/text_overlap/__main__.py` — 命令行入口
- `skills/autocad-text-overlap-check/` — 技能（已装到 `~/.claude/skills/`），
  目录结构见 [`references/layout.md`](../skills/autocad-text-overlap-check/references/layout.md)

---

## 现象

需求是「文字经常与图中元素交叠，希望有个检查工具告诉我哪里、什么内容交叠了」。第一版直接用 ezdxf 现成的包围盒：

```python
from ezdxf import bbox
b = bbox.extents([mtext_entity], fast=False)
```

在 `gpu_dc_100.dxf` 上跑，报出 **30 对文字互压 + 51 个文字被曲线穿过**。肉眼核对第一条就发现不对：标题「设 计 说 明」与它下面第一条注释重叠 **71%**——而那两行之间明明有 646 单位的净空。

## 根因

### 一、`ezdxf.bbox` 对 MTEXT 的换行宽度理解错了（这是主因）

`ezdxf/disassemble.py:447`：

```python
box_width = mtext.dxf.get("width", 0)
...
return text_wrap(text, box_width, font.text_width)      # :355
```

而 `ezdxf/tools/text.py::text_wrap` 的换行判据是：

```python
if box_width is not None and get_text_width(current_line + t) > box_width:
```

**DXF 组码 41 值为 `0.0` 的含义是「不换行」**，但代码把这个 `0.0` 当成箱子宽度传进去。任何词都宽于 0，于是**每个词都被切成一行**。

实测证据（handle 3B6，一行 40 字的注释，字高 265）：

| | 高度 | 宽度 | 行数 |
|---|---|---|---|
| ezdxf 算出 | **2534** | **5489** | 6 |
| AutoCAD 实际 | **374** | **11732** | 1 |

把 `text_wrap` 单独拎出来验证：

```
width=0.0  -> 6 行：'1.' / '本图为' / 'GPU' / '智算中心机房平面布置图，比例' / '1:100，尺寸单位' / 'mm。'
width=None -> 1 行：'1. 本图为 GPU 智算中心机房平面布置图，比例 1:100，尺寸单位 mm。'
```

高度被算成 6 倍、宽度被算成一半，于是凭空造出大量假重叠。源码里那句 docstring 其实已经承认了：

> `Calculation is based on a mono-spaced font and therefore the border path is just an educated guess.`

**结论：MTEXT 的包围盒不能直接用 ezdxf 的。**

### 二、AutoCAD 返回的是「字形墨迹框」，不是字体的 advance 宽度

改成自己按字体算之后，第一版用了 `font.text_width()`（advance 宽度）和 `total_height`。仍然偏，而且很整齐：

| 字符 | AutoCAD 报的宽 | 字体 advance |
|---|---|---|
| `1` | 0.298 em | 0.740 em |

AutoCAD 给的是**字形实际落下墨迹的范围**——`1` 这个字符两侧本来就是空的。

### 三、字体名写成完整路径，ezdxf 解析出另一套度量

这条最隐蔽，因为它不报错。

```
fonts.make_font('simhei.ttf', 400, 1.0)                    -> baseline=11.56, '国' 墨迹高 520.2
fonts.make_font('C:\\Windows\\Fonts\\simhei.ttf', 400, 1.0) -> baseline=0.00,  '国' 墨迹高 349.2
```

两者都返回 `TrueTypeFont`，**类型一致、不抛异常**，但后者所有中文字形宽度少 33%。

而**通过 COM 给样式指定字体时，AutoCAD 写进 DXF 的正是完整路径**：

```python
doc.TextStyles.Add("CN").fontFile = r"C:\Windows\Fonts\simhei.ttf"
# DXF 里得到：'CN' font='C:\Windows\Fonts\simhei.ttf'
```

绕法：解析时取 `os.path.basename`。

### 四、`font.measurements.total_height` 不可靠

同一个字高下，不同字体给出完全不同的 `total_height`，且部分字体 `baseline=0`：

| 字体 | char_height | `total_height` |
|---|---|---|
| simhei.ttf | 350 | 424.9 |
| simsun.ttc | 350 | 424.0 |
| msyh.ttc | 350 | **465.0**（且 baseline=0） |

改从字形轮廓量 `A` 的实际高度——这个值在测试过的五个字体里**恒等于 char_height**。

### 五、MTEXT 多行间距不是 1.0 倍字高

DXF 组码 44 缺省（或为 1.0）时，AutoCAD 用的是「3-on-5」行距，即 **行距 = 5/3 × 字高**。实测两组完全吻合：

```
2 行 @255 字高 -> 706.7 = 265 + 5/3 × 265      ✓
3 行 @200 字高 -> 866.7 = 200 + 2 × 5/3 × 200  ✓
```

### 六、attachment point 7/8/9 的垂直方向搞反了

第一版以为所有点位都是「插入点在上、文字向下」。实际上 1-3 顶对齐（向下）、4-6 居中、7-9 底对齐（向上）。这一条是我在自己的测试里发现的——只比宽高看不出，一比绝对坐标就露馅：7-9 整整低了 505 单位（字高 250 时）。

顺带一个坑：**通过 COM 设置 `AttachmentPoint` 时，AutoCAD 会同时改写 insert 点**，保持文字视觉位置不动。所以从 DXF 读到的 insert 就是对齐点本身，验证要按 DXF 的实际值来。

### 七、2.89% 的宽度残差

按字形轮廓量完之后，宽度还有恒定 +2.89%。查过 `OS/2.sCapHeight`、`usWinAscent`、`hhea.ascent`、`unitsPerEm` 等所有候选参考高度，**没有一个能解释这个比例**，而同名文字的短串、长串比例完全一致。判定为 AutoCAD 的渲染差异，按字体实测并标定：

```python
_WIDTH_RATIO = {
    "simhei.ttf": 1.028902,
    "simsun.ttc": 1.022867,
}
```

标定后宽度误差归零。

### 八、`msyh.ttc`（微软雅黑）测不准

同样的文字、同样的字高，三个字体在 AutoCAD 里的宽度：

| 字体 | AutoCAD 宽 | ezdxf 轮廓宽 | 比值 |
|---|---|---|---|
| simhei.ttf | 1478.7 | 1521.4 | 1.0289 |
| simsun.ttc | 1476.3 | 1510.0 | 1.0229 |
| **msyh.ttc** | **2066.7** | **1736.0** | **0.8400** |

前两个方向一致（略宽），msyh 反向偏 16%，**没有任何常数能同时修正三种字体**。已在代码里标为不可靠字体，命中时在结果里给出 note，而不是假装准。

---

## 处理

最终做法（`tools/text_overlap/textbox.py`）：

1. **自己取 MTEXT 的视觉行**：组码 41 > 0 才用 `text_wrap`，`0` 表示不换行、只按 `\n` 断。
2. **按字形轮廓量宽度**：`font.text_path(text).extents()`，不用 `text_width()`。
3. **字体名剥掉路径**：`os.path.basename`，避免 ezdxf 走退化度量。
4. **字高从 `A` 的轮廓量**：恒等于 char_height，避开 `total_height` 的字体差异。
5. **行距用 5/3**。
6. **对齐点按 1-3 顶 / 4-6 中 / 7-9 底**，在实体自身坐标系算完再转到 WCS，旋转自然正确。
7. **宽度按字体标定**（除以实测比值）。
8. **高度兜底不低于一个字高**：破折号这类无升降部的字符，AutoCAD 仍按字高给框。

检测逻辑（`tools/text_overlap/overlap.py`）：

| 类型 | 判据 | 为什么这么定 |
|---|---|---|
| `text_text` | 两框交集面积 / **较小框**面积 ≥ 15% | 用较小框而不是并集，长注释压短轴号才不会被稀释掉；15% 的下限放过紧贴的表格内边距 |
| `text_curve` | 曲线穿过文字框**内缩 5%** 后的核心区 | 外圈 5% 放过下划线、外框、引线碰到角上的情况；只有真正**穿过**文字才算 |

不检查的实体：`DIMENSION`（标注的尺寸线与文字本来就贴合）、`HATCH`、`INSERT`/`TABLE`（块内文字不展开）、`SOLID`、`POINT`、`LEADER`、`VIEWPORT`。

---

## 验证方法（可复现）

验证的核心是**拿 AutoCAD 自己的答案当基准**，不是拿自己算的当基准。

### 基准从哪来

```python
app = win32com.client.Dispatch('AutoCAD.Application')
doc = app.Documents.Open(r"...\gpu_dc_100.dxf")
for e in doc.ModelSpace:
    if e.ObjectName == "AcDbMText":
        mn, mx = e.GetBoundingBox()      # AutoCAD 自己算的
```

310 个 MTEXT 全部导出，逐一对齐。

### 三个验收脚本

| 脚本 | 作用 | 结果 |
|---|---|---|
| `draw_test/overlap_proto/clean.py` | 干净图纸（27 文字，全部留足间距）必须 0 条 | PASS |
| `draw_test/overlap_proto/planted.py` | 植入 6 类缺陷必须全检出，对照组不得误报 | PASS（6/6） |
| `draw_test/overlap_proto/anchors2.py` | 9 个对齐点 + 旋转，比**绝对坐标** | PASS（≤2.89 单位） |

`crosscheck.py` 是受控对照：在 AutoCAD 里新建一张图、写 11 个已知文字、`SaveAs` 成 DXF、逐条比。宽度误差全部 **0.00%**（msyh 除外），高度 ≤2.89%，多行高度 **0.00%**。

### 精度数字怎么读

- **不要只看宽高**。只比尺寸会把 attachment point 7-9 那类「尺寸对、位置错」的问题全部漏掉——必须比绝对坐标（`anchors2.py` 就是为了这个写的）。
- **对照实验是必须的**。`clean.py` 那 27 个文字如果没有报 0 条，检测器就不能用；`planted.py` 的对照组没被误报，说明 15% 阈值不是靠运气。
- **`accoreconsole` 这条路走不通**。本机 `accoreconsole.exe` 返回 `Version W.60.0.0` 并提示「未授权、运行于评估模式」，LISP 脚本**不会执行**，一直卡在 `命令:` 提示符（`timeout` 报 124）。只能改用运行中的 AutoCAD + COM。

---

## 预防

1. **别用 `ezdxf.bbox` 量 MTEXT。** 组码 41 = 0 的换行 bug 会让框大出数倍，且**不报错**。要量就自己按字形轮廓算。
2. **字体名一律取 basename 再喂给 ezdxf。** 完整路径会静默退化 33%，两者类型都是 `TrueTypeFont`。
3. **字体度量优先从字形轮廓取，不要读 `measurements`。** `total_height` / `baseline` 在部分字体（尤其 `.ttc` 集合）上是退化的。
4. **验证位置一定要比绝对坐标**，只比宽高会漏掉对齐语义错误。
5. **判断「准不准」必须拿 CAD 自己的答案当基准。** 自己算完自己验，等于没验。
6. **不受支持的能力要给 note，不要给信心。** 无标定字体、msyh、上标 `²` 都在结果里显式说明；上标偏差方向恒为「偏宽」，意味着会多报而不会漏报——这是安全的方向。

---

## 附：检测器在样例图纸上的实际输出

`gpu_dc_100.dxf`（6 条，逐条已核实为真缺陷）：

```
1. text_text at (12510, 24039)
   D7 [A-TEXT] C
   crosses D2 [A-TEXT] B
   overlap 41% of the smaller box
```

轴 B 在 y=23920、轴 C 在 y=24160，**两轴线仅相距 240，而字高 400 的字符框高约 486**——必然互压。这是图纸本身的缺陷。

```
3. text_curve at (27600, 27480)
   252 [A-TEXT] CRAC-5
   crosses C1 [A-AXIS] LINE
```

`C1` 是 x=27400 的竖直轴线，直接穿过 `CRAC-5` 标签框（框横跨 26972..28228）。

同类还有 `GPU 智算机房`、`288.0 m² 100 柜 × 12 kW` 被 x=21400 的轴线穿过，`监控大屏 4×4` 被门线穿过。

**注意**：轴号文字压在轴线上，在建筑制图里是**正常惯例**。工具报出来是让使用者知情并判断，不是命令他去改。这点已写进技能的说明里。

## 第二轮：覆盖块、表格、标注（同日追加）

第一版只读空间里的直接文字，块内、表格内、标注内的文字全部漏掉。逐项补上后，
又踩到 4 个坑，其中两个会静默给出错误结果。

### 九、块内文字被完全跳过，却报「0 文字、0 交叠」

一张由块引用组成的图（房间标签、设备编号通常都放在块里）会被报成「干净」。

```
modelspace: [('INSERT','TAG'), ('INSERT','TAG')]   # 每个块里有一个 MTEXT
detector:   {'texts_total': 0, 'by_kind': {'text_text': 0}}   # 报"干净"
```

这直接违反 AGENTS.md 第 6 条：**未完成的扫描不能当成通过**。

### 十、`entity.transform()` 保留旋转 —— 是我自己又加了一遍（结论已更正）

> **更正**：本节最初写的是「`transform()` 会静默丢掉旋转」。**这是错的。**
> 后续用 TEXT 实体复核时发现，`transform()` 会把块引用的旋转**写进实体自身**：
> MTEXT 写进 `text_direction`，TEXT 写进 `rotation`。真正出错的是我在
> `transform` 之后**又按矩阵角度补了一次旋转**，等于加了两次。

为什么第一轮没暴露：MTEXT 一旦有了 `text_direction`，`rotation` 属性就不存在，
所以「在 0 的基础上再加一次」看起来是对的——那批断言恰好通过了。换成 TEXT 就露
馅：它同时有 `rotation`，被在**已经正确的 65°** 上再加 65°，框变成 110°。

复现（TEXT 在 65° 块里）：

```
不补旋转（正确）：  h/w = 1.8   <- 65° 形状
补一次（错误）：    h/w = 2.75  <- 110° 形状
```

修法是把手写的「从矩阵反解 rotation 再设回去」整段删掉，直接
`transform()` 后用实体自身的值。回归测试 `test_rotation_is_not_applied_twice`
用 h/w 落在 1.4–2.2 来卡住这个错误，TEXT 与 MTEXT 各一条。

非均匀缩放/镜像时（轴不再垂直或长度不等）框是平行四边形，轴对齐框表达不了，
**报为未检查**而不是给个近似值——这条原结论不变。

### 十一、`virtual_entities()` 不返回 ATTRIB

带属性的块（设备编号这类**每次插入都不同**的文字）完全读不到：

```
virtual: [('MTEXT', 'FIXED')]     # ATTRIB 不在里面
attribs: 2 个，但 virtual_entities 一个都不返回
```

绕法：直接读 `insert.attribs`。好消息是 ATTRIB 的 `insert`/`rotation`/`height`
**已经在 WCS 且已按块缩放**，不需要再套矩阵：

```
INSERT insert (5000,7000) rot 30 scale 2 x2
ATTRIB insert (5000,7000) height 400 rot 29.999...   # 已变换好
```

### 十二、表格单元格：不读就等于整表消失

`ACAD_TABLE` 自己什么都不画——单元格是 MTEXT、格线是 LINE，全在一个匿名块里，
由表格的 `block_record_handle` 指向它：

```
TABLE 49C n_rows=262177 n_cols=0 block_record_handle=49D
  -> 块 *T19: {'MTEXT': 31, 'LINE': 15}
```

`123_check.dxf` 里有 3 个这样的表格（门表、窗表、房间表），第一版全部漏掉。

**这里还踩了一个：** 第一版把单元格按单位矩阵放在原点，结果 3 个表格的 55 个
单元格全叠在一起，报出 54 个"文字互压"（ratio=1.000）。表格自己的 `insert`
没有应用。补上后误报归零：

```
table insert (13600,8000) + horizontal_direction (1,0,0)
  49C: acad (13600,5900)-(19350,8000)   mine (13803,6011)-(19143,7890)  31 格  ✓ 全在内
  4CF: acad (13600,3650)-(18350,5400)   mine (13803,3760)-(18143,5290)  21 格  ✓
  4F5: acad (13600,900)-(17850,3000)    mine (13834,1010)-(17566,2890)  15 格  ✓
```

### 十三、标注文字：`*D` 块是「样式单位装饰 + 图纸单位位置」的混合体

这是最绕的一个。`*D` 块里的几何：

| 元素 | 实测值 | 说明 |
|---|---|---|
| 延长线跨度 | 500.625 | 图纸单位（与 defpoint 差吻合） |
| 尺寸线跨度 | 2115 | ≈ 实际测量值 2120 |
| 箭头长度 | 2.534 | = `DIMASZ` 2.5，**样式单位** |
| 文字字高 | 2.5 | = `DIMTXT` 2.5，**样式单位** |
| 延长线间隙 | 0.625 | = `DIMEXO` 0.625，**样式单位** |

**位置是图纸单位，装饰是样式单位。** 所以不能整体缩放（会把位置移走），
正确做法是：以块的墨迹框为形状，按 `DIMTXT × DIMSCALE` 算出作图高度，再把中心
对齐到已验证正确的 `text_midpoint`。

`123_check.dxf` 的 `$DIMSCALE = 50`，于是作图高度 = `2.5 × 50 = 125`，与同图其他
文字（120-250）吻合。

项目自己的 `engineering/arch/draw.py:381` 早就记录过这个道理：

> "Drawn at the style's DIMSCALE 1, a 1:50 chain's 2.5 text was 2.5 drawing units
> — 0.05 mm on the sheet, which is no text at all."

### 顺带发现的两处真实图纸缺陷

| 文件 | 缺陷 |
|---|---|
| `123_check.dxf` | 房间表里 `TELECOM EQUIPMENT ROOM` 单元格宽 2506，被 x=14350 的列格线穿过 |
| `datacenter_plan_200558.dxf` | `$DIMSCALE = 1` 而 `$DIMTXT = 2.5`，13 个标注文字只有 **2 单位**高，同图其他文字是 125 —— 出图等于没有标注文字 |
| `telecom_equipment_room_plan_fixed.dxf` | 同上，18 个标注文字 |

第二、三处催生了新的第三类检查 `text_scale`：比较每个文字的**自然高度**（已还原
旋转）与全图中位数，偏离超过 4 倍就报。

### 又一个误报：旋转文字被当成尺度异常

第一版 `text_scale` 用轴对齐框的高度，两个 90° 竖排的「封闭冷通道」框高 1627
（横排的 4.68 倍）被误判。改为比较 `char_height`（与旋转无关）后误报归零。

### 这一轮的验证

| 项 | 结果 |
|---|---|
| 单元/端到端测试（不需要 AutoCAD） | **24 个函数 / 60 条断言全通过** |
| 干净图误报 | 0 |
| 植入 6 类缺陷 | 6/6 全检出，对照组不误报 |
| 310 个真实 MTEXT 精度 | 89% ≤3%、97.4% ≤5%、98.4% ≤8%（**无回归**） |
| 9 个对齐点 + 旋转 | ≤ 2.89 单位 |
| 表格单元格位置 | 3 个表全部落在 AutoCAD 表格范围内 |

### 这一轮新增的坑（已并入第 10 节排错表）

- `virtual_entities()` 不含 ATTRIB
- 表格单元格在 `*T` 块里，要用 `block_record_handle` 找
- `*D` 块混用单位；标注文字高度 = `DIMTXT × DIMSCALE`
- `GetBoundingBox` 对 DIMENSION 返回几何框、不含文字（实测 DIMTXT 2.5/25/125 与
  DIMSCALE 1/50/200 六种组合，框都是 1000×203.1）
- `accoreconsole` 未授权导致 LISP 不执行，验证只能靠运行中的 AutoCAD

> `transform()` 那条**结论有误**，已在本节第十项更正：它保留旋转，是我重复加了
> 一次。不要按「会丢旋转」去写代码。


### 「310 个精度」到底在说什么（补注）

这份数字容易被误读，写清楚：

**样本**：`gpu_dc_100.dxf` 里全部 310 个 MTEXT，字体统一 `simhei.ttf`。
不是什么抽象抽样，就是那一张图里的所有文字。

**基准**：AutoCAD 自己的 `GetBoundingBox()`（经 COM 取得），存成 CSV 逐条对比。

**误差分布**（按尺寸，宽高取较大误差）：

| 误差上限 | 通过 | 占比 |
|---|---|---|
| ≤1% | 34 | 11.0% |
| ≤2% | 60 | 19.4% |
| ≤3% | 276 | **89.0%** |
| ≤5% | 302 | **97.4%** |
| ≤8% | 305 | **98.4%** |
| ≤15% | 308 | 99.4% |

**误差最大的几个，逐个查过，全是带 `m²` 的文字**：

```
3A3  w误差 18.72% h误差 19.08%  '288 m²'
27A  w误差 15.96% h误差 17.75%  '70.8 m²'
363  w误差 14.17% h误差  2.89%  '面积 (m²)'
```

原因：AutoCAD 把 `²` 当**上标叠放**（缩小+抬高），ezdxf 的字形轮廓把它**当普通字符排在同一行**，所以偏宽。
**方向是偏大 —— 只会多报，不会漏报**，这是安全的方向。

**位置误差必须单独说**：

| 指标 | 值 |
|---|---|
| 角点最大偏移中位数 | 2.80 单位 |
| 角点最大偏移最大值 | 222.12 单位 |

那个 222 单位的（handle `3BC`，`7. 主机房楼面荷载不小于 16 kN/m²…`）拆开看：

```
左边界  mine=58000.0   acad=58000.0    <- 完全一致
右边界  mine=68606.0   acad=68383.8    <- 差 222
```

**不是位置算错，是框宽了 222。** 单独量「对齐点所在那个角/边」：

| 指标 | 结果 |
|---|---|
| 锚点水平误差 | 中位数 **0.000**，最大 **0.000** |
| 锚点垂直误差 | 中位数 **0.000**，最大 **0.000** |
| 282/282 通过 | 是（含旋转的 28 个已排除） |

**结论**：文字**放在哪**是精确的（误差 0）；**框多大**最多差 8%（98.4% 的样本），且偏大。
所以不能说"整体精度 89%"——**位置的精度远高于此**。

## 更新说明

- 2026-11-18 首次记录。基于 ezdxf 1.4.4 实测；8 个根因均含可复现证据。检测器已通过三项验收（干净图 0 误报 / 植入 6 类全检出 / 9 对齐点 ≤2.89 单位）。
- 2026-11-18 第二轮：补齐块内文字（含嵌套/旋转）、ATTRIB、表格单元格、标注文字，新增 `text_scale` 检查。追加 4 个根因（第九至十三节）。测试扩到 35 项，精度无回归。
- 2026-11-18 第三轮：补三个盲区 ——（十四）TEXT 在旋转块里被重复加旋转，是我自己的错，第十节已更正；（十五）合并单元格已验证 AutoCAD 行为正确，不是盲区；（十六）新增 `text_illegible`，按视口比例折算到纸面毫米并与真实 PDF 交叉验证。测试 24 函数 / 60 断言。技能重构为 `SKILL.md` + `references/` 六篇 + `assets/` 的目录结构。
- 2026-11-18 第四轮：**拿用户的真实图纸跑，暴露四处该优化的地方**（十七至二十）。新增第七类检查 `text_glyphless`，报告加文字样式。测试 27 函数 / 75 断言。

## 第四轮：跑真实图纸才暴露的问题

前面三轮用的都是自己造的样例。这一轮直接跑用户机器上的六张图（`123`、`Drawing7`、`telecom`、`telecom_fixed`、`datacenter_plan_200558`、`gpu_dc_100`），立刻发现四处：

### 十七、同一对文字被报两次，读起来像两个缺陷

`123.dxf` 里两组完全重合的文字，同时命中 `text_text` 和 `text_duplicate`，因此
两组缺陷产生了 **4 条**结果：

```
text_text      10F <-> 8DB      <- 同
text_text      110 <-> 8DC      <- 一
text_duplicate 10F <-> 8DB      <- 件
text_duplicate 110 <-> 8DC      <- 事
```

而且 `text_text` 给的 `fix` 是「挪开」——对重复项来说是**错的做法**，挪开之后两行字
都还在图上。

修法：`_drop_duplicate_collisions()` 删掉被 `text_duplicate` 覆盖的 `text_text`
行，保留后者。同时给 `text_duplicate` 补上 `entity_delete` 建议：

```
fix: entity_delete(handle='8DB')
     keep 10F and delete 8DB, or the other way round - the two are identical
     apart from their handle
```

结果：`123.dxf` 从 5 条降到 3 条，且每条都是不同的缺陷。

### 十八、块内文字拿不到 `fix`，却不说为什么

块展开出来的文字 handle 形如 `50A in 4F5`，`entity_move` 拿它**什么都动不了**。
原来的代码直接 `continue`，于是 `fix` 是空 —— 而空的 `fix` 读起来像「查过了，
没问题」。

修法：显式说明该去哪里改。

```
this text lives in block reference 4F5; move or edit it inside the block
definition, not here.  ``entity_move`` needs the handle of a top-level entity
```

### 十九、新增第七类检查 `text_glyphless`：字在屏幕上没事，打印出来缺字符

这是这一轮最有价值的发现，而且**它正是 AGENTS.md 第一号坑，却从来没被检查过**。

跑用户的三张图，`Drawing7`、`datacenter_plan_200558`、`telecom`（含 fixed）全部命中：

```
text_glyphless at (3847, 3662)
   EC [A-ROOM-T-N] 52.92 m² [style Standard]
   note: 7 text(s) use style 'Standard' (font 'txt', no CJK/Unicode fallback)
         and contain '²': those characters do not plot
```

即：这些图的 `m²` 在图上看着正常（AutoCAD 编辑器里 `²` 有替代显示），
**打印出来会变成 `m`**。

判定逻辑只能靠一条可证实的边界：

| 字体类型 | 缺字形时 | 能否用 cmap 判断 |
|---|---|---|
| SHX（`txt.shx`） | **静默不画** | — |
| TrueType（`simhei.ttf`） | **自动回退到别的字体照样画** | ❌ |

实测证据：`simhei.ttf` 的 cmap 里**没有 U+00B2**，但 AutoCAD 用它渲染 `m²` 完全正常。
所以任何基于 cmap 或字形轮廓的判断都会误报。三条路都试过，全部不可靠（见
`references/pitfalls.md` 第 17 条）：

| 方法 | 结论 |
|---|---|
| `fontTools` 查 cmap | `simhei` 说没有 `²`，但 AutoCAD 画得出来 |
| ezdxf `text_path("²")` | 找不到字体时静默回退成默认字体，永远「有」 |
| 字符宽度 vs 空格宽度 | 回退字形和真字形都有宽度，无法区分 |

最终只跑可证实的那一条：**SHX 样式且 `bigfont` 为空**。带 bigfont 的 SHX 放行
（big font 正是提供 CJK 字形的），TrueType 一律不管。

### 二十、报告不显示文字样式，而样式恰恰是修法

`_collect_texts` 一直在收 `style`，但从没输出过。而 `text_glyphless` 的修法就是
换样式 —— 不显示样式，用户还得回 CAD 里查。

加上 `[style CN]` 标签后，顺手发现一个隐藏问题：

```python
entity.dxf.get("style", "")   # 123.dxf 里 142 个文字中 136 个返回 ""
```

DXF 语义里属性缺席就等于 `Standard`。原来的代码于是对绝大多数标签报「无样式」，
恰好掩盖了它们**全都在 `Standard`**（即 `txt.shx`）这个事实。加 `_style_of()` 补默认值。

### 顺带更正一处旧结论

`references/pitfalls.md` 第 7 条标题还写着「`transform()` 保留缩放、丢掉旋转」——
这是上一轮已更正、但这里漏改的。已改为「旋转会被应用两次」，并说明了当初为什么会
误判（MTEXT 的 `rotation` 属性在 `text_direction` 存在时缺席，导致「在 0 上加一次」
看起来正确）。

### 对用户图纸的实际修复与复测

`123.dwg` 三处都修了，逐步复测：

| 步骤 | 操作 | `by_kind` 变化 |
|---|---|---|
| 起点 | — | `text_curve:1, text_duplicate:2, text_glyphless:1` |
| ① 删重复 | 删 `8DB`、`8DC` | `text_duplicate` → 0，露出真实的 `text_scale:1` |
| ② 改样式比例 | `ISO-25`/`Standard`/`Annotative` 的 `dimscale` → 50 | `text_scale` → 0 |
| ③ 换字体 | `Standard` 字体 `txt` → `simsun.ttc` | `text_glyphless` → 0 |
| 结果 | `123_fixed3.dxf` | **全部清零** |

第 ① 步顺带印证了一件事：重复项删掉后，原本被挤在后面的 `text_scale` 才浮出来 ——
**修完一处要重跑**，否则会漏掉下一处。

### 这一轮的验证

| 项 | 结果 |
|---|---|
| 测试 | **27 个函数 / 75 条断言全通过**（新增 3 个函数 15 条断言） |
| 干净图 `clean.dxf` | 仍 0 条 |
| 植入图 `planted.dxf` | 仍 6/6，对照组不误报 |
| 用户 6 张图 | 全部跑通，无崩溃 |
| 修复复测 | `123` 三处逐项归零 |

## 第三轮：三个盲区

### 十四、TEXT 在旋转块里被加了两次旋转（不是 ezdxf 的问题，是我的）

`_measure_in_block` 在 `entity.transform(matrix)` 之后又按矩阵的 +X 方向算了一次
角度并设回实体。见本节第十项的更正说明。影响范围：**只有 TEXT**，MTEXT 因为
`text_direction` 存在时 `rotation` 属性缺席而侥幸正确。字高缩放一直是对的。

修好后 TEXT 与 MTEXT 在 65° 块里都量出 65° 的形状（h/w = 1.8），回归测试用
h/w 落在 1.4–2.2 卡住。

### 十五、合并单元格：不是盲区，AutoCAD 本来就算对了

原本担心表格合并后单元格文字的位置会算错。用一张 AutoCAD 亲手建的 5×3 合并表
（`verify/merged_table.dxf`，插入点从 5 移到 15，15 个格子并成 13 个）验证：
自动合并后 `*T` 块里只剩**一条** MTEXT，位置就是合并区的中心。

也就是说 `*T` 块已经反映了合并结果，不需要额外合并逻辑。此结论已有测试
`test_merged_table_cells_keep_correct_text` 固定。

### 十六、新增 `text_illegible`：出图后小到看不见

前面五类检查都在模型空间里比大小，但「看不清」是**纸面**上的概念。同一个 160
单位的文字，1:100 出图是 1.6 mm（低于 ISO 3098 的 2.5 mm 下限），1:20 出图是
8 mm（绰绰有余）。

算法：

```
纸面毫米 = 模型字高 × 每单位毫米数 / 视口比例
视口比例 = VIEWPORT.view_height / VIEWPORT.height
```

`$INSUNITS` 给每单位毫米数（14 种单位已映射，0=无单位则不检查并说明）。
没有图纸空间视口的纯模型 DXF **不出任何条目** —— 没有图纸，就无所谓纸上太小。

**交叉验证**：把一张图的 PDF 真实导出，在我的测量结果里挑出两个已知尺寸的标注
（应打印 10 mm 和 100 mm），两边计数完全吻合（10 与 100），1.4% 的残差可归因于
em/cap 换算差异。

`gpu_dc_100.dxf` 上这一项报出 6 组、共 129 个文字（1.5–2.3 mm），都是真问题：
该图视口比例 1:100 而多数标签字高 150–230 单位。

### 顺带修掉的两个自己造成的 bug

| 现象 | 根因 | 修法 |
|---|---|---|
| 输出报表时进程崩溃 `UnicodeEncodeError: 'gbk' codec can't encode character '\xb2'` | 中文 Windows 控制台是 GBK，编码不了 `²`。检查本身已经成功，死在打印上 | `__main__` 启动时把 stdout/stderr `reconfigure(encoding="utf-8", errors="replace")` |
| 12 条结果只报了 6 条的名字（`text_illegible` 6 条隐形） | `_human()` 的摘要漏了这个新 kind | 补齐，并加一道对账：摘要计数之和 ≠ 结果总数时明确打印差额 |

第二个正是我自己写在 `references/pitfalls.md` 里那条纪律——**新增 kind 必须同时
注册到摘要**——只是当时没执行到。教训：纪律要写成代码里的对账，不要写成文档里的
提醒。