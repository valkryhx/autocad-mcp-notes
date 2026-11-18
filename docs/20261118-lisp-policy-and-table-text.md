# LISP 写层默认被禁 / 表格单元格中文空白

> 记录日期：2026-11-18
> 环境：AutoCAD 2026 `25.1s (LMS Tech)`、autocad-mcp-pro 1.8.0、Windows
> 相关文档：[`AGENTS.md`](../AGENTS.md) · [`20261117-autocad-troubleshooting.md`](20261117-autocad-troubleshooting.md) · [`20261117-chinese-text.md`](20261117-chinese-text.md) · [`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md)

---

## 1. 现象

### 1.1 LISP 写操作被拒

用 `system_run_lisp` 改文字高度、设表格单元格，全部被前置策略拒绝：

```text
LISP expression rejected: contains a restricted function.
'vla-gettextstring' at line 1, column 101 needs the write tier (1.8.1),
so the expression went to the 1.7 denylist, which refuses
vla-get-columns, vla-get-rows, vla-gettextstring, vla-object, vlax-ename-.
The read tier (LISP_POLICY=read) runs reads such as vla-get-*, getvar and
entget; set DANGEROUS_COMMANDS_ENABLED=true to allow all LISP expressions.
```

另一条（交互式命令）：

```text
LISP expression rejected: contains a restricted function.
'gettext' at line 1, column 116 waits for the operator's input,
which holds AutoCAD's only COM thread; no LISP_POLICY tier runs it.
```

### 1.2 表格单元格中文空白

`entity_create_table` 建表后：**标题行中文正常显示，表头与表体全空白**。纯 ASCII 表格的单元格同样空白。

---

## 2. 根因

### 2.1 LISP 三档策略（源码核实）

`config.py:22` 定义 `LISP_POLICIES = ("read", "denylist", "off")`，**默认 `read`**（`config.py:285`）。

`security_lisp.py:346 symbol_tier()` 分级规则：

| 判定 | 符号 |
|---|---|
| `read` | `vla-get-*`、`entget`、`getvar`、几何函数 |
| `write` | `vla-put-*`、`vla-` 前缀（`security_lisp.py:363`） |
| `none` | `getpoint`/`getstring` 等一切交互式 `get*`（会独占 COM 线程） |

`read` 档只放行 read tier；`write` 与 `none` 都落到 1.7 黑名单（`security.py:416 _DANGEROUS_LISP_PATTERNS`，其中 `r"vla[xr]?-[\w-]+"` 匹配**所有** vla-/vlax- 调用）被整条拒绝。

**这不是程序缺陷，是 1.8.0 默认安全策略。**

### 2.2 表格中文空白的真正原因

用 ezdxf 直接读 DXF 里的 `ACAD_TABLE` 虚拟实体，证据如下：

```text
'BOM TEST'  x= 3250.0 y= 7600.0 h= 250.0 sty= None att= 5
'NAME'      x= 1250.0 y= 6800.0 h= 250.0 sty= None att= 5
'GPU RACK'  x= 1250.0 y= 6000.0 h= 250.0 sty= None att= 5
```

- **数据和居中都是对的**（`attachment_point=5` 正中，列内居中准确）
- **`style = None`** → 回退 `Standard` 样式，字体 `txt.shx`，**没有 CJK 字形** → 中文空白
- 快照渲染器（`view_screenshot` 的 region 模式，走 `Document.Export`）**根本不绘制 TABLE 单元格文字**，所以截图看不到不代表数据缺失

> ⚠️ **不要用 `GetTextString` 判断表格内容是否存在**。ActiveX 签名是 3 参数 `GetTextString(row, col, nContent)`，少传参数返回 `nil`，会严重误导。用 ezdxf 读 DXF 的 `virtual_entities()` 才可靠。

---

## 3. 处理

### 3.1 开启 LISP 写层

在 `~/.claude.json` → `mcpServers.autocad.env` 增加：

```json
"LISP_POLICY": "off",
"DANGEROUS_COMMANDS_ENABLED": "true"
```

| KV | 默认 | 放开范围 |
|---|---|---|
| `LISP_POLICY` | `read` | `off` = LISP 完全不检查 |
| `DANGEROUS_COMMANDS_ENABLED` | `false` | 命令字符串也不检查（`system_run_command` 任意命令） |

只想放开 LISP、保留命令检查时，只设 `LISP_POLICY=off` 即可（影响面更小）。

**改完必须重启 MCP 进程**，否则配置不生效：

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='autocad-mcp.exe'" |
  Where-Object { $_.CommandLine -match 'autocad-mcp' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### 3.2 表格中文的正确做法

`LISP_POLICY=off` 后 **`vla-AddTable` + `vla-SetText` 可正常写入数据**，但**单元格字体仍是 `Standard`**，中文依旧空白。可靠方案两条：

**方案 A（推荐）：不用 TABLE，手绘表格线 + MTEXT**

MTEXT 支持 `attachment_point=5`（正中），可精确指定 `style="CN"`，完全绕开 TABLE 的样式隔离：

```python
mt = msp.add_mtext(s, dxfattribs={"style": "CN", "char_height": h})
mt.set_location((x, y), attachment_point=5)     # 5 = 正中
```

再用 LWPOLYLINE + LINE 画格线。行高、字高、居中全部可控。

**方案 B：原生 TABLE + LISP 改每个单元格字体**

```lisp
(vla-SetCellStyle tbl r c "CN")     ; 需先 textstyle_create 建 CN
(vla-SetCellAlignment tbl r c 5)    ; 5 = acMiddleCenter
```

### 3.3 无效的尝试（别重走）

| 尝试 | 结果 |
|---|---|
| `vla-GetTextString tbl r c`（2 参数） | 返回 `300.0`/`nil` 等无意义值，**误导性极强** |
| `vla-SetTextString` / `vla-SetText` 后读回验证 | 都返回 `nil`，无法用于验证 |
| `(command "_.TABLE" ...)` | 停在交互提示上**卡死 COM 线程 120s+**，需人工按 ESC |

---

## 4. 预防

1. **看到 `policy_refused` + `tier_needed: write`，先查 `LISP_POLICY`**，不要以为是工具坏了。
2. **表格内容验证一律用 ezdxf 读 DXF 的 `virtual_entities()`**，不用 ActiveX `GetTextString`。
3. **不要在 LISP 里发需要交互输入的命令**（`_.TABLE`、`-LAYER` 停在选项菜单等）。要用 AutoCAD 原生命令时先 `(setvar "CMDDIALOG" 0)`，且优先用 ActiveX 对象模型。
4. **中文标注一律走 TrueType 样式**（`simsun.ttc`），TABLE 的单元格需要单独设样式，不跟随 `AcDbText.StyleName`。
5. **快照渲染器不绘制 TABLE 单元格**，要判断表格显示必须用真实窗口截图（`view_zoom_and_screenshot`）。

---

## 5. 相关

- LISP 策略源码：`security_lisp.py`（`symbol_tier`、`check_expression`）、`security.py:416`（1.7 黑名单）、`config.py:22/159/285`
- 中文显示：[`20261117-chinese-text.md`](20261117-chinese-text.md)
- 表格居中与行高：[`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md)

---

*2026-11-18 记录。补充两种开关的准确 KV 名、LISP 三档策略的源码位置、以及 ActiveX GetTextString 的误导性陷阱。*
