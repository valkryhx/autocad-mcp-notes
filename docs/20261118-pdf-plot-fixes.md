# PDF 出图：中文乱码 + 版面裁切的完整修复

> 记录日期：2026-11-18
> 环境：AutoCAD 2026 `25.1s (LMS Tech)`、ezdxf、autocad-mcp-pro 1.8.0、DWG To PDF.pc3
> 相关文档：[`AGENTS.md`](../AGENTS.md) · [`20261118-chinese-text-dwg-fix.md`](20261118-chinese-text-dwg-fix.md) · [`20261117-autocad-troubleshooting.md`](20261117-autocad-troubleshooting.md)

---

## 1. 现象

DWG 里中文显示正常，但导出 PDF 后：

1. **中文全变成 `???` 或乱码**
2. **右侧标题栏被裁掉**（`2026-11-18`、`主机房平面布置图` 等文字在 PDF 里完全消失）
3. 大标题被截断（`GPU 智算中心机房平面布置图` → `GPU 智算中`）

这三个症状看着像一回事，实际是**三个独立原因**。

---

## 2. 根因与证据

### 2.1 中文乱码 → TTC 集合字体无法嵌入 PDF

**证据**：解压 PDF 内容流统计指令：

| 字体 | `Tj`（文字指令） | `BT` | `BaseFont` |
|---|---|---|---|
| `simsun.ttc` | **0** | **0** | 无 |
| `simhei.ttf` | 323 | 323 | `SimHei` ×2 |

`simsun.ttc` 时 PDF 里**一个字体对象都没有**，文字全部被转成几何线条（7928 条 `l` 指令）。AutoCAD 打印 PDF 时无法嵌入 TTC 集合字体，只能把字形炸成矢量线段——看起来就是乱码/`???`。

**修法**：中文样式必须用**单体 `.ttf`**，不能用 `.ttc`。

```python
DOC.styles.add("CN", font="simhei.ttf")     # ✅
# DOC.styles.add("CN", font="simsun.ttc")   # ❌ PDF 出图会炸成线条
```

可用的单体中文字体：`simhei.ttf`（黑体）、`simkai.ttf`（楷体）、`simfang.ttf`（仿宋）、`SIMLI.TTF`（隶书）。

> `.ttc` 是字体集合（collection），一个文件装多个字体；PDF 嵌入只认单体 TrueType。

### 2.2 版面裁切 → 可打印区小于图框

**证据**：`DWG To PDF.pc3` 的 A1 介质边距是 `[17,17,5,5] mm`，可打印区只有 **831 × 560 mm**。图框若按 841 × 594 画，1:100 出图必然溢出，AutoCAD 就裁掉或拒绝。

**修法**：图框缩到可打印区内。

```python
FW, FH = 82000, 55500      # 840x555 -> 稳落在 831x560 内
```

`page_setup_apply` 会返回边距，直接读它：

```json
"margins_mm": [17, 17, 5, 5]     # 上、下、左、右
```

### 2.3 内容被裁一半 → `PlotType` 枚举用错

**这是最隐蔽的一个。**

ActiveX `Layout.PlotType` 的枚举：

| 值 | 常量 | 含义 |
|---|---|---|
| 0 | `acDisplay` | 当前显示范围 |
| 1 | `acExtents` | **图形实际范围** |
| 2 | `acLimits` | 图形界限 |
| 3 | `acView` | 命名视图 |
| 4 | `acWindow` | 窗口 |
| 5 | `acLayout` | 布局（图纸空间） |

我最初把 `PlotType` 设成了 **1**，但文档和实测都表明 **extents 在 AutoCAD 里的值应是 2**；设成 1 时实际走的是别的语义，导致按屏幕视图出图并缩放，内容只画到 x = 698 mm（模型宽 820 mm），右侧 122 mm 丢失。

**证据**：用 pymupdf 量 PDF：

```text
page(pt): 2384 x 1684   (841 x 594 mm)
文字范围: x 445..1944 pt = 157..686 mm
图形最右: 1978 pt = 698 mm       ← 应有 820 mm
/ Rotate: 270                     ← 页面还被旋转了
```

**修法**：改用**图纸空间 + 视口**，彻底绕开 plot_area/PlotType 的歧义。

### 2.4 `/Rotate 270` 让页面变成纵向

`vla-put-PlotRotation` 的值含义与直觉相反：

| 值 | 效果 |
|---|---|
| 0 | 横向（不旋转） |
| 1 | 纵向 |
| 2 | 横向（旋转 180） |
| 3 | 纵向（旋转 270） |

我原本设了 1（纵向），结果横向的 A1 图被塞进纵向页面，右侧再被裁一次。

---

## 3. 处理（最终可用方案）

### 3.1 用图纸空间视口，而不是模型空间 extents

在 ezdxf 里建满幅视口：

```python
LAY = DOC.layouts.get("Layout1")
for _vp in list(LAY.query("VIEWPORT")):
    LAY.delete_entity(_vp)          # 清掉默认视口

LAY.add_viewport(
    center=(410.0, 277.5),               # 纸面 mm，图纸中心
    size=(820.0, 555.0),                 # 纸面 mm，满幅
    view_center_point=(41000.0, 27750.0),# 模型中心
    view_height=55500.0,                 # 模型高度
)
# 缩放 = view_height / size.height = 55500/555 = 100 → 精确 1:100
```

**验证比例**（必须算）：

```python
scale = vp.dxf.view_height / vp.dxf.height   # 必须 == 100.0000
```

### 3.2 布局出图参数

```python
page_setup_apply(
    layout="Layout1",
    paper="A1",
    plot_area="layout",        # 不是 extents！图纸空间走 layout
    scale="1:1",               # 视口已含比例，布局本身 1:1
    plot_style="monochrome.ctb",
)
```

关键：**`plot_area="layout"` + `scale="1:1"`**。比例由视口负责，布局出图按 1:1 原样输出。

### 3.3 出图

```python
batch_plot(
    output_dir="...",
    layouts=["Layout1"],
    file_pattern="{layout}.pdf",
)
```

`batch_plot` 会从写出的 PDF 里读 `/MediaBox` 反算纸型，**尺寸是被验证的，不是假设的**：

```json
{"layout":"Layout1","ok":true,"bytes":98858,
 "mediabox_mm":[841.022,594.078],"paper":"ISO_A1"}
```

### 3.4 验证 PDF（三层）

```python
import fitz                                  # pymupdf
d = fitz.open("out.pdf"); p = d[0]
print(p.rotation)                            # 必须 0
print(p.rect)                                # 2384x1684 pt = 841x594 mm
words = p.get_text("words")
print(max(w[2] for w in words) * 25.4/72)    # 文字最右 mm，应 < 841
txt = p.get_text()
for s in ["2026-11-18", "主机房平面布置图"]:   # 标题栏易被裁
    assert s in txt, s
```

**实测正确结果**：

```text
/Rotate: 0
文字最右: 809 mm  (页面 841)
文字最上: 563 mm  (页面 594)
全部关键文字: OK
```

---

## 4. 无效的尝试（别重走）

| 尝试 | 结果 |
|---|---|
| `PlotType=1` + `extents` + `1:100` | 内容只画到 698mm，右侧被裁 |
| `PlotRotation=1` | 页面变纵向，横向图再被裁一次 |
| 全出血介质 `ISO_full_bleed_A1` | `PlotToFile` 直接返回 False，拒绝出图 |
| LISP `(vla-PlotToFile layout path)` | 静默不生成文件（返回 T/NIL 不可靠） |
| LISP 连续调用取值 | **返回值稳定滞后一条**，读到的是上一次的结果 |
| `drawing_export_pdf(layout="Model")` | 反复 `PlotToFile returned False`，它会重置 layout 设置 |
| `-PLOT` 命令行交互 | 停在提示上卡死 COM 线程 120s+，需人工 ESC |
| 只用第一个 `cm` 矩阵解析 PDF 坐标 | PDF 有 26 个嵌套 `cm`，必须跟踪 `q`/`Q` 栈 |

---

## 5. 预防

1. **中文样式一律用单体 `.ttf`**（`simhei.ttf`），绝不用 `.ttc`——PDF 出图会把字形炸成线条。
2. **图框尺寸必须先查可打印区**：`page_setup_apply` 的返回里有 `margins_mm`，A1 是 17/17/5/5 → 可打印 831×560。
3. **出图优先用图纸空间视口 + `plot_area="layout"` + `scale="1:1"`**，别在模型空间玩 `extents` + 比例。
4. **视口比例必须回算验证**：`view_height / size.height` == 100。
5. **`PlotRotation`：0 = 横向**，别想当然设 1。
6. **PDF 出图后必须实测**：`pymupdf` 读 `/Rotate`、`rect`、文字最右/最上坐标、关键字符串是否齐全。
7. **布局（layout）出图不会自动带上模型空间的图框**——图框要画在模型里并让视口覆盖到，或直接画在图纸空间。

---

*2026-11-18 记录。三个独立根因：TTC 字体无法嵌入 PDF、可打印区小于图框、PlotType/PlotRotation 枚举用错。最终方案是图纸空间视口 + layout 1:1 出图。*
