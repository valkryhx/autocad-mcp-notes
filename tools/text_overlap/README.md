# tools/text_overlap

文字与图形交叠检查。用来在 DXF 上找出文字压文字、线条穿过文字的情况，报出
handle、图层、文字内容和精确位置。

## 用法

```bash
python -m tools.text_overlap FILE.dxf            # 人读的报表
python -m tools.text_overlap FILE.dxf --json     # 机读
python -m tools.text_overlap FILE.dxf --layout Layout1
python -m tools.text_overlap FILE.dxf --quiet    # 只看退出码
```

退出码：`0` 无交叠，`1` 有交叠，`2` 文件读不了。

**只吃 DXF。** DWG 要先在 AutoCAD 里 `SaveAs` 成 DXF（`AcSaveAsType` **61**），
或用 MCP 的 `drawing_save_as` 写一份。

依赖 ezdxf 与 fontTools（`D:/git_codes/Autocad-MCP/.venv` 里都有）。

## 输出含义

| kind | 含义 |
|---|---|
| `text_text` | 两个文字的框相交，且交集 ≥ 较小框的 15% |
| `text_curve` | 一条曲线穿过文字框内缩 5% 后的核心区 |
| `text_scale` | 文字高度偏离全图中位数超过 4 倍 |
| `text_hidden` | 文字在关闭/冻结的图层上（打印不出来） |
| `text_duplicate` | 同一文字叠在同一位置（复制粘贴留下的），附 `entity_delete` 建议 |
| `text_illegible` | 经视口折算后，**纸面**尺寸低于 ISO 3098 的 2.5 mm |
| `text_glyphless` | 用了 SHX 样式（`txt.shx` 等），而它的字形表里没有这些字符 |

15% 的下限放过紧贴的表格内边距；5% 的内缩放过下划线、外框、引线碰到角上的情况
——只有真正**穿过**文字才算。

`text_scale` 抓的是完全不重叠的那类缺陷：`$DIMSCALE` 为 1 而 `$DIMTXT` 为 2.5 的
图，标注文字只有 2.5 单位高（其他文字 125），出图等于没有标注文字。比较高度时
**已把旋转还原**，竖排文字不会被误判。

`text_illegible` 是唯一按**纸上毫米**判断的检查：模型字高 × 每单位毫米数 ÷ 视口的
`view_height / height`。没有图纸空间视口的纯模型图不出条目——没有图纸，就无所谓
纸上太小。`$INSUNITS` 为 0（无单位）时同样跳过并说明。

`text_glyphless` 抓的是「图上正常、打印缺字」：`Standard` 的 `txt.shx` 是单线字体，
字形表里没有 CJK 也没有 `²`/`Ø`/`±`，AutoCAD **静默不画**。只报 SHX 且无 `bigfont`
的样式——TrueType 缺字形时会回退到别的字体照样画，实测 `simhei.ttf` 的 cmap 里
没有 U+00B2 却能正常渲染 `m²`，所以任何基于 cmap 的判断都会误报。详见
[`docs/20261118-text-overlap-check.md`](../../docs/20261118-text-overlap-check.md) 第四轮。

报表里文字会带 `[style 名字]`。`text_glyphless` 的修法是换样式，而样式没法从图层
和内容推出来，所以必须印出来。DXF 里属性缺席即等于 `Standard`，`_style_of()` 负责补
这个默认值。

**一条不等于一行字。** `text_scale` / `text_hidden` / `text_illegible` /
`text_glyphless` 是分组检查，同类问题压成一条。摘要因此按实际文字数报：

```
12 finding(s): 2 text-on-text, 4 text-on-geometry, 6 too small on paper (129 texts)
```

`Finding.affected` 就是这个组覆盖的文字数，JSON 里为 `affected_texts`（仅 ≠1 时输出）。
实测 `gpu_dc_100.dxf`：6 条 illegible 覆盖 129 个文字（占全图 40%）。

`text_curve` 的 `note` 会写**穿入深度**——最严重那条曲线在完整文字框内的裁切长度
占字高的百分比。100% 表示整条切断，20% 以下只是蹭边。判定用内缩 5% 的核心区，
度量用完整框，两者用途不同。

**块、表格、标注里的文字都会被读**，不再跳过：

- 块引用会展开（含嵌套，最深 8 层），变换矩阵逐层应用
- 块的 `ATTRIB` 值会读（`virtual_entities()` 不返回它们）
- 表格单元格文字经由 `block_record_handle` 找到 `*T` 块后读取
- 标注文字从 `*D` 块读，尺寸按 `DIMTXT × DIMSCALE` 计算
- 引线（MULTILEADER）文字从 `context.mtext.default_content` 读，字高
  `context.char_height × context.scale`

不检查：`HATCH`、`SOLID`、`POINT`、`LEADER`、`VIEWPORT`，以及标注**自己**的箭头和
尺寸线（它们贴着文字是设计如此；标注文字仍会与其他一切比较）。

跑不了的条目会进 `not_checked` 并带原因（非均匀缩放/镜像的块、块内读不到文字
等），**不会静默丢弃**。`not_checked` 非空时不能说「图是干净的」。

**空结果只代表「本次检查范围内没有交叠」**，不代表图是好的。

## 精度

文字框按字形轮廓构建，并与 AutoCAD 的 `GetBoundingBox` 逐条对齐：

| 指标 | 结果 |
|---|---|
| 框宽 vs AutoCAD | 已标定字体（`simhei.ttf`、`simsun.ttc`）**完全一致** |
| 框高 vs AutoCAD | ≤ 2.9% |
| 9 种 attachment + 旋转 90° 的角点位置 | ≤ 2.9 单位（字高 250） |
| 310 个真实 MTEXT | 89% ≤3%，97% ≤5%，98% ≤8% |

已知不可靠，结果里会显式标注：无标定字体（按原始轮廓算，偏宽几个百分点）、
`msyh.ttc`（微软雅黑，偏差 16% 且无常数可修）、上标 `²`（偏宽 14–19%，方向安全
——会多报不会漏报）、非均匀缩放或镜像的块（文字框是平行四边形，轴对齐框表达不了，
报为未检查）。

## 验收

```bash
# 不需要 AutoCAD（33 个函数 / 100 条断言）
python tools/text_overlap/tests_overlap.py

# 需要 AutoCAD 在运行
cd draw_test/overlap_proto
python clean.py        # 干净图必须 0 条
python planted.py      # 植入 6 类缺陷必须全检出，对照组不误报
python crosscheck.py   # 逐字对比 GetBoundingBox
python anchors.py      # 9 个对齐点 + 旋转
```

`tests_overlap.py`、`clean.py`、`planted.py` 不需要 AutoCAD；
`crosscheck.py` 与 `anchors.py` 要实机。

## 安全位移

`text_text` / `text_curve` 的每条结果带一个 `fix`，它**已经对全图所有文字框和
所有曲线验过**，不是「大概挪开就行」：

```python
fix: entity_move(handle='D7', dx=286.5, dy=0.0)  -> 286.50 drawing units right
     verified: tested against every other text box and every curve ...
```

朴素的「刚好挪开压它的那个」实测会失败：`gpu_dc_100.dxf` 的轴号 `D7` 上移 182.5
刚好躲开 `D2`，却正好落在圆 `D1` 上。`_try_shift` 因此对四个方向逐步增大位移，
取第一个与**任何**框和曲线都不相交的距离。四面都被堵死时返回 `fix: None` 并写明，
不猜。

### 多行标签整体移动

房间标注是若干独立实体堆成一列（房名、编号、面积），只挪一行会让标注散架。工具按
四条规则识别同组（`_stack_group`）：同图层同样式、水平重叠 ≥50%、**垂直不相交**、
间隙 ≤1 个字高。命中就给出 `cad_batch`：

```python
fix: cad_batch of 2 entity_move step(s), each dx=1145.09, dy=0.0
     moves 8B ROOM NAME
     moves 8C 288.0 m2
```

用 `cad_batch` 的 `on_error=rollback` 保证不会「移了一半」。

「垂直不相交」这条不能省：两个**互相压住**的文字看起来和上下叠放完全一样，第一版
没排除，结果给了个「整体移」的建议，移完重叠照旧 —— 被
`test_fix_is_verified_safe` 抓到。

整组挪不动时仍给单行建议，但置 `moves_alone: true` 并警告标注会歪。

### 无解时的原因

三种情况该做的事完全不同，`_no_shift_reason()` 分开说：

| 消息 | 含义 | 该做什么 |
|---|---|---|
| `... N units wide and the widest free slot ... is M` | 文字比旁位还宽，平移永远无解 | 拆行或缩短 |
| `... even when its whole N-line label moves together` | 整组都挪不动 | 移走穿过它的线，或改字号 |
| `something is on every side of it` | 真四面被围 | 移走或缩短穿过它的东西 |

## 控制台编码

`__main__` 启动时把 stdout/stderr 重设为 UTF-8。中文 Windows 控制台默认 GBK，
编码不了 `²`（`\xb2`），会在**检查已经成功之后**抛 `UnicodeEncodeError` 把结果
整个丢掉。再遇到乱码是终端渲染问题，用 `--json` 或比对码点，不是数据错。

## 为什么不能用 ezdxf 自带的 bbox

`ezdxf/disassemble.py` 把 DXF 组码 41 的 `0.0`（表示「不换行」）当成箱子宽度
传给 `text_wrap`，其结果判据是 `width(line) > box_width`，于是**每个词都切成
一行**。一张 40 字的注释实测被算成 2534 高，而 AutoCAD 实际是 374——差 6.8 倍，
会凭空造出满图的假重叠。

完整根因（共 8 条）与证据见
[`docs/20261118-text-overlap-check.md`](../../docs/20261118-text-overlap-check.md)。