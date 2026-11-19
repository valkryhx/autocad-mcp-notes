# 文字检查器把组码 10/11 读反了：DXF 报 0 条、DWG 报 1 条

> 记录日期：2026-11-19
> 环境：AutoCAD 2026 (`25.1s`)、ezdxf 1.4.4、`tools/text_overlap`
> 相关文档：[`20261118-text-overlap-check.md`](20261118-text-overlap-check.md)

## 现象

同一张图（`draw_test/20261119.dxf`，2026-11-19 的机房平面图）交给检查器，两个格式结论不同：

```text
draw_test/20261119.dxf  [Model]
  measured 159 text entities ... 919 curves
  0 finding(s): all clean

draw_test/20261119.dwg  [Model]
  measured 159 text entities ... 919 curves
  1 finding(s): 1 text-on-geometry

  1. text_curve at (5722, 17530)
     4BF [A-TEXT] 4 机房 × 2 排 × 10 柜 × 6 GPU = 480 块 GPU ... [style CN]
     crosses 97 [A-WALL] LWPOLYLINE
     note: LWPOLYLINE crosses this text; the worst one runs 3676% of the text height inside the box
```

DWG 是从同一份 DXF 用 `SaveAs` 存的。文字框：

| 文件 | 文字框 Y | A-WALL #97 顶边 Y | 结论 |
|---|---|---|---|
| DXF | 17502..17697 | 17460 | 不相交 |
| DWG（经 AutoCAD 转出的副本） | 17432..17627 | 17460 | 相交 27 |

两者相差 **70 单位 = 半个字高**（`height = 140`）。

顺带一个更早看到的假象：AutoCAD 里读这条文字的 `InsertionPoint` 是
`(2150, 17530)`，而 DXF 里写的是 `(2150, 17600)`，`TextAlignmentPoint` 是
`(2150, 17600)` —— 插入点被改了 70，对齐点没动。

## 根因

`tools/text_overlap/textbox.py` 的 `_measure_text()` 把两个分支写反了。

DXF 规范对 TEXT 的对齐语义：

- **组码 72 = 0 且 73 = 0**：文字以**组码 10**（`insert`，左基线点）定位，组码 11 不用
- **72 或 73 任一非零**：文字以**组码 11**（`align_point`）定位，**组码 10 被忽略**

原来的代码正好相反 —— 非零分支读 `insert`：

```python
if halign == 0 and valign == 0:
    alignment_point = entity.dxf.get("align_point", None)   # ← 错：这个分支该读 insert
    origin = Vec3(alignment_point) if alignment_point is not None \
             else Vec3(entity.dxf.insert)
else:
    origin = Vec3(entity.dxf.insert)                         # ← 错：这个分支该读 align_point
```

这张图里所有文字都是 `set_placement(..., MIDDLE_LEFT)` 写的，即
`halign=0, valign=2`。生成的 DXF 里组码 10 和组码 11 恰好相同，所以**在 DXF 上看
不出错**。但 AutoCAD 存 DWG 时会按 `valign=2` 重算插入点（组码 10 下移半字高），
两者不再相同，检查器读错分支的后果才显形。

**这就是"一层夹具测不出来"的典型**：只测 DXF，永远发现不了。

定位过程（没有靠猜）：

1. 先排除对齐态本身：造 `align_probe.dxf`，四种对齐态写到同一位置，AutoCAD 实测框
   与检查器算的框相差 1–6 单位（字形度量的正常误差），**证明对齐枚举没问题**
2. 再让组码 10 与组码 11 **故意不同**：造 `align_probe2.dxf`，
   `insert=(1000,1000)`、`align_point=(3000,1500)`。修复后四个对齐态全部落在规范
   指定的锚点上；修复前 `h1v2 / h0v2 / h2v2` 都落在 (1000,1000)，与规范相反

## 处理

改 `tools/text_overlap/textbox.py`：

```python
halign = int(_attr(entity, "halign", 0) or 0)
valign = int(_attr(entity, "valign", 0) or 0)
if halign == 0 and valign == 0:
    origin = Vec3(entity.dxf.insert)          # 组码 10
    left = 0.0
    baseline = 0.0
else:
    alignment_point = entity.dxf.get("align_point", None)
    # 有对齐码却没有组码 11 的文件：退回 insert，总比丢掉这条文字强
    origin = (Vec3(alignment_point) if alignment_point is not None
              else Vec3(entity.dxf.insert))
    left = {...}.get(halign, 0.0)
    baseline = {...}.get(valign, 0.0)
```

新增回归测试 `test_text_anchor_follows_alignment_codes()`，7 条断言：

- `halign=0 valign=0` 用组码 10
- `h0v2 / h1v2 / h2v2 / h1v0` 四种用组码 11（**判据是锚点必须靠近 3000 而不是 1000**）
- `valign=2` 时框中心落在对齐点上
- 缺组码 11 时退回插入点，不丢文字

测试的必要性：夹具里组码 10 与 11 **必须不同**。两个点相同的话，改前改后算术结果一样，
测试对 bug 完全免疫 —— 和之前"嵌套块 `via='None'` 需要递归形状夹具"是同一类教训。

修完后：

```text
DXF  → 0 finding(s)
DWG  → 0 finding(s)      ← 之前是 1 条假报警
回归 37 个测试函数全过
负对照（植入压字/压线/隐藏层/重复 4 类）→ 全部检出，无漏报
```

## 预防

1. **文字实测必须两个格式都跑一遍**。DXF 只是"我要写的"，DWG 才是"AutoCAD 认的"；
   两者不一致时，不管理由是什么，都说明有一方的读法是错的。
2. **写测试夹具要让被测分支的两种取值不同**。这个 bug 只要组码 10 == 组码 11 就测不出来；
   需要递归就造两层，需要两个锚点就造两个不同的点。
3. `set_placement()` 写出来的 TEXT 一律是"非零对齐码"，所以**项目里几乎所有文字都走
   这个分支** —— 这个 bug 的影响面覆盖全部图纸，不只是这一张。
4. 顺带记：`Layout.Measurement` 在 pywin32 的 dynamic dispatch 下会报
   「对象未打开进行写入」，读不了；要拿标注值，走 `*D` 块里的 MTEXT 文字，
   或者直接在 DXF 上读 `DIMENSION.get_measurement()`。

## 更新说明

- 2026-11-19 首次记录。修复 `textbox.py` 对齐分支，补 7 条断言。