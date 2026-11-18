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

它检查六类问题：

| 类型 | 人话解释 |
|---|---|
| `text_text` | 两行字压在一起了 |
| `text_curve` | 有根线从字中间穿过去了（墙线、轴线、表格线都算） |
| `text_scale` | 这行字比图里其他字小得离谱（比如标注文字只有 2 单位高，别的字 125） |
| `text_hidden` | 这行字在**关掉的图层**上——屏幕上可能看不见，**打印出来一定没有** |
| `text_duplicate` | 同一行字被画了两遍，叠在一起（复制粘贴留下的） |
| `text_illegible` | 这行字**打印到纸上**小于 2.5 mm，出图后看不清 |

最后一类比较特殊：它算的是**纸上**的大小，不是模型里的大小。同样 160 单位高的字，
1:100 出图只有 1.6 mm（看不清），1:20 出图有 8 mm（没问题）。所以它只在图纸里
有图纸空间视口时才报——纯模型的图没有「纸上」这回事。

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
| `6 finding(s)` | 找到 6 个问题，下面按类型分开统计 |
| `1. text_text at (12510, 24039)` | 第 1 个问题，位置在图上的 x=12510, y=24039 |
| `D7 [A-TEXT] C` | 这行字叫 `C`，在 `A-TEXT` 图层，图元编号 `D7` |
| `crosses D2 ... B` | 它压住了另一行字 `B`（编号 `D2`） |
| `overlap 41%` | 重叠了 41%（按较小的那个框算） |
| `fix: entity_move(...)` | **怎么改**：把 `D7` 往右挪 286.5 单位 |

> 上表是同一张图 `gpu_dc_100.dxf` 的**完整实测输出**，现在实际是 **12 条**
> （2 互压 + 4 穿线 + 6 出图过小）。完整原文见
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

### 情况二：写 `no safe shift`

```
no safe shift: no short shift clears this text - something is on every side of it.
Move or shorten whatever crosses it, or resize the text
```

**意思是：这行字四面八方都被挡住了，挪不开。** 这不是工具偷懒，是它试过所有方向、所有距离，都还是会撞到东西——所以诚实地告诉你，而不是给你一个没用的建议。

这时你有三个选择：

| 做法 | 什么时候用 |
|---|---|
| 挪**穿过去的那根线** | 那根线是可以动的（比如一道墙可以开洞、一条轴线可以改短） |
| 把字改短 | 文字太长，比如「TELECOM EQUIPMENT ROOM」缩成「TE ROOM」 |
| 把字改小 | 但如果改小就变成 `text_scale` 问题了，慎用 |

### 情况三：`text_scale`

```
text_scale at (940, -618)
   F3 [A-DIMEN-T-N] 2120
   note: 13 DIMENSION text(s) drawn 2.0 units tall against a drawing median of 125.0 (0.02x)
```

**意思是：图里所有字基本都是 125 高，但这 13 个标注文字只有 2 单位高——打印出来等于看不见。**

这通常不是谁手动改坏了，而是**标注全局比例没设对**：

- AutoCAD 里输入 `DIMSCALE` → 回车 → 改成 `50`（如果图是 1:50 出的）
- 或者输入 `DIMSTYLE` → 修改 → `调整` 标签 → `使用全局比例` 填 50

改完，所有标注文字会一起变大，不用一个一个调。

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

```
text_duplicate at (12500, 3000)
   1A2 [A-TEXT] D-101
   with 1A3 [A-TEXT] D-101
   note: the same text twice in the same place - one of them is a duplicate
```

**意思：`D-101` 这行字被画了两次，位置几乎重合。**

常见原因：复制粘贴时忘了删原件，或者镜像/阵列多留了一份。

**为什么是问题：** 表面看没影响，但**统计数量会错**——门表说 4 樘门，图上数出 5 个编号。而且以后改一处，另一处不会跟着变。

**怎么改：** 选中其中一个 → `ERASE`（删除）→ 检查剩下的那个内容对不对。

**注意**：如果两行字离得远（比如两个房间都叫「走廊」），工具**不会**报——那本来就是两个不同的标签。

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