# AutoCAD 卡在未结束的命令上：文档级 COM 全被拒，应用级正常

> 记录日期：2026-11-19
> 环境：AutoCAD 2026 (`25.1s`)、pywin32、`autocad-mcp-pro` 1.8.0（COM 引擎）
> 相关文档：[`20261119-system-status-stale-proxy-p0.md`](20261119-system-status-stale-proxy-p0.md)、[`20261119-dxf-save-fails-after-reopen.md`](20261119-dxf-save-fails-after-reopen.md)

## 现象

MCP 所有工具都报同一句：

```text
AutoCAD refused the call (RPC_E_CALL_REJECTED): it is waiting at a command
prompt or showing a dialog. Nothing was written. Press ESC in AutoCAD ...
```

`system_status` 返回 `connected: false`。人工看 AutoCAD 窗口：正常显示，无弹窗，
无 `#32770`，标题栏有文档名，看起来完全健康。

**但关键的误导点在这里：`system_status` 报 `connected: false` 让人以为 MCP 断开，
实际是 AutoCAD 单方面拒收调用。** 判别方法见下面的「根因」。

## 根因

不是 MCP 断连，不是死代理缓存（那是 P0，已修），也不全是"忙"——
**AutoCAD 有一个命令停在提示符上等输入，`GetAcadState().IsQuiescent` 为 `False`。**
`IMessageFilter` 在非静默状态下对**文档级**调用一律返回 `RPC_E_CALL_REJECTED`。

### 决定性证据：应用级能通，文档级全拒

同一个 `Dispatch` 对象，逐项探测：

| 调用 | 结果 |
|---|---|
| `app.Visible` | ✅ OK `True` |
| `app.Version` | ✅ OK `'25.1s (LMS Tech)'` |
| `app.Caption` | ✅ OK `'Autodesk AutoCAD 2026 - [multi_save.dxf]'` |
| `app.GetAcadState()` | ✅ OK，**`IsQuiescent = False`** |
| `app.ActiveDocument` | ✅ OK（返回对象） |
| `app.Documents.Count` | ❌ `-2147418111` `RPC_E_CALL_REJECTED` |
| `doc.Name` / `.FullName` / `.Saved` / `.ReadOnly` | ❌ 全部 `-2147418111` |
| `doc.Save()` | ❌ `-2147418111` |

`GetAcadState` 能答、而且答"我正忙"——这一条就定了性：**AutoCAD 认为自己在执行
命令**，所以拒收文档级自动化，同时**你这个人在界面上按 Ctrl+S 也会被忽略**。

### 排除的假设（都实测过）

| 假设 | 证伪证据 |
|---|---|
| 有模态对话框 | 全系统扫 `#32770`：acad.exe 下一个都没有 |
| UI 线程挂死 | `IsHungAppWindow = False`，`WM_NULL` 在 **0 ms** 内送达 |
| 在菜单/移动循环里 | `GetGUIThreadInfo.flags = 0`，`hwndMenuOwner = 0` |
| CPU 在算东西 | acad.exe 4.3 s 采样只 **9.4%**；6 个线程全 `Wait/UserRequest` |
| MTA 能绕过 | 用 `COINIT_MULTITHREADED` 重试，`Documents.Count` 一样被拒 |
| MCP 死代理（P0 那个） | `system_status` 未报 `proxy_dropped`；且重启 AutoCAD 无效 |

**"忙"这个词会误导人。** 线程都在 `Wait/UserRequest`（等输入），不是在计算。
真正发生的是：一个命令停在提示符上，等着一个永远不会来的输入。

## 处理

### 有效的做法：ESC 要发给**每个子窗口**，不是发给主框架

只对主框架 `AfxMDIFrame140u` `PostMessage` ESC **无效**（试了 3 轮，每轮 2 条消息）。
必须遍历框架的**全部后代窗口**（实测 36 个），包括绘图视口
`ACADDM_CHILD_DXGI_FLIP_MODE_VIEW_CLASS`：

```python
import ctypes
from ctypes import wintypes

u = ctypes.WinDLL("user32")
VK_ESCAPE, WM_KEYDOWN, WM_KEYUP = 0x1B, 0x0100, 0x0101

def collect(hwnd, out):
    """框架 + 全部后代（含两层以上的视口）。"""
    out.append(hwnd)
    kids = []
    u.EnumChildWindows(hwnd, ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                        wintypes.LPARAM)(lambda k, _l: (kids.append(k), True)[1]), 0)
    for k in kids:
        collect(k, out)

for h in targets:
    u.PostMessageW(h, WM_KEYDOWN, VK_ESCAPE, 1)
    u.PostMessageW(h, WM_KEYUP,   VK_ESCAPE, 0xC0000001)
```

实测效果：

```text
BEFORE: IsQuiescent=False | Documents.Count 被拒 (-2147418111)
STEP 1: PostMessage ESC → 36 个窗口
after : IsQuiescent=True  | Documents.Count=2      ← 一轮恢复
```

`PostMessage` 是异步的、不抢焦点，比 `keybd_event` 温和；
`keybd_event` 需要先 `SetForegroundWindow`，会打断用户手上的操作。

### 无效的做法（不要再走）

- ❌ 只给主框架发 ESC —— 试了 3 轮无效
- ❌ 等 —— 60 s 内 20 次重试全部被拒，不会自己好
- ❌ 重启 AutoCAD —— 那条命令不会自己消失，重启只是代价更大
- ❌ 重启 MCP 服务 —— 与 MCP 无关，`connected: false` 是 AutoCAD 说的
- ⚠️ `keybd_event` + `SetForegroundWindow` —— 有效但会抢焦点，仅在 PostMessage 失败时用

## 预防

1. **`system_status` 报 `connected: false` 不等于 MCP 断连**。先看有没有
   `proxy_dropped`（那是 P0）；没有的话，用 `GetAcadState().IsQuiescent` 判别，
   而不是去杀进程重连。
2. **`GetAcadState()` 是唯一能在"全线拒绝"时还答话的接口**——它挂在 Application
   对象上，不受文档级过滤影响。诊断时第一个就调它。
3. **应用级能通、文档级全拒 = 有命令停在提示符上**。这个组合很特征化，别误判成断连。
4. **ESC 必须广播到所有后代窗口**，只发给主框架不管用。已封装进
   `scripts/clear_pending_command.py`。
5. **"忙"要分两种**：CPU 高才是真在算；CPU 低 + 线程 `Wait/UserRequest` 是**在等输入**，
   对应处理完全不同（等没用，要 ESC）。

## 更新说明

- 2026-11-19 首次记录。发现于「重启 Claude Code 后验证新代码」，
  当时 AutoCAD 里挂着 `multi_save.dxf`，界面上按 Ctrl+S 也存不了。
- 与 P0（`20261119-system-status-stale-proxy-p0.md`）是两个独立问题：
  P0 是 MCP 侧缓存死代理，本问题是 AutoCAD 侧有未结束命令。两者都表现为
  `connected: false`，但判据不同（P0 有 `proxy_dropped`，本问题 `IsQuiescent=False`）。