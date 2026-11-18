# 中文与特殊符号（`m²`、`Ø`、`±`）显示：能存不能看，靠文字样式解决

> 记录日期：2026-11-17
> 环境：AutoCAD 2026 中文版（`25.1s (LMS Tech)`，`D:\autocad_26\AutoCAD 2026\`）、`autocad-mcp-pro==1.8.0`（本地 venv 版）、Windows
> 发现场景：绘制通信机房平面图，需要中文图名、房名，以及 `m²` 面积标注

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 第 10 节排错、第 11 节记录制度
> - [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) — 引擎选型
> - [`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md) — 表格单元格居中
>
> **一句话结论**：中文、`²`、`Ø`、`±` 存得进去、读得回来，但默认 `Standard` 样式的 `txt.shx` 没有这些字形，AutoCAD 静默跳过不画。换成 `simsun.ttc` 等 TrueType 字体即可。

---

## 1. 现象

把中文写入图纸后，**数据完全正确，但屏幕上看不见**。

**现象 A — 读回比对通过**

用 `entity_create_text` 写入 `"通信机房平面图"`，再用 COM 读回：

```text
MATCH: True
got  len: 7 codepoints: ['0x901a','0x4fe1','0x673a','0x623f','0x5e73','0x9762','0x56fe']
want len: 7 codepoints: ['0x901a','0x4fe1','0x673a','0x623f','0x5e73','0x9762','0x56fe']
```

字符一个不差，`TextString` 属性完整。**存储层没有任何问题。**

**现象 B — 屏幕上什么都没有**

同一条文字放大到视图里，截图上看不到任何字形。实体存在、包围盒存在（`bbox: [30000,30000] [32750,30500]`），画面上是空白。

**现象 C — 控制台显示乱码，但不是数据问题**

PowerShell / Git Bash 打印 `ent.TextString` 显示 `'ͨŻƽͼ'`。这是**终端编码**（GBK/UTF-8 混淆）的问题，不是 AutoCAD 数据的问题——同一段文字用 `got == expected` 比对是 `True`。

---

## 2. 根因

图纸默认文字样式是 `Standard`，它的字体是 **`txt.shx`** —— 一个纯 ASCII/西文的 SHX 字形文件，**没有任何 CJK 字形**。

```text
=== 文字样式 ===
  Standard:   font='txt'   bigfont=''
  Annotative: font='txt'   bigfont=''
$FONTALT = simplex.shx      ← 找不到字形时的替补，同样没有中文
```

AutoCAD 遇到字体里没有的字符，**不会报错、不会提示**，直接不画。所以：

- 数据是 `0x901a` 等正确码点 → 存得住、读得回
- 字体里没有对应字形 → 画不出来
- 没有报错 → 看起来像"中文不支持"

**结论：不是不支持中文，是默认字体没有中文字形。**

---

## 3. 处理

### 3.1 建一个中文字体样式（MCP 方式，推荐）

```text
textstyle_create(name="CN", font="simsun.ttc")
```

返回：

```json
{"ok": true, "name": "CN", "font": "simsun.ttc", "font_resolved": true, "current": false}
```

`font_resolved: true` 表示该字体在本机真实存在、AutoCAD 接受它。

**本机可用的中文字体**（Windows 自带）：

| 字体文件 | 字体 | 说明 |
|---|---|---|
| `simsun.ttc` | 宋体 | 最通用，工程图常用 |
| `simhei.ttf` | 黑体 | 笔画粗，远看清晰 |
| `msyh.ttc` | 微软雅黑 | 现代感强 |
| `simkai.ttf` | 楷体 | 手写感 |
| `simfang.ttf` | 仿宋 | 公文常用 |

### 3.2 把实体指定到该样式

MCP 的 `entity_create_text` **不支持指定样式**，只能用当前样式。所以两条路：

**做法 A：先设当前样式（新文字自动用它）**

```text
textstyle_create(name="CN", font="simsun.ttc", set_current=True)
# 之后 entity_create_text 创建的文字都是中文可见的
```

**做法 B：事后改已有实体的 StyleName（COM）**

```python
# 必须用 COM 后端（ezdxf 无头下实体样式名同样可写，但需在保存前）
for ent in doc.ModelSpace:
    if ent.ObjectName == "AcDbText" and ent.Handle == "8C9":
        ent.StyleName = "CN"
doc.Regen(1)
```

`StyleName` 是可写属性，改完 `Regen` 即生效。

### 3.3 完整可复现流程（本次实测）

```powershell
# ① 建中文样式并设为当前
#    textstyle_create(name="CN", font="simsun.ttc", set_current=True)

# ② 写中文
#    entity_create_text(text="通信机房平面图", x=20200, y=10600, height=400, layer="ANNO")

# ③ 若是已有实体，用 COM 改样式（8C9 = 上一步返回的 handle）
python -c "
import win32com.client
app = win32com.client.GetActiveObject('AutoCAD.Application')
doc = app.ActiveDocument
for e in doc.ModelSpace:
    if e.ObjectName == 'AcDbText' and e.Handle == '8C9':
        e.StyleName = 'CN'
doc.Regen(1)
"
```

效果：中文正常显示（本次已确认「通信机房平面图」7 个字清晰可见）。

### 3.4 附：上标／特殊符号（`m²` 显示成 `m`）是同一个根因

**这不是中文特有的问题，是同一个「字体缺字形」的问题。**

面积标注 `54.48 m²` 里的 `²` 是 **U+00B2**（SUPERSCRIPT TWO）。默认 `Standard` 的 `txt.shx` 没有这个字形，AutoCAD 静默跳过，于是屏幕上只看到 `m`：

| 层面 | 结果 |
|---|---|
| 存储 | ✅ `entity_list` 读回 `"54.48 m²"`，8 个字符，`²` 完好 |
| 显示 | ❌ 默认样式下 `²` 不画，肉眼看到 `m` |

**解决：把带符号的文字指定到有完整 Unicode 字形的字体样式**（与中文完全相同的做法）。

```python
for ent in doc.ModelSpace:
    if ent.ObjectName == "AcDbText" and ent.Handle in ("110", "113", "116", "8DC"):
        ent.StyleName = "CN"        # CN = simsun.ttc
doc.Regen(1)
```

改完 `m²` 正常显示（本次已确认）。

**图纸里会出现同类问题的字符，还有：**

| 字符 | 码点 | 用途 | 默认 `txt.shx` |
|---|---|---|---|
| `²` `³` | U+00B2 / U+00B3 | 面积、体积 `m²` `m³` | ❌ 无 |
| `Ø` `±` `°` | U+00D8 / U+00B1 / U+00B0 | 直径、公差、角度 | ❌ 无（`%%c` `%%p` `%%d` 是 SHX 专用转义，另说） |
| `㎡` | U+33A1 | 平方米单字符 | ❌ 无 |
| `±` `≤` `≥` `≈` | 符号区 | 公差、比较 | ❌ 无 |
| 中文 | U+4E00+ | 中文标注 | ❌ 无 |

**判断方法一致：读回码点确认数据，再看图上有没有字形。数据对而看不见 = 字体问题。**

> **SHX 控制码是另一套。** `%%d`（度）、`%%p`（±）、`%%c`（Ø）、`%%178`（²）是 AutoCAD 老式 SHX 转义序列，只对 SHX 字体有效；用在 TrueType（如 `simsun.ttc`）上会被当普通字符画出 `%%d` 字样。**用 TrueType 样式时请直接写 Unicode 字符 `°±Ø²`，不要用 `%%` 转义。**

### 3.5 无效尝试

| 尝试 | 结果 |
|---|---|
| 直接 `entity_create_text` 写中文 | 存得住、读得回，**但看不见**（默认 `txt.shx` 无字形） |
| 用 `MText` 替代 `Text` | 同样问题——取决于样式字体，不是实体类型 |
| 靠 `$FONTALT = simplex.shx` 替补 | 无效，`simplex.shx` 也没有 CJK 字形 |
| 用控制台打印中文判断 | 不可靠：终端编码把正确数据渲染成乱码，会误判为"存坏了" |
| 用 `system_run_lisp` 批量改样式 | 被安全策略拒绝：`vla-get-activedocument`、`vla-setcellalignment` 等在 deny 列表，需 `DANGEROUS_COMMANDS_ENABLED=true` |

---

## 4. 预防

1. **画中文图之前，先建中文文字样式并设为当前。** 顺序错了就是"写完看不见"，还得回头补。
2. **判断中文是否成功，比对码点，别看控制台。** `got == expected` 才是证据；终端乱码是环境噪声。
3. **`font_resolved: true` 是字体可用的唯一凭据。** 无头引擎对不存在的字体照样写入并报 `font_resolved: false`（AutoCAD 打开时替补）；COM 后端直接拒绝。
4. **`lang` 参数不是文字语言。** `arch_*` 工具的 `lang` 只接受 `en`/`tr`（土耳其语，用于词表与小数逗号），**不影响能否写中文**。
5. **中文字高要比西文留更大余量。** 同样 `height` 下汉字视觉更满，`:50` 图上 400 单位（8 mm 纸面）印刷清晰。
6. **确认图纸已存盘。** 样式与文字都要 `drawing_export_dwg` 之后才算交付。
7. **面积、直径、角度等带符号的文字，一并指定到 TrueType 样式。** `m²`、`Ø`、`±`、`°` 和中文是同一个根因，别只改中文那一行。房间表 / 门窗表里的 `m²` 也要查（表格单元格有各自样式）。
8. **TrueType 样式下写 Unicode 字符，不写 `%%` 转义。** `%%d`/`%%p`/`%%c` 只对 SHX 字体有效，在 `simsun.ttc` 上会被当普通文字画出来。
9. **刷新瞬间的占位符不是数据损坏。** `Regen` 或切换样式时 CJK / 上标可能瞬时显示成 `?` 或空白，刷新完成后恢复；删文字前先 `Regen` 再确认。

---

## 5. 一条命令速查

```python
# 建样式 + 写中文/符号 + 指定样式（COM）
import win32com.client
app = win32com.client.GetActiveObject("AutoCAD.Application")
doc = app.ActiveDocument

# 建样式（若不存在）
names = [s.Name for s in doc.TextStyles]
if "CN" not in names:
    st = doc.TextStyles.Add("CN")
    st.FontFile = "simsun.ttc"      # 宋体；simhei.ttf 黑体、msyh.ttc 雅黑亦可

import pythoncom, array
from win32com.client import VARIANT

def add(text, x, y, h=300.0, style="CN"):
    pt = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                 array.array("d", [float(x), float(y), 0.0]))
    t = doc.ModelSpace.AddText(text, pt, float(h))
    t.StyleName = style
    return t.Handle

# 中文 + 上标一起写（注意：直接写 Unicode ²，不要写 %%178）
add("通信机房平面图", 20200, 10600, 400)
add("54.48 m²", 3600, 3200, 125)

doc.Regen(1)
print("ok")
```

```python
# 一次性把已有文字全部切到 Unicode 字体（中文、m²、Ø、± 一并解决）
for ent in doc.ModelSpace:
    if ent.ObjectName == "AcDbText":
        try:
            ent.StyleName = "CN"
        except Exception:
            pass
doc.Regen(1)
```

> **表格里的 `m²` 也要处理。** TABLE 实体有自己的单元格样式，不走 `AcDbText` 的 `StyleName`；用 `SetCellAlignment` 那套 API 找不到样式入口时，可把整张表的行列文字重新 `SetText`，或在表格使用的文字样式上直接改字体。

---

*首次记录于 2026-11-17，来自通信机房平面图的中文标题实测。「能存不能看」是最容易误判为"不支持中文"的一类问题。*