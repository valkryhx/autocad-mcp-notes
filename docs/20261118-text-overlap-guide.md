# 文字交叠检查 —— 新手操作手册

> 面向：刚开始用 AutoCAD 的人
> 记录日期：2026-11-18
> 配套：`tools/text_overlap/`（工具）、`skills/autocad-text-overlap-check/`（技能）

> **相关文档**
> - [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) — 全部根因与实测证据
> - [`AGENTS.md`](../AGENTS.md) — 使用规范总纲

---

## 一、这个工具在解决什么问题

图上文字压住别的东西，打印出来就是一团黑，谁都看得出来，但画的时候很难发现——尤其是图大了以后。

这个工具会告诉你：**哪一行字、压在什么东西上、在图的哪个位置、以及挪多少能挪开。**

它检查七类问题：

| 类型 | 人话解释 |
|---|---|
| `text_text` | 两行字压在一起了 |
| `text_curve` | 有根线从字中间穿过去了（墙线、轴线、表格线都算） |
| `text_scale` | 这行字比图里其他字小得离谱（比如标注文字只有 2 单位高，别的字 125） |
| `text_hidden` | 这行字在**关掉的图层**上——屏幕上可能看不见，**打印出来一定没有** |
| `text_duplicate` | 同一行字被画了两遍，叠在一起（复制粘贴留下的） |
| `text_illegible` | 这行字**打印到纸上**小于 2.5 mm，出图后看不清 |
| `text_glyphless` | 这行字用的字体**没有这些字的字形**，打印时静默丢掉 |

最后两类比较特殊，算的都是「纸上」而不是「模型里」：

- `text_illegible`：同样 160 单位高的字，1:100 出图只有 1.6 mm（看不清），1:20 出图
  有 8 mm（没问题）。所以它只在图纸里有图纸空间视口时才报。
- `text_glyphless`：图上看着一切正常，**打印出来 `m²` 会变成 `m`**。详见下面第五节。

---

## 二、怎么跑

**第一步：把图存成 DXF。** 工具只认 DXF，不认 DWG。

在 AutoCAD 里：`文件` → `另存为` → 文件类型选 `AutoCAD 2013 DXF (*.dxf)`。

如果你是让 Claude 用 MCP 画的图，直接说「存成 dxf」。

**第二步：跑检查。**

```bash
cd D:/git_codes/test_Autocad_MCP
D:/git_codes/Autocad-MCP/.venv/Scripts/python.exe -m tools.text_overlap 你的图.dxf
```

---

## 三、报告怎么看

报告长这样：

```
你的图.dxf  [Model]
  measured 319 text entities (310 in the space, 0 from 0 block/table container(s)), 377 curves
  6 finding(s): 2 text-on-text, 4 text-on-geometry, 0 off-scale

  1. text_text at (12510, 24039)
     D7 [A-TEXT] C
     crosses D2 [A-TEXT] text B
     overlap 41% of the smaller box
     fix: entity_move(handle='D7', dx=286.5, dy=0.0)  -> 286.50 drawing units right
          verified: tested against every other text box and every curve ...
```

逐行翻译：

| 行 | 意思 |
|---|---|
| `measured 319 text entities` | 一共量了 319 行字（**包括块里、表格里、标注里的**） |
| `6 finding(s)` | 找到 6 条问题，下面按类型分开统计 |
| `1. text_text at (12510, 24039)` | 第 1 个问题，位置在图上的 x=12510, y=24039 |
| `D7 [A-TEXT] C [style CN]` | 这行字叫 `C`，在 `A-TEXT` 图层，用 `CN` 样式，图元编号 `D7` |
| `crosses D2 ... B` | 它压住了另一行字 `B`（编号 `D2`） |
| `overlap 41%` | 重叠了 41%（按较小的那个框算） |
| `fix: entity_move(...)` | **怎么改**：把 `D7` 往右挪 286.5 单位 |

### 「一条」不等于「一行字」

这条最容易被误读。

`text_scale`、`text_hidden`、`text_illegible`、`text_glyphless` 这四类是**分组**的
——同一类问题压成**一条**，不管涉及多少行字。所以摘要里会写成：

```
12 finding(s): 2 text-on-text, 4 text-on-geometry, 6 too small on paper (129 texts)
                                                              ↑ 6 条，但覆盖 129 行字
```

**「6」是 6 组，不是 6 个字。** 报数的时候要说「129 行字太小」，不能说「6 个问题」
——后者会让人以为随手改改就完事了。

> 上表是同一张图 `gpu_dc_100.dxf` 的**完整实测输出**，现在实际是 **12 条**
> （2 互压 + 4 穿线 + 6 组出图过小，共覆盖 135 处文字）。完整原文见
> `skills/autocad-text-overlap-check/assets/sample-report.txt`。

---

## 四、看到 `fix` 之后怎么办

### 情况一：有 `fix` 且有 `verified`

**这个位移是验证过的**——工具会把挪完之后的位置，跟图上**所有**其他文字和所有线条重新比一遍，确认不会撞上别的东西才给你。

它不是随便算的。早期版本就是"从撞到的东西旁边挪开就行"，结果实测发现：把轴号 `D7` 往上挪 182.5 单位，躲开了旁边的 `B`，却正好撞上一个圆。所以现在每条建议都经过全图复核。

**怎么执行**（三种方式，任选）：

1. **让 Claude 执行**（最省事）：
   > 把 D7 向右移动 286.5
   
   Claude 会调用 `entity_move(handle='D7', dx=286.5, dy=0.0)`

2. **自己在 AutoCAD 里做**：
   选中那行字 → 输入 `MOVE` → 回车 → 随便点一个基点 → 打开正交（F8）→ 鼠标往右拖 → 输入 `286.5` → 回车

3. **直接改位置**：选中 → `属性`（Ctrl+1）→ 改 X 坐标，加 286.5

### 情况一之二：`fix` 是一组 `cad_batch`（多行标签）

如果那行字属于一处**多行标注**（比如房名 + 面积分两行写的），工具给的是：

```
fix: cad_batch of 2 entity_move step(s), each dx=1145.09, dy=0.0
     moves 8B ROOM NAME
     moves 8C 288.0 m2
     this text is one line of a stacked label, so the lines above and below it
     move with it - moving this line alone always lands on one of them
```

**意思：这几行是一处标注，必须一起挪。** 只挪一行会让标注看起来歪掉。

**怎么执行**：让 Claude 执行整条 `cad_batch`，或者自己在 AutoCAD 里先把这几行
**一起选中**，再 `MOVE`、输入同一个距离。

> 如果工具给的是单行 `entity_move` 但带着这样的警告：
> 「this line belongs to a 2-line label, but the label cannot move as a whole」，
> 说明整组挪不动，只能挪这一行 —— 挪完标注会歪。更好的做法是重新排版这处标注。

### 情况二：写 `no safe shift`

工具会给三种不同的原因，**先看是哪种**，因为该做的事完全不一样：

```
no safe shift: no shift can free this text: it is 6026 units wide and the
widest free slot beside it is 1159. Shorten it or split it onto two lines
```
→ **文字比旁边的空位还宽，平移永远无解。** 改成两行，或者把内容缩短。

```
no safe shift: no shift clears this text even when its whole 2-line label
moves together (254). ...
```
→ **整组标签一起移也移不动。** 去挪那条穿过它的线，或者调整字号。

```
no safe shift: no short shift clears this text - something is on every side of it.
Move or shorten whatever crosses it, or resize the text
```
→ **真的四面被围。** 看下面的三个选择。

一般的三个选择：

| 做法 | 什么时候用 |
|---|---|
| 挪**穿过去的那根线** | 那根线是可以动的（比如一道墙可以开洞、一条轴线可以改短） |
| 把字改短 / 拆成两行 | 文字太长，比如「TELECOM EQUIPMENT ROOM」缩成「TE ROOM」 |
| 把字改小 | 但如果改小就变成 `text_scale` 问题了，慎用 |

**先看切得多深。** 穿线类的 `note` 里会写穿透程度：

```
note: LINE crosses this text; the worst one runs 100% of the text height inside the box
note: ARC crosses this text; the worst one runs 40% of the text height inside the box
```

| 穿透 | 含义 | 要不要改 |
|---|---|---|
| **100%** | 字被**整条切断**，那行字完全没法看 | 必须改 |
| 50% 上下 | 切断半个字 | 基本要改 |
| 20% 以下 | 只是蹭到边缘 | 常常可以不管 |

实测你的 `telecom_equipment_room_plan.dxf`：`BAT1`、`BAT2` 是 100%（被竖线整条贯穿），
而房间名那条是 40%（门弧擦过左侧）。

### 情况三：`text_scale`

```
text_scale at (940, -618)
   F3 [A-DIMEN-T-N] 2120
   note: 13 DIMENSION text(s) drawn 2.0 units tall against a drawing median of 125.0 (0.02x)
```

**意思是：图里所有字基本都是 125 高，但这 13 个标注文字只有 2 单位高——打印出来等于看不见。**

这通常不是谁手动改坏了，而是**标注比例没设对**。

**关键：要改的是「标注样式」里的比例，不是图纸头的 `DIMSCALE`。**

实测过你的 `123.dwg`：图纸头写着 `$DIMSCALE = 50`，看着像是设对了，但它引用的标注
样式 `ISO-25` 里 `dimscale` 还是 **1.0** —— 所以那 18 个标注文字照样只有 2 单位高。
**改样式才有效。**

- 输入 `DIMSTYLE` → 选中正在用的样式（比如 `ISO-25`）→ `修改` → `调整` 标签 →
  `使用全局比例` 填 `50`（图是 1:50 出的）
- 改完所有用这个样式的标注会一起变大，不用一个一个调

如果图里用了好几个标注样式，每个都要改。

改完记得**重跑一次检查**，确认真的归零。

### 情况四：`text_duplicate`

```
text_duplicate at (1946, 2530)
   10F [A-ROOM-T-N] 01 [style Standard]
   crosses 8DB [A-ROOM-T-N] text 01 [style Standard]
   note: the same text twice in the same place - one of them is a duplicate.
         Delete one rather than moving it
   fix: entity_delete(handle='8DB')
        keep 10F and delete 8DB, or the other way round - the two are identical
        apart from their handle
```

**意思是：同一行字被画了两遍，完全重合。** 报告直接给了删除建议，两个删哪个都行。

**为什么必须修**：图上看着一模一样，但**统计会错**——房间表说一间，图上数出两间。

> 以前这条会同时报成 `text_text` 和 `text_duplicate` 两条，读起来像两个问题。
> 现在同一对只报一次，而且给的是**删除**建议，不是挪开——挪开之后两行字都还在图上。

---

## 五、三类"看不出来"的问题

这三类问题在屏幕上**不一定看得出来**，但都是真缺陷。

### `text_hidden` —— 字在关掉的图层上

```
text_hidden at (0, 0)
   ABC [NOTES] 这是隐藏的注释
   note: 1 text(s) on layer 'NOTES', which is switched off: they do not appear in a plot
```

**意思：这行字在 `NOTES` 图层，而那个图层被关掉了（或者冻结了）。**

屏幕上可能还看得见灰色残影，但**打印的时候一行都不会出现**。AutoCAD 不会警告你。

**怎么改：** 打开图层管理器（命令 `LAYER`）→ 找到 `NOTES` → 把灯泡点亮（或解冻雪花）。

改完再跑一遍检查，确认它没有接着压到别的东西。

### `text_duplicate` —— 同一行字画了两遍

见上面「情况四」，报告会直接给出 `entity_delete` 建议。

> 注意：如果两行字离得远（比如两个房间都叫「走廊」），工具**不会**报——
> 那本来就是两个不同的标签。

### `text_illegible` —— 出图后小到看不清

```
text_illegible at (17100, 29800)
   E6 [A-TEXT] 01
   note: 100 text(s) print at 1.6 mm on layout 'Layout1'; ISO 3098 sets the minimum at 2.5 mm
```

**意思：这 100 行字按现在的视口比例打印出来只有 1.6 mm 高，低于制图标准（ISO 3098）规定的 2.5 mm 下限。**

这条不是「压住了」，是「印出来看不见」——属于另一类缺陷，纸上才能发现。

**怎么改：** 分两种情况。

- **全图都这样** → 说明视口比例选错了，或者文字样式字高没按比例设。改视口比例（双击视口内部 → `ZOOM` → `1:50XP`），或者统一把字高按比例放大。
- **只有几个这样** → 单独把那几个字放大。

**注意**：同一行的 `note` 里写了「N text(s)」，表示这一组有几行字。工具的报法是按打印尺寸分组的，一个尺寸一行，不是一行字一条。

### `text_glyphless` —— 字体没有这些字，打印时丢掉

```
text_glyphless at (3847, 3662)
   EC [A-ROOM-T-N] 52.92 m² [style Standard]
   note: 7 text(s) use style 'Standard' (font 'txt', no CJK/Unicode fallback)
         and contain '²': those characters do not plot
```

**意思：这些字用的是 `Standard` 样式，而 `Standard` 的字体是 `txt.shx`——一个单线
（stroke）字体，它的字形表里没有中文、也没有 `²` `Ø` `±` `³`。**

最坑的地方：**CAD 里看着完全正常**。文字存得对、读回来对，屏幕上也有显示，
AutoCAD 一个字都不警告。但打印（或转 PDF）时那些字符**直接不见**，
`54.48 m²` 变成 `54.48 m`。

**怎么判断这是真的？** 看 `[style ...]` 标签。工具已经把它印出来了，就是让你能直接
定位要改哪个样式。

**怎么改：**

1. AutoCAD 里输入 `STYLE` → 选中那个样式（比如 `Standard`）→ 把字体换成 TrueType：
   `simsun.ttc`（宋体）、`simhei.ttf`（黑体）、`msyh.ttc`（微软雅黑）
2. 或者把这几行字单独指定到已有的 TrueType 样式上

**千万不要**把 `²` 改写成 `%%178`、把 `°` 改成 `%%d`——那些是 SHX 字体的老式控制码，
换成 TrueType 之后会原样打印出 `%%178` 这几个字。

> **为什么只报 SHX 不报 TrueType？** 实测过：`simhei.ttf` 的字符表里其实**没有 `²`**，
> 但 AutoCAD 用它渲染 `m²` 完全正常——TrueType 会自动回退到别的字体去找字形，SHX 不会。
> 所以「字体文件里有没有这个字」这个判断方法会误报。工具只报能确证的那一种。

---

## 六、哪些"问题"其实不用改

这是新手最容易搞错的地方。工具只负责**发现**，判断要不要改是你的活。

| 报告的样子 | 实际是不是问题 | 怎么判断 |
|---|---|---|
| 轴号 `1` `2` `3` 压在轴线上 | **通常不是**（建筑制图惯例） | 轴号本来就该在轴线端头上。看位置对不对就行 |
| 表格里的字被表格线穿过 | **通常是问题** | 文字应在格子里面，不该被格线切。但轻微碰到边线可以接受 |
| 尺寸标注压在自己的尺寸线上 | **工具不会报** | 这是设计如此，已经在工具里排除了 |
| 墙上写着房间名，墙线穿过 | **看情况** | 如果文字在墙中间，说明该处墙没开洞或该挪字 |
| 大段说明文字被轴线穿过 | **通常是问题** | 说明文字不该在轴线上 |

**报告的意义是"让你知道"，不是"命令你改"。** 想保留某个压线，就保留——但你要知道它在。

---

## 七、改完之后必须做的两件事

### 1. 重新存 DXF

在 AutoCAD 里改完，一定要**再存一次 DXF**（覆盖原来那个）。

### 2. 再跑一次检查

```bash
python -m tools.text_overlap 你的图.dxf
```

**在保存后的文件上再检查一遍**——这是这个项目的一条硬规则：内存里改好不等于文件里改好了。改动没存进文件，等于没改。

---

## 八、退出码

如果只是想快速知道「有没有问题」，用 `--quiet`：

```bash
python -m tools.text_overlap 图.dxf --quiet
echo $?          # 0 = 没问题，1 = 有问题，2 = 文件读不了
```

批量检查：

```bash
for f in draw_test/*.dxf; do
  python -m tools.text_overlap "$f" --quiet || echo "有问题：$f"
done
```

---

## 九、常见疑问

**问：为什么 DWG 不行？**
答：DWG 是闭源格式，没有免费库能读。DXF 是纯文本格式，能读。存成 DXF 只要几秒。

**问：`text_curve` 报了好多，都是错的吗？**
答：轴号压轴线是正常的，会占掉大部分。看 `layer` 字段：`A-AXIS` 的是轴线，`A-WALL` 的是墙，`A-DOOR` 是门。墙、门穿过文字通常要改，轴线穿轴号通常不用。

**问：它会不会改我的图？**
答：**不会。** 工具只读。它给出 `entity_move(...)` 的参数，执行不执行、由谁执行，都是你决定。

**问：`measured 319` 但我的图看着没那么多字？**
答：319 包括块里、表格里、标注里的文字。这些在 AutoCAD 里看着是"整个块"或"整个表格"，但拆开是一行一行字。

**问：为什么有的字量不准？**
答：字体没标定的情况下会偏几个百分点（结果里会写 `font has no calibration`）。`msyh.ttc`（微软雅黑）偏差较大，会被标为不可靠。用 `simhei.ttf`（黑体）或 `simsun.ttc`（宋体）最准。

---

## 十、记住这三条

1. **先看 `layer`（图层），再决定要不要改。** `A-AXIS` 上的压线多半正常，`A-WALL` 上的多半要改。
2. **有 `verified` 的 `fix` 可以放心用，但改完必须重跑检查。**
3. **报告是证据，不是命令。** 知道哪里压了比什么都重要，改不改你说了算。

---

## 附：更细的说明在哪

工具的细节已经拆成 `skills/autocad-text-overlap-check/references/` 下的六篇：

| 想知道 | 看 |
|---|---|
| 报告每一行怎么读、每类问题怎么处理 | `reading-a-finding.md` |
| 哪些报告出来但**不该改** | `what-not-to-fix.md` |
| 数字为什么可信（精度、交叉验证） | `accuracy.md` |
| 想改代码 / 遇到量不准 | `pitfalls.md` |
| 改了代码怎么确认没弄坏 | `verification.md` |
| 文件都在哪 | `layout.md` |

本文是给「拿到报告怎么处理」用的；上面那些是给「怎么信这份报告」用的。