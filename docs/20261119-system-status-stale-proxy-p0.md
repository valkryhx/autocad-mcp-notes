# P0：`system_status` 缓存死代理，一次失联变成永久失联

> 记录日期：2026-11-19
> 环境：AutoCAD 2026 (`25.1s`)、`autocad-mcp-pro` 1.8.0（editable 源码安装）、pywin32
> 源码：`D:\git_codes\Autocad-MCP\backends\com_backend.py`
> 相关文档：[`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md)（上一轮的重连修复）

## 现象

杀掉 `acad.exe` 后，MCP 的每一次调用都报同一个错，**永远不会自己恢复**：

```text
{"backend":"com","connected":false,"error":"(-2147023174, 'RPC 服务器不可用。', None, None)"}
```

连续调 3 次、5 次，结果一字不差。重启 AutoCAD 也没用——因为缓存里那个 COM 代理早就指向已死的进程。
唯一的恢复手段是把 MCP 服务进程杀掉重开，而使用者的感受就是 **“AutoCAD MCP 又断了”**。

用户的原话：「为何 autocad MCP 经常断开？我记得是指向本地源码的方式使用 mcp 按理说应该很稳定啊」。

## 根因

`system_status()` 在自己的 `_sync` 里把异常**吞掉并返回状态**，没有驱逐缓存的 Application 代理：

```python
def _sync():
    try:
        app = _acad_app()
        ...
    except Exception as exc:
        log.debug("system_status: _acad_app check failed: %s", exc)
        status = {"backend": "com", "connected": False, "error": str(exc)}
        return status            # ← 拿到这里，_run 的 drop 分支永远走不到
```

而 `_acad_app()` 只在 `"app" not in _COM_STATE` 时才重新 `Dispatch`：

```python
if "app" not in _COM_STATE:
    _COM_STATE["app"] = win32com.client.GetActiveObject(progid)
    ...
return _COM_STATE["app"]     # ← 死代理被永久复用
```

`_run()` 在 `_CONNECTION_LOST` 里是会 `_drop_app()` 的（提交 `9654e01` 修的就是这个），
但 `system_status` 把异常在**进到 `_run` 之前**就 catch 了，那条路根本走不到。

**为什么这是 P0 而不是普通 bug**：`system_status` 恰恰是出故障后第一个被调用的工具。
它一边报告 `connected: false`，一边把死代理留在缓存里，下一个调用继续踩同一个坑。
本来是“一次失联，下次自动重连”，变成了“一次失联，永久瘫痪”。

### 定位过程

1. 查 `~/.claude.json`：确认 `direct_url: {'editable': True}`，配置指向源码，且运行的是最新提交
   —— **排除“配置指向了旧包”** 这个最常见的猜测
2. 翻会话日志：5 次断连**全部**发生在“我杀了进程”之后（`killed` / `Killing ... autocad-mcp.exe` / `remaining=0`）
3. 查 journal（`autocad-mcp-pro/state/journal.sqlite3`）：**71 个 `server_instance`**，24 个只处理过 1 次调用
   —— 那一堆实例就是重启史，不是崩溃史
4. 但 `timed_out` 有 16 次、全部卡在 60.x 秒，`apply_busy` 13 次 —— 说明还有别的诱因让人不得不杀进程
5. 做对照实验：干净启动 → 3 次调用全正常；杀 acad → **3 次全部 `RPC 服务器不可用`，不自愈**
6. 手工 `_drop_app()` 后再调 → **立刻恢复**（`connected=True, version=25.1s`）
   —— 到这里根因锁定

## 处理

### 1. 抽出共用判据

新增两个模块级函数，让“是不是连接丢失”只有一个定义：

```python
def _hresult_of(exc: BaseException) -> int | None:
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None

def _drop_app_if_connection_lost(exc: BaseException) -> bool:
    if _hresult_of(exc) not in _CONNECTION_LOST:
        return False
    _drop_app()
    return True
```

### 2. `system_status` 的异常分支补上驱逐

```python
except Exception as exc:
    dropped = _drop_app_if_connection_lost(exc)
    status = {"backend": "com", "connected": False, ..., "error": str(exc)}
    if dropped:
        status["proxy_dropped"] = True
        status["next_call_reconnects"] = True
    ...
```

`proxy_dropped` / `next_call_reconnects` 两个字段让调用方**看得出“重试一次就好”**，
不用去猜要不要重启服务。

### 3. 回归测试

新增 `tests/test_system_status_reconnect.py`，5 个测试：

| 测试 | 断言 |
|---|---|
| `test_system_status_drops_a_dead_proxy`（参数化 2 个 HRESULT） | `RPC_S_SERVER_UNAVAILABLE` / `RPC_E_DISCONNECTED` 都必须驱逐缓存 |
| `test_system_status_reconnects_on_the_next_call` | 第 2 次调用必须重连成功，且**确实重新问了代理**（`_acad_app` 被调用 2 次） |
| `test_system_status_keeps_the_proxy_on_a_document_scoped_error` | `DISP_E_EXCEPTION` 这类非连接错误**不能**驱逐（否则会把无害的读失败升级成重连/重启 AutoCAD） |
| `test_connection_lost_set_matches_what_system_status_acts_on` | 遍历 `_CONNECTION_LOST` 每个成员都必须驱逐；且 `RPC_E_CALL_REJECTED` 必须**不在**集合里 |

测试在修复前是失败的（3 failed），修复后 5 passed —— 说明它们真的在测这个 bug。

### 4. `COM_CALL_TIMEOUT` 提到 3600

```json
"COM_CALL_TIMEOUT": "3600"
```

journal 里 `cad_batch` 实测 191.6s、`arch_plan_from_spec` 106.8s、`drawing_screenshot` 193.9s，
原来的 180s 会把长作业拦腰截断；而超时之后**作业仍在 AutoCAD 里跑**，
下一次调用就撞上“忙”，于是又去杀进程 —— 这正是上面那个恶性循环的另一半。

## 实测验证

```text
① 初始 system_status: connected=True version=25.1s (LMS Tech)
② taskkill /F /IM acad.exe
③ 第1次: connected=False proxy_dropped=True  next_reconnects=True  err=RPC 服务器不可用
   第2次: connected=True                                        ← 自动恢复
   第3次: connected=True
④ document_list -> 1 个文档: ['Drawing1.dwg']   ✅ 无需重启 MCP 服务即恢复
```

修复前同一实验：3 次全是 `connected=False`，`document_list` 同样失败。

全量测试：**7590 passed**，4 failed —— 这 4 个全部与本次改动无关：
- `test_release_consistency`：统计代码树里的测试数量（我新增了测试文件，数字 7583→7597），
  **在原代码上同样失败**，已用 `git stash` 验证
- `test_shutdown_grace` / `test_skill_eval`（2 个）：单独跑均通过，是全量并行时的时序抖动

## 预防

1. **任何“吞掉 COM 异常并返回状态”的入口都必须调 `_drop_app_if_connection_lost`。**
   局部属性读取失败（读不到线宽就用 ByLayer）是合理降级，但**连接级失败不能降级**——
   它必须驱逐代理，否则会变成永久故障。
2. **`_CONNECTION_LOST` 是唯一判据**，`_run`、`_handle_to_object`、`system_status` 三处共用，
   不允许再各写一份（`9654e01` 修的就是两份集合漂移的同类问题）。
3. **`RPC_E_CALL_REJECTED` 绝不能进这个集合。** 那时服务器活着、只是忙，
   在该处驱逐会把“按 ESC 后重试”升级成完整重连（`CAD_LAUNCH=auto` 下甚至会再启一个 AutoCAD）。
4. **诊断顺序**（下次遇到“MCP 又断了”）：
   ① 看窗口标题有没有 `*`（唯一在 COM 失效时仍可用的判据）
   ② 调 `system_status`，看 `proxy_dropped` 是否为 true（true = 重试一次就好）
   ③ 查 journal 的 `server_instance` 数量，暴涨说明有人在反复杀进程
   ④ 查 `process_exit` / `timed_out`，区分“服务崩了”和“超时后我杀了服务”
5. **先怀疑自己的操作，再怀疑代码。** 这次 5 次断连全部是手动杀进程造成的；
   但正是那个 P0 让“杀一次”变成“必须一直杀”，所以两者都要修。

## 更新说明

- 2026-11-19 首次记录。修 `system_status` 死代理缓存（P0），`COM_CALL_TIMEOUT` 180→3600，
  新增 5 个回归测试。