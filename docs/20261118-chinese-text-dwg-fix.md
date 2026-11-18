# 中文在 DWG 中乱码的完整修复：DXF 代码页 + 文字样式

> 记录日期：2026-11-18
> 环境：AutoCAD 2026 `25.1s (LMS Tech)`、ezdxf、autocad-mcp-pro 1.8.0
> 相关文档：[`AGENTS.md`](../AGENTS.md) · [`20261117-chinese-text.md`](20261117-chinese-text.md) · [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md)

---

## 1. 现象

用 ezdxf 生成含中文的平面图，经 AutoCAD 打开后：

- **LISP 读回的文本完全正确**（`<GPU 智算中心机房平面布置图>`）
- **码点完全正确**（`智`=U+667A、`算`=U+7B97）
- **文字样式也是对的**（312 个 MTEXT 全用 `CN`）
- **但在 AutoCAD 里看仍然是乱码**

「数据对、码点对、样式对、显示却错」——这个组合是最难查的一类，因为所有常规验证手段都显示通过。

## 2. 根因

**两个独立原因叠加，必须同时修。**

### 2.1 DXF 代码页声明错误

ezdxf 生成的 R2018 DXF 头里：

```text
$DWGCODEPAGE = ANSI_1252      ← 西欧代码页
$ACADVER     = AC1032          ← 即 R2018
```

但实测文件字节是 **UTF-8**：

```text
'GPU \xe6\x99\xba\xe7\xae\x97\xe6\x9c\xba\xe6\x88\xbf'   # 智算机房 的 UTF-8 字节
```

ezdxf 文档写明：

> DXF R12, R2000, R2004 - ASCII encoding
> **DXF R2007 and newer - UTF-8 encoding**
> in ASCII mode, unknown characters will be escaped as `\U+nnnn`

即 R2007+ 本来就是 UTF-8，`$DWGCODEPAGE` 在这个版本已经不重要（AutoCAD 按 UTF-8 读）。**所以这条不是乱码主因，但声明与实际不符值得修正。**

### 2.2 文字样式字体（真正的主因）

`Standard` 样式的字体是 `txt.shx`，**这个 SHX 字体没有 CJK 字形**。AutoCAD 遇到无字形的字符时**静默跳过，不报错**，屏幕上就是空白或乱码。

这就是 [`20261117-chinese-text.md`](20261117-chinese-text.md) 已记录的根因。本次的修法是：**建 TrueType 中文样式，并把所有文字显式指向它**。

## 3. 处理（实测有效）

### 3.1 建中文 TrueType 样式

```python
DOC.styles.add("CN", font="simsun.ttc")
```

或在 AutoCAD 内：

```text
textstyle_create(name="CN", font="simsun.ttc", set_current=True)
```

本机可用中文字体：

| 字体文件 | 名称 |
|---|---|
| `simsun.ttc` | 宋体 |
| `simhei.ttf` | 黑体 |
| `msyh.ttc` | 微软雅黑 |
| `simkai.ttf` | 楷体 |
| `simfang.ttf` | 仿宋 |

### 3.2 每个文字实体显式指定样式（关键）

**不能依赖「设为当前样式」**。生成 DXF 时要逐个实体写死 `style`：

```python
mt = msp.add_mtext(s, dxfattribs={
    "style": "CN",              # ← 必须显式写，不能省
    "char_height": h,
    "layer": layer,
})
mt.set_location((x, y), attachment_point=5)
```

### 3.3 已有文字批量改样式（COM）

```python
for e in doc.ModelSpace:
    if e.ObjectName in ("AcDbText", "AcDbMText"):
        e.StyleName = "CN"
doc.Regen(1)
```

LISP 版：

```lisp
(progn
  (setq ss (ssget "_X" '((0 . "TEXT,MTEXT"))))
  (setq i 0)
  (repeat (sslength ss)
    (vla-put-StyleName (vlax-ename->vla-object (ssname ss i)) "CN")
    (setq i (1+ i)))
  (princ))
```

### 3.4 直接把 `Standard` 改成中文字体（一劳永逸）

如果不想改所有实体，可把默认样式本身换掉：

```text
_-STYLE  Standard  simsun.ttc  0  1  0  N  N
```

这样所有走 `Standard` 的文字（包括 **TABLE 单元格**）都自动有中文字形——也顺便解决了 [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md) 里表格单元格空白的问题。

## 4. 验证方法（三层，缺一不可）

乱码问题最容易「以为好了其实没好」，必须三层都验：

| 层 | 方法 | 能证明什么 |
|---|---|---|
| **数据层** | LISP `(cdr (assoc 1 (entget e)))` 读回 | 字符串在内存里正确 |
| **码点层** | `(itoa (ascii (substr s i 1)))` 或 ezdxf `ord(c)` | 没有编码转换错误 |
| **显示层** | **真实窗口截图** | 屏幕上真的看得见 |

### 验证码点（LISP）

```lisp
(progn
  (setq e (entget (ssname (ssget "_X" '((0 . "MTEXT"))) 11)))
  (setq s (cdr (assoc 1 e)))
  (setq out "")
  (setq i 1)
  (repeat (min 14 (strlen s))
    (setq out (strcat out (itoa (ascii (substr s i 1))) ","))
    (setq i (1+ i)))
  out)
;; 正确结果示例：22270,32,32,21517,  → 0x56FE 0x0020 0x0020 0x540D = 「图  名」
```

### ⚠️ 显示层必须用真实窗口截图

**这是本次踩的最大的坑。**

| 工具 | 走的路径 | 是否可信 |
|---|---|---|
| `view_screenshot(region=...)` | `Document.Export` **快照渲染器** | ❌ **会丢弃部分文字**，表格单元格尤其严重 |
| `view_zoom_and_screenshot()` | 真实 AutoCAD **窗口捕获** | ✅ 可信 |
| ezdxf + matplotlib 渲染 | ezdxf 自己的渲染器 | ❌ 缺中文字体就是方块 |

我此前用快照渲染截图判断「中文正常」，实际是**误判**；用户打开 DWG 看到的是乱码。快照渲染器显示空白 **不代表** 数据缺失，显示正常也 **不代表** 真的正常。

**结论：判断中文显示，只认真实窗口截图。**

## 5. 预防

1. **生成含中文的 DXF 时，每个文字实体显式写 `style="CN"`**，不依赖当前样式。
2. **文字样式必须用 TrueType**（`simsun.ttc` 等），`txt.shx` 无 CJK 字形且静默失败。
3. **验证中文必须三层全过**：数据、码点、**真实窗口截图**。快照渲染器不作为依据。
4. **控制台乱码不算数**：Windows 终端 GBK/UTF-8 编码会渲染成乱码，用 `ord()` 比对码点。
5. **`m²`/`Ø`/`±`/`°` 同一根因**：`txt.shx` 也没有这些字形，同样要 TrueType 样式，且**直接写 Unicode，不用 `%%178`/`%%d`**。
6. **TABLE 单元格有独立样式**，不跟随 `AcDbText.StyleName`；改 `Standard` 字体是覆盖它的最简办法。
7. DXF R2007+ 用 UTF-8 编码，`$DWGCODEPAGE` 声明与实际不符一般不影响 AutoCAD 读取，但**跨软件交换时**（老的 DXF 工具）值得修正声明。

## 6. 相关

- 原始中文显示问题：[`20261117-chinese-text.md`](20261117-chinese-text.md)
- TABLE 单元格样式隔离：[`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md)
- 表格居中与行高：[`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md)

---

*2026-11-18 记录。核心教训：快照渲染器（`view_screenshot` 的 region 模式）会丢弃文字，判断中文显示只认真实窗口截图；文字样式必须逐实体显式指定 TrueType 字体。*
