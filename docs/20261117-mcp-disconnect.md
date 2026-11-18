# AutoCAD MCP 反复断开：根因排查与恢复手法

> 记录日期：2026-11-17
> 环境：AutoCAD 2026（`25.1s (LMS Tech)`，`D:\autocad_26\AutoCAD 2026\`）、`autocad-mcp-pro==1.8.0`（uvx 启动）、Windows
> 触发场景：连续多轮绘制/修订同一张平面图（`telecom_equipment_room_plan.dwg`）
> 上游状态：修复已提 [PR #26](https://github.com/U-C4N/Autocad-MCP/pull/26)；两个衍生问题见 [#27](https://github.com/U-C4N/Autocad-MCP/issues/27)、[#28](https://github.com/U-C4N/Autocad-MCP/issues/28)

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 第 5 节双引擎边界、第 10 节排错、第 11 节记录制度
> - [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) — 无头 vs COM 选型与 DWG 回写
> - [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) — 部署与能力基线
> - 上游 PR：[#26](https://github.com/U-C4N/Autocad-MCP/pull/26) · 上游 issue：[#27](https://github.com/U-C4N/Autocad-MCP/issues/27) [#28](https://github.com/U-C4N/Autocad-MCP/issues/28)

---

## 1. 现象

本次会话中 MCP 连接反复失效，表现为三类错误轮替出现。

**现象 A — 调用超时（60 s）**

```text
Internal error: Error calling tool 'drawing_info': AutoCAD did not respond within 60s.
The application may be showing a modal dialog or have an active command prompt (press ESC in AutoCAD).
The abandoned call may still complete in AutoCAD after this error - the worker is blocked inside an
uncancellable COM call, not stopped - so verify the drawing before retrying: a retry can
double-apply the operation. Increase COM_CALL_TIMEOUT if a long operation is expected.
```

**现象 B — AutoCAD 活着，但 COM 拒绝一切调用**

```text
AutoCAD COM error (-0x7ffeffff): AutoCAD refused the lookup of 'Count' (busy)
AutoCAD COM error (-0x7ffefef2): 应用程序调用一个已为另一线程整理的接口。
AutoCAD COM error (-0x7ff8f946): RPC 服务器不可用。
```

**现象 C — 客户端报服务断开，工具直接消失**

```text
Error: No such tool available: mcp__autocad__drawing_info.
Its MCP server 'autocad' has disconnected. It becomes callable again only if the server reconnects.
```

**关键观察：`AutoCAD 进程 Responding = True` 且窗口正常时，MCP 依旧全盘失效；重启 AutoCAD 后仍报 `RPC 服务器不可用`，只有杀掉 MCP 服务进程才恢复。**

---

## 2. 根因

证据来自 MCP 自带的操作日志 `C:\Users\drago\AppData\Local\autocad-mcp-pro\state\journal.sqlite3`（`operations` 表，本次会话 379 条）。

### 2.1 统计：一晚上起了 55 个服务实例

```sql
SELECT server_instance, pid, COUNT(*) FROM operations GROUP BY server_instance, pid;
```

| 指标 | 值 |
|---|---|
| 服务实例数 | **55** |
| `timed_out` | 16 |
| `failed` | 22 |
| `active_document_changed` | 8 |
| **`process_exit`** | **7** |
| `refused` | 6 |
| `unknown_tool` | 6 |

时间线（节选）：19:31:01、19:31:14、19:32:01、19:32:16……每 10–15 秒一个新实例，多数存活 **0.0–0.3 s**。这说明客户端在不停地重启子进程——即"断开 → 重连 → 再断开"的循环。

### 2.2 根因一：重连判据漏掉了真正的断连错误码

`backends/com_backend.py:4118`（1.8.0）决定"遇到哪个 HRESULT 才丢弃缓存的 Application 代理并重连"：

```python
except _COM_ERROR as e:
    hr = e.args[0] if e.args else 0
    if hr in (-2147221246, -2147221005, -2147417842):
        _drop_app()
        self._connected = False
```

被覆盖的三个码：

| 常量 | 十六进制 | 含义 |
|---|---|---|
| -2147221246 | `0x80040102` | CO_E_OBJNOTCONNECTED 一类的连接类错误 |
| -2147221005 | `0x800401F3` | CO_E_CLASSSTRING（ProgID 无效） |
| -2147417842 | `0x8001010E` | RPC_E_WRONG_THREAD |

**实际遇到的码：**

| 实际错误 | 十六进制 | 在判据里？ |
|---|---|---|
| `RPC 服务器不可用` (-2147023174) | **`0x800706BA`**（RPC_S_SERVER_UNAVAILABLE） | ❌ **否** |
| `已为另一线程整理的接口` (-2147417848) | **`0x80010108`**（RPC_E_DISCONNECTED） | ❌ **否** |
| AutoCAD 自定义拒绝 | `0x7FFEFFFF` | ❌ 否 |

后果：AutoCAD 进程死掉/卡死时抛的正是 `0x800706BA` 与 `0x80010108`，**服务不认为需要重连**，于是 `_COM_STATE["app"]` 里那个已失效的代理被永久缓存（`_drop_app()` 只在 `_com_teardown`、超时分支、上述三个码时调用）。之后每次调用都撞同一个死代理，直到**进程被杀**才重新 `GetActiveObject`。

这解释了最关键的那个反常现象：**AutoCAD 重启了，MCP 还报 RPC 不可用**——它连的不是新进程。

### 2.3 根因二：60 秒超时只是客户端放弃，AutoCAD 里作业仍在跑

超时错误原文自带说明：

```text
The abandoned call may still complete in AutoCAD after this error -
the worker is blocked inside an uncancellable COM call, not stopped
```

超时后 SolidWorks 侧（AutoCAD 的 STA 线程）仍在执行那个作业，于是后续调用拿到 `(busy)` 与 `0x80010108`。这形成死锁：AutoCAD 被占着 → MCP 不敢重连（见 2.2）→ 一直占着。

### 2.4 根因三：两个 Claude 会话抢同一个 AutoCAD

`active_document_changed` 共 8 次，**全部集中在单个实例 pid=11216**（存活 1228 s）：`layer_create` ×4、`cad_batch` ×2、`drawing_preflight` ×1、`textstyle_create` ×1。

该时段确认同时开了两个会话（`ListAgents` 可见 peer `test-autocad-mcp-b1`）。`drawing_new` 会切换活动文档，两个会话互相把对方的文档切走，触发保护性拒绝；为绕开又反复新建，最终产生 `Drawing1..Drawing11` 共 11 个空档。

### 2.5 不是启动方式的问题

`~/.claude.json` 的启动配置本身正确：

```json
"command": "uvx",
"args": ["--from", "autocad-mcp-pro[com,pdf,office]==1.8.0", "autocad-mcp"],
"env": { "AUTOCAD_MCP_BACKEND": "auto", ... }
```

`backends` 选择逻辑（`server.py:148`）：`auto` 在 Windows 下优先 COM，初始化失败才降级 ezdxf；只有显式 `AUTOCAD_MCP_BACKEND=com` 时失败才抛错。**这段没有问题**。唯一可调的启动参数是当时未设置的 `COM_CALL_TIMEOUT`（默认 60 s）。

---

## 3. 处理

### 3.1 立即恢复（本次验证有效）

MCP 服务是客户端拉起的子进程，**杀掉后客户端会重新拉起一个带全新 COM 句柄的进程**；若客户端判定为断连，再在输入框执行 `/mcp` 重连。

```powershell
# 杀掉所有 autocad-mcp 服务进程（不影响 AutoCAD 本身）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'autocad-mcp' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

一行版（Bash / Git Bash）：

```bash
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'autocad-mcp' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }"
```

然后：

1. 客户端输入 `/mcp` → 重连 `autocad`
2. `system_status` 确认 `connected: true`、`bound_document` 正确
3. **先 `drawing_info` 核对实体数**，再继续写操作（超时的调用可能已写入一半）

### 3.2 已采用的配置调整

在 `~/.claude.json` → `mcpServers.autocad.env` 增加：

```json
"COM_CALL_TIMEOUT": "180"
```

理由：`arch_plan_from_spec` 画整张平面、`drawing_critique` 全图扫描这类操作可能超过 60 s，放宽阈值可显著减少"假超时 → 作业仍在跑 → 后续全部 busy"的连锁。

> 改完需重启 Claude Code（或 `/mcp` 重连）才生效。配置文件已备份为 `~/.claude.json.bak.20261117_213533`。

### 3.3 无效尝试（避免重走）

| 尝试 | 结果 |
|---|---|
| 给 AutoCAD 窗口发 `ESC`（`SendKeys`、`system_run_command`） | 无效。`system_run_command` 本身也走 COM，同样 `(busy)` |
| 等待自然恢复（等 20–150 s 多次） | 无效。死代理不会自己失效，等待无用 |
| 直接重启 AutoCAD 进程 | 无效。MCP 仍报 `RPC 服务器不可用`，因为它缓存着旧代理 |
| 杀掉 MCP 进程但不 `/mcp` 重连 | 工具仍显示 disconnected；需要在客户端重连 |
| 用 `Get-Process acad \| Stop-Process` 后立刻删 `.dwg`/`.dwl`/`.dwl2` | 需等 2–3 s 释放文件锁，否则 `Device or resource busy` |
| 同时开两个 Claude 会话操作同一 AutoCAD | 必冲突（见 2.4），不要这样做 |

### 3.4 根本修复（已实施，提 PR）

在 `backends/com_backend.py` 的重连判据里补上缺失的两个码。

**改动内容**（分支 `fix/com-reconnect-on-connection-lost`，提交 `9654e01`）：

```python
# 新增两个具名常量（附实测证据注释）
_RPC_E_DISCONNECTED = -2147417848        # 0x80010108
_RPC_S_SERVER_UNAVAILABLE = -2147023174  # 0x800706BA

# 新增单一判据集合
_CONNECTION_LOST = frozenset({
    -2147221246, -2147221005, -2147417842,   # 原有三个
    _RPC_E_DISCONNECTED, _RPC_S_SERVER_UNAVAILABLE,   # 新增
})

# _run 里原本的硬编码三元组
- if hr in (-2147221246, -2147221005, -2147417842):
+ if hr in _CONNECTION_LOST:

# _NOT_A_HANDLE_ANSWER 改为复用同一集合，防止两处再次不一致
-_NOT_A_HANDLE_ANSWER = frozenset({ ... 五个硬编码 ... })
+_NOT_A_HANDLE_ANSWER = frozenset({_RPC_E_CALL_REJECTED}) | _CONNECTION_LOST
```

`RPC_E_CALL_REJECTED` 有意**不**放进 `_CONNECTION_LOST`：服务活着只是忙，不算断连；放进去会把「按 ESC 重试」变成完整的重新 Dispatch。

**验证**：`test_com_backend.py` / `test_com_timeout.py` / `test_com_rejected_lookup.py` / `test_cad_launch.py` 共 **110 passed**。没有测试断言旧的三个码元组，因此无需改测试。

**重要发现**：同文件 `_NOT_A_HANDLE_ANSWER` 的注释原本就写明这两个码是连接级、且声称「这三个是 `_run` 丢弃代理的依据」，但 `_run` 的实际元组里没有它们——**同一文件内部自相矛盾**，这是补齐的额外依据。

### 3.5 上游反馈（已提交）

| 编号 | 类型 | 标题 | 链接 |
|---|---|---|---|
| #26 | PR | fix(com): drop the Application proxy on the two disconnects it missed | https://github.com/U-C4N/Autocad-MCP/pull/26 |
| #27 | issue | COM: a 60 s deadline abandons the client but leaves the STA worker inside `SendCommand`; the following calls see `(busy)` | https://github.com/U-C4N/Autocad-MCP/issues/27 |
| #28 | issue | COM: two clients on one AutoCAD make `drawing_new` steal `ActiveDocument` from each other; nothing detects or warns | https://github.com/U-C4N/Autocad-MCP/issues/28 |

- **#26** 对应本节 3.4 的修复；提交 `9654e01`，+32/−14，`MERGEABLE`
- **#27** 记录 2.3 的现象（超时后 STA 作业仍在跑）。另指出 `(busy)` 的 HRESULT 是 AutoCAD 自定义的 `0x7FFEFFFF`，**不是标准码**，任何 HRESULT 映射表都抓不到
- **#28** 记录 2.4 的现象（两会话争抢）。另指出 `drawing_new` 会返回 `ok: true` 但 bootstrap 内部各图层已 `"failed: ..."`，只看 `ok` 会误判为成功

分支：`valkryhx/Autocad-MCP` → `fix/com-reconnect-on-connection-lost`（fork 与上游 main 基线均为 `6f6a538`）

本地仓库：`D:\git_codes\Autocad-MCP`

---

## 4. 预防

1. **一次会话只用一个 Claude 实例操作 AutoCAD。** 需要并行就各自用独立的 AutoCAD 或各自的 DXF 文件。
2. **小改用无头引擎**（`AUTOCAD_MCP_BACKEND=ezdxf`），完全不碰 COM，也就没有断连问题。选型见 [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md)。
3. **COM 操作分批，别把大活堆在一次调用里。** 一张图用 `arch_plan_from_spec` 一次画完，不要拆成几十次小调用。
4. **超时后先 `drawing_info` 核对，不要原样重发**——错误原文明确警告可能重复应用。
5. **出现 `RPC 服务器不可用` 就按 3.1 杀进程**，不要浪费时间重启 AutoCAD 或等它自愈。
6. **遇到 `(busy)` 先想"是不是上次超时的作业还在跑"**，而不是"AutoCAD 卡了"。
7. **每次读写前看 `system_status`**：`connected`、`bound_document`、`active_document_changed` 三个字段足以判断当前是否可用。

---

## 5. 一条命令速查

```powershell
# 卡住时的标准恢复
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'autocad-mcp' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# 然后在客户端输入 /mcp 重连 autocad，先 drawing_info 核对再继续写
```

```powershell
# 查历史：错误类型分布
python -c "import sqlite3;db=sqlite3.connect(r'file:C:\Users\drago\AppData\Local\autocad-mcp-pro\state\journal.sqlite3?mode=ro',uri=True);cur=db.cursor();cur.execute('SELECT error_kind,COUNT(*) FROM operations WHERE error_kind IS NOT NULL GROUP BY error_kind ORDER BY 2 DESC');[print(r) for r in cur]"
```

```powershell
# 查历史：服务实例数（值大说明在反复重连）
python -c "import sqlite3;db=sqlite3.connect(r'file:C:\Users\drago\AppData\Local\autocad-mcp-pro\state\journal.sqlite3?mode=ro',uri=True);cur=db.cursor();cur.execute('SELECT COUNT(DISTINCT server_instance) FROM operations');print('instances:',cur.fetchone()[0])"
```

---

*首次记录于 2026-11-17，来自通信机房平面图多轮修订期间的实测与 journal 取证。*

*2026-11-17 更新：3.4 的根本修复已实施并提交 [PR #26](https://github.com/U-C4N/Autocad-MCP/pull/26)；2.3 与 2.4 的两个衍生问题分别提为 [#27](https://github.com/U-C4N/Autocad-MCP/issues/27)、[#28](https://github.com/U-C4N/Autocad-MCP/issues/28)。PR 合并后 3.1 的「杀进程」可降级为兜底手段。*