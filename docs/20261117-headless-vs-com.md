# 无头 ezdxf 与 COM 直连的选型：速度、能力边界与 DWG 回写

> 记录日期：2026-11-17
> 环境：AutoCAD 2026（`25.1s (LMS Tech)`，`D:\autocad_26\AutoCAD 2026\`）、`autocad-mcp-pro==1.8.0`、Windows
> 任务背景：绘制并多轮修订 `telecom_equipment_room_plan.dwg`（通信机房平面图）

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 第 5 节双引擎边界、第 11 节记录制度
> - [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) — 部署与能力基线
> - [`20261117-autocad-troubleshooting.md`](20261117-autocad-troubleshooting.md) — 问题索引

---

## 1. 现象

同一批改图操作，两种引擎的耗时相差两个数量级；且无头引擎**无法把结果写回 `.dwg`**。

**现象 A — COM 单次改图慢且失败代价高**

在 COM 后端下逐次修改文字/移动实体，单次调用耗时实测（取自 `step1_out.txt` 等服务日志的 `duration_ms`）：

| 调用 | duration_ms |
|---|---|
| 建立会话（首次） | 43 487 |
| `entity_batch_create`（15 个文字） | 2 880 |
| `entity_delete_many` | 394 |
| 单次 `entity_move` | 223 |
| 若干轻量查询 | 8–17 |

超时时返回：

```text
Internal error: Error calling tool 'drawing_info': AutoCAD did not respond within 60s.
The application may be showing a modal dialog or have an active command prompt (press ESC in AutoCAD).
The abandoned call may still complete in AutoCAD after this error - the worker is blocked inside
an uncancellable COM call, not stopped - so verify the drawing before retrying: a retry can
double-apply the operation.
```

随后继续调用得到：

```text
AutoCAD COM error (-0x7ffeffff): AutoCAD refused the lookup of 'Count' (busy)
AutoCAD COM error (-0x7ffefef2): 应用程序调用一个已为另一线程整理的接口。
```

**现象 B — 无头引擎不能写 DWG**

```text
UnsupportedCapabilityError: drawing_save: the headless ezdxf backend cannot write DWG.
ezdxf has no DWG writer, and writing DXF bytes to
'D:\git_codes\test_Autocad_MCP\draw_test\telecom_equipment_room_plan.dwg'
would produce a file AutoCAD refuses or misreads.
Save with a .dxf extension instead, or switch to the live COM backend
(AUTOCAD_MCP_BACKEND=com, needs Windows + AutoCAD) for real DWG output.
```

**现象 C — 同一工具在两引擎下结果不同**

`arch_rooms_detect` 对同一份图纸：

| 引擎 | 返回 |
|---|---|
| COM | 3 间房，面积 54.4752 / 20.4204 / 14.8764 m²，`confidence: 1` |
| 无头 ezdxf | `rooms: []` |

---

## 2. 根因

### 2.1 慢的是 COM 跨进程往返，不是文件格式

COM 后端每次工具调用都要穿过 `out-of-process` COM 边界进入 AutoCAD 的 STA 线程，并由 AutoCAD 主线程排队执行。无头 ezdxf 是在 Python 进程内存里直接改 DXF 文档，没有 IPC、没有 UI 线程调度，所以同样改 15 个文字：

- COM：2 880 ms（一次往返，含 Regen）
- 无头：几十毫秒（纯内存操作）

**结论：决定速度的是「有没有 COM 往返」，不是「DXF 还是 DWG」。**

### 2.2 超时后的代价不对称

COM 调用超时只是**客户端放弃等待**，服务端那个 STA 作业仍在 AutoCAD 里跑（错误原文明确写了 `The abandoned call may still complete in AutoCAD after this error`）。于是：

- 后续调用被 `(busy)` 拒绝，需等待或被 `ESC` 打断；
- 已写入的一半内容留在文档里，重试可能重复应用；
- 曾因此出现多个 `Drawing1..Drawing11` 空文档，且 `drawing_new` 抢占活动文档导致跨会话互相踢。

无头引擎一旦抛错，文件保持原样，重跑即可——**失败代价接近零**。

### 2.3 无头能力的硬边界

| 项 | 依据 |
|---|---|
| 不能写 DWG | 无 ODA File Converter；ezdxf 无 DWG writer。错误以 `capability: "dwg_write"` 拒绝 |
| 部分几何识别不可用 | `arch_rooms_detect` 依赖 AutoCAD 内部几何/面拓扑，无头返回空数组 |
| 无命令/AutoLISP、无交互选点 | `system_capabilities` 中 `lisp`、`interactive_prompt` 在无头下不支持 |

---

## 3. 处理

### 3.1 本次采用的两段式流程（无头改 + accoreconsole 转 DWG）

```powershell
# ① 无头引擎改图，存 DXF
$env:AUTOCAD_MCP_BACKEND="ezdxf"
$env:ACCORECONSOLE_PATH="D:\autocad_26\AutoCAD 2026\accoreconsole.exe"
# ... 调 entity_move / entity_batch_create / drawing_save_as(path=*.dxf)

# ② accoreconsole 把 DXF 另存为 DWG
& "D:\autocad_26\AutoCAD 2026\accoreconsole.exe" `
    /i "D:\...\telecom_equipment_room_plan_fixed.dxf" `
    /s "D:\...\saveas.scr"
```

`saveas.scr` 内容（**必须用正斜杠**，见 3.3）：

```text
_FILEDIA
0
_.SAVEAS
2018
D:/git_codes/test_Autocad_MCP/draw_test/telecom_equipment_room_plan.dwg
_.QUIT
```

③ 转换后**重新打开生成的 DWG 复测**，不引用转换前的内存状态。

### 3.2 选型判据（本次实测得出）

| 场景 | 推荐 | 理由 |
|---|---|---|
| 一次画完整张图（`arch_plan_from_spec` 等批量建模） | **COM** | 批量操作 COM 也只走一趟；无头还要多付一次 3–6 s 转换 |
| 多轮小改（挪文字、改字高、居中轴号） | **无头** | 单次 6–70 ms，省掉的 COM 往返远超转换开销 |
| 需要读房间/墙体面拓扑、AutoLISP、交互选点 | **只能 COM** | 无头能力拒绝或返回空结果 |
| 目标产物必须是 `.dwg` 且要反复迭代 | **无头改 → accoreconsole 转** | 兼顾速度与格式；每次转完务必复测 |

### 3.3 无效尝试（写下来避免重走）

| 尝试 | 结果 |
|---|---|
| 用 Bash heredoc 写 `saveas.scr`，路径用反斜杠 | `\t`、`\d` 被 shell 解释成制表符/转义，路径被破坏 → 改用正斜杠或单引号 heredoc |
| 目标 `.dwg` 已存在时直接转 | 提示「文件已存在且为只读」，未覆盖 → 先备份再删除旧 DWG |
| AutoCAD 仍开着时删除 `.dwg`/`.dwl`/`.dwl2` | `Device or resource busy` → 先 `Stop-Process acad` 释放文件锁 |
| COM 挂起后重启 AutoCAD 再调 MCP | 仍报 `RPC 服务器不可用 (-2147023174)`，服务进程缓存着已失效的 COM 句柄 → 杀掉 `python.exe` 中 `autocad-mcp` 进程重连（本次需在客户端 `/mcp` 重连） |
| 用系统 `python` 渲染预览 | `ModuleNotFoundError: No module named 'ezdxf'` → 用 MCP 自带解释器 `uv/cache/archive-v0/<hash>/Scripts/python.exe` |
| `drawing_save_as` 传 `fmt="dwg"` | `Unexpected keyword argument`，参数名是 `format`（且扩展名优先） |
| `predicate` 选择器写 `type: "lwpolyline"` / `"text"` | 校验器只认 `line/circle/arc/ellipse/polyline/point/spline/dimension` |
| `arch_element` 选择器按 `room:R1` 计数 | 房间记录挂在文字上，计数得 0；应改用 `predicate` + 几何，或先用 `arch_rooms_detect` 实测面积 |

### 3.4 本次结果（实测证据）

在**转换后的 DWG 文件上**复测：

| 项 | 结果 |
|---|---|
| 文件 | `draw_test\telecom_equipment_room_plan.dwg`，64 299 字节 |
| 实体 / 图层 / 单位 | 231 / 28 / mm |
| 轴号居中（12 个） | 文字包围盒中心与圆心最大偏心 **0.000 mm** |
| 文字互压 | **0** 对 |
| `drawing_verify_requirements` | `status: pass`、`accepted: true`（设备实测 25 台 = 目标 25） |
| `drawing_critique` | error/warning **0** |

---

## 4. 预防

1. **先定产物格式再选引擎。** 交付要 `.dwg` 且需要多轮改 → 走「无头改 DXF + accoreconsole 转 DWG」，每轮转完必须重开复测。
2. **不要用 COM 做高频小改。** 单次 200 ms–3 s 且超时要等 60 s，失败还留半份脏数据。
3. **一次成图用 COM 的批量工具。** `arch_plan_from_spec` / `entity_batch_create` 一趟完成，别拆成多次小调用。
4. **COM 超时后先确认文档状态再重试**，不要原样重发——原文已警告可能重复应用。
5. **需要房间面积/墙体拓扑时只用 COM。** 无头返回 `rooms: []` 不是「没有房间」，是能力缺失。
6. **给脚本传 Windows 路径时用正斜杠**，或使用带引号的 heredoc，避免 `\t`/`\d` 被转义。
7. **转换前备份、转换后复测**：`cp x.dwg x.bakN` → 删旧 → 转换 → 重新打开生成的 DWG 实测。

---

## 5. 一条命令速查

```powershell
# 无头改图后转 DWG 的标准三段
& "D:\autocad_26\AutoCAD 2026\accoreconsole.exe" /i "<改完的>.dxf" /s "saveas.scr"
Get-ChildItem "<目标>.dwg" | Select-Object Name,Length,LastWriteTime
# 再用 AUTOCAD_MCP_BACKEND=ezdxf 打开这个 .dwg 复测
```

---

*首次记录于 2026-11-17，来自通信机房平面图的多轮修订实测。若后续装了 ODA File Converter，2.3 节「不能写 DWG」需重新评估。*