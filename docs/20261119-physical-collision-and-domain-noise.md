# 文字检查抓不到的两类缺陷：物理碰撞，与跨领域 critique 噪声

> 记录日期：2026-11-19
> 环境：AutoCAD 2026 (`25.1s`)、`autocad-mcp-pro` 1.8.0、`tools/text_overlap`
> 相关文档：[`20261118-text-overlap-check.md`](20261118-text-overlap-check.md)、
> [`20261119-dxf-save-fails-after-reopen.md`](20261119-dxf-save-fails-after-reopen.md)

## 现象

画机房平面图（4 房间 × 2 排 × 6 机架）时遇到两个**检查盲区**，都不是画错了线，
而是"检查报告没说出真正的问题"：

### 盲区一：文字检查把几何缺陷报成了文字缺陷

第一版布局把机架排到 x=11300，而右墙门的门扇正好扫 x=11300~12500。
`tools.text_overlap` 报了：

```text
1. text_curve at (11600, 8714)
   1AE in 1AC [0] TAG=R4-B06 [style Standard]
   crosses C9 [A-DOOR-E-N] LINE
   text is inside block reference 1AC
   note: LINE crosses this text; the worst one runs 22% of the text height inside the box
```

**这份报告在技术上是对的，但它指向的修法是错的。** 按它说的去挪标签，
机架仍然站在门口——门打不开，而检查会变绿。

### 盲区二：全量 critique 在建筑图上产生 49 条领域错配噪声

同一张（已修好的）平面图跑 `drawing_critique()`：

```text
total: 49   by_focus: {pid_dangling_line: 1, pid_illegal_tag: 48}
```

- `pid_illegal_tag` ×48：把机架标签 `R1-A01` 当仪表位号，按 ISA-5.1 判为非法
- `pid_dangling_line` ×1：把门扇线 C9 判为"悬空"

而 `arch_room_unlabelled` / `arch_wall_gap` / `arch_opening_clash` 三项**全部为 0**。

## 根因

### 盲区一：检查器只建模了"文字 vs 曲线"

`tools/text_overlap` 的七项检查全部以**文字**为主体。它看到门弧穿过标签，
就报文字交叠；它没有"实体占据空间"这个概念，因此无法说"机架站在门口"。

### 盲区二：`has_pid_content` 只看属性名，不看位号形状

```python
ATTRIBUTE_TAGS = ("TAG", "TAGNO", ..., "INST_TAG", "INSTTAG")
...
tag_key = next((k for k in ATTRIBUTE_TAGS if k in attributes), None)
if keyword_kind or tag_key:
    node = _Node(source="heuristic", confidence=0.6, ...)
```

机架块的属性名恰好就是 `TAG`，于是 48 个机架全被启发式判成 P&ID `equipment`
（置信度 0.6），`has_pid_content()` 返回 True，七个 `pid_*` 检查全部开跑。

**关键证据**：同一个解析器对这两类标签的判定是清楚的——

| 标签 | `parse_tag` 结果 |
|---|---|
| `R1-A01` | `valid: False`（"not in [area-]LETTERS[-]loop[suffix] format"） |
| `RACK_6GPU` | `valid: False` |
| `P-101` | `valid: True`（pump） |
| `FT-100` | `valid: True`（Flow Transmitter） |

也就是说**证据本来就在手上**：一个真实 P&ID 位号能过语法，机架名不能过。
但 `has_pid_content` 没用这条证据。

## 处理

### 一、新增两项物理碰撞检查（`tools/text_overlap/physical.py`）

| kind | 含义 |
|---|---|
| `opening_blocked` | 某个实心轮廓落在门的扫掠四分之一圆内 |
| `solid_overlap` | 两个实心轮廓相交超过较小者面积的 15% |

门的识别**只从 ARC 读**，不猜块名：

```text
铰点 = 弧心  门扇长 = 弧半径  扫掠角 = 弧的 start/end
```

因为 `arch_opening` 画的就是 LINE（门扇）+ ARC（扫掠），读弧即可得到全部三个量，
即使门扇画成多段线也能识别。图层名含 `DOOR`/`KAPI` 才认；其他图层的弧不当门，
如实报 `not_checked` 而不是编一个扫掠区。

实测（同一张图，把 R4 的 12 台机架移回错误位置）：

```text
1. opening_blocked at (11600, 8700)
   block reference 24B [0]
   stands inside the swing of CA [A-DOOR-E-N] ARC
   note: block reference 24B (RACK_6GPU) stands inside the swing of door CA
         (hinge 12500,8700, leaf 1200); the doorway cannot open.
         Move 24B clear of the swept quarter disc (x 11300..12500, y 7500..8700).
```

修复后的图：0 条。

### 二、把 `has_pid_content` 收紧到"位号必须过 ISA-5.1 语法"

```python
def has_pid_content(graph: dict) -> bool:
    for node in graph["nodes"]:
        if not _recognised(node):
            continue
        if node.get("source") != "heuristic":
            return True          # catalogue / XDATA: 图自己作证
        if _tag_shaped(node):
            return True          # 有真实位号支撑这个猜测
    return False
```

catalogue 与 XDATA 是图自己声明的内容，直接算数；**启发式节点必须有一个能过
语法的位号**才算。0.6 置信度的猜测永远只是猜测——这正是 spec §9.2 对它的定性。

## 三个必须知道的阈值细节

这三条都踩过，并且都写成了回归测试：

| 细节 | 踩法 | 后果 |
|---|---|---|
| **相切不算阻挡** | 机架 R4-B05 东边缘正好在 x=11300，门扫掠也从 11300 开始——角点距离恰等于半径 | 报了 2 台而不是 1 台，会让人去挪一台本来就合规的机架 |
| **相邻不算重叠** | 一排 6 台机架彼此共边，朴素的 `>=` 判定 | 48 台机架报 47 条"碰撞" |
| **报块引用 handle，不报块内成员 handle** | 同一块定义的 48 台机架，块内成员 handle 全是 `110` | 报 `handle=110` 无法定位是哪一台；必须报外层 INSERT 的 handle |

角度的坑：门扇从 180°（向西开）扫到 270°（贴墙）覆盖的是**左下**象限。
写成 90°–180° 会覆盖空的左上象限，检查"完全不触发"，看起来像检查坏了。
实测时按真实门（`W_RIGHT` 上的 D3：铰点 12500,2700，扫 180..270）核对才定位到。

## 预防

1. **文字检查通过 ≠ 图纸没问题**。它只回答"标签能不能读"。几何对不对（机架站
   在门口、家具穿过墙）必须另有检查——本次已加入 `opening_blocked` 与
   `solid_overlap`。
2. **`text_curve` 报"标签被线穿过"时，先问那条线是什么**。如果线是门弧、家具
   轮廓、其他实体的边，真正要改的是**那个实体的位置**，不是标签。
3. **全量 `drawing_critique()` 会跨领域评分**。建筑图上出现成片 `pid_*` 时，先看
   `by_focus`：`pid_illegal_tag` 连着报几十条，几乎一定是领域错配。用
   `focus=["arch_*"]` 收窄再判断。
4. **位号形状是区分领域的可靠证据**，属性名叫 `TAG` 不是。真实位号过 ISA-5.1，
   机架名不过。
5. **检查器必须有两个方向的反例**：既要有"该报的报了"，也要有"不该报的没报"。
   本次两个阈值（相切、相邻）都是先误报、加了反例测试才定下来的。

## 更新说明

- 2026-11-19 首次记录。发现于自测新增的 `saving-formats` 技能流程时，画机房平面图。
- 新增 `tools/text_overlap/physical.py`（两项检查 + 三个阈值），
  `overlap.py` 的 `detect()` 接入，`__main__.py` 摘要与明细适配非文本类发现。
- `engineering/pid/critique.py`：`has_pid_content` 收紧，新增 `_tag_shaped()`。
- 测试：`tools/text_overlap/tests_overlap.py` 37 → **43**（6 个新测试，含两个反例），
  `tests/test_pid_critique.py` 25 → **26**。两套全部通过。
- 技能 `autocad-text-overlap-check` 从"七项检查"更新为"九项"，新增
  "Why physical checks exist" 一节。