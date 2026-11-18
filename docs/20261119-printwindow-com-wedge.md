# PrintWindow 截图导致 AutoCAD COM 失效

> 记录日期：2026-11-19
> 环境：AutoCAD 2026（`25.1s (LMS Tech)`，`D:\autocad_26\AutoCAD 2026\`）、Windows、pywin32
> 发现场景：想给用户截一张优化后 DWG 的图，自己写了 `PrintWindow` 抓窗口，把 AutoCAD 搞卡

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 第 10 节排错、第 11 节记录制度
> - [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) — MCP 断开与 COM 句柄失效
> - [`20261118-chinese-text-dwg-fix.md`](20261118-chinese-text-dwg-fix.md) — 判断中文显示只认真实窗口截图

---

> **一句话结论**：**不要用 `PrintWindow` 截 AutoCAD 窗口。** 它返回全白图，并且会向 AutoCAD 发同步重绘请求，把消息循环搞乱，之后 COM 拒绝所有调用（`<unknown>.Count`、`RPC_E_CALL_REJECTED`）。要截图用 MCP 的 `view_screenshot`。

---

## 现象

三步连锁，每一步单独看都像别的问题。

### 一、截出来全白

```python
ctypes.windll.user32.PrintWindow(hwnd, hdc, 2)
```

返回 `True`（成功），但 PNG 全是白的：

```
opt_tags.png  1568x930  内容: 全白
```

### 二、接着 COM 属性访问开始抛异常

上一刻还好好的调用，几秒后变成：

```python
app.Documents.Count
# AttributeError: <unknown>.Count
```

```python
win32com.client.GetActiveObject("AutoCAD.Application")
# 能拿到对象，但读任何属性都失败
```

再往后：

```python
com_error: (-2147221021, '操作无法使用', None, None)   # MK_E_UNAVAILABLE
```

### 三、MCP 工具报

```
Internal error: AutoCAD refused the call (RPC_E_CALL_REJECTED):
it is waiting at a command prompt or showing a dialog.
```

注意这条**具有误导性**：它说「等在命令提示符或对话框」，但实际按 ESC 也没用，因为 AutoCAD 不是在等输入，是**自动化服务器本身卡住了**。

---

## 根因

**AutoCAD 2026 的绘图区走 GPU 合成，不在 GDI 表面上。**

| 方式 | 结果 | 原因 |
|---|---|---|
| `PrintWindow` | 全白 | 抓的是 GDI 内容，GPU 合成图层不在里面 |
| `BitBlt` 从屏幕 DC | 也全白（同样试过） | 同上 |
| `view_screenshot`（MCP） | ✅ 正常 | 它走的是 AutoCAD 自己的截图通道 |

**致命的是副作用，不是白图本身**：`PrintWindow` 会向目标窗口发 `WM_PRINT` / `WM_PRINTCLIENT`，**要求它同步重绘**。AutoCAD 的绘图区在渲染线程里，这个同步请求打乱了它的消息循环 → COM 自动化服务器进入不可用状态，但进程仍然活着（`tasklist` 能看到 `acad.exe`，内存正常）。

所以这不是崩溃，是**卡死**。这也解释了为什么：
- 进程还在，但 `app.Documents` 读不了
- 报 `RPC_E_CALL_REJECTED`（"被呼叫方拒绝接收呼叫"）—— 典型的 STA 线程忙/阻塞
- 按 ESC 无效，因为它不在等命令输入

---

## 处理

### 恢复

按顺序试，**不要一上来就杀进程**：

| 步骤 | 做法 | 结果 |
|---|---|---|
| 1 | 手动在 AutoCAD 窗口按 ESC / 点一下命令行 | **这次有效**，COM 恢复 |
| 2 | 关掉挡着的对话框 | 若有模态框必须关 |
| 3 | `taskkill /F /IM acad.exe` + 重启 | 会**关掉未保存的文档**，慎用 |

第 1 步这次成功了。恢复后立刻验证：

```python
app = win32com.client.Dispatch("AutoCAD.Application")
app.Documents.Count          # 能读出数字才算恢复
```

### 杀进程前必须确认没有未保存工作

这是本轮真正的教训。当时 AutoCAD 里开着 `Drawing7.dwg`，`Saved=False` 且 `FullName=''`（**新建后从未存过盘**）。如果按 AGENTS.md 的常规做法直接 `taskkill`，那份工作就没了。

判断「有没有未保存的东西」，**在 COM 已经失效时只能靠窗口标题**：

```python
import win32gui
win32gui.EnumWindows(
    lambda h, _: print(win32gui.GetWindowText(h))
    if "AutoCAD" in win32gui.GetWindowText(h) and win32gui.IsWindowVisible(h) else None,
    None,
)
```

标题里带 `*` 表示有未保存修改。COM 可用时也可以读 `doc.Saved`。

### 正确的截图方式

```python
# MCP 工具，一次调用
view_screenshot()          # source: window，真实窗口截图
```

或者先缩放再截：

```python
view_zoom_window(x1=..., y1=..., x2=..., y2=...)
view_screenshot()
```

返回里的 `source: window` 说明是真实窗口截图。**`view_screenshot` 的 region 模式不要用来判断文字** —— 它走 `Document.Export` 渲染器，会丢文字（见 `20261118-chinese-text-dwg-fix.md`）。

---

## 预防

1. **禁止 `PrintWindow` / `BitBlt` 截 AutoCAD。** 用 `view_screenshot`。这条已加入 AGENTS.md 第 10 节。
2. **想截图前先确认 AutoCAD 里有没有未保存的文档。** 先在 AutoCAD 里存盘，再让我操作。
3. **看到 `RPC_E_CALL_REJECTED` 先按 ESC，别急着重启。** 这条错误码的提示（"等在命令提示符"）会误导人。
4. **杀 `acad.exe` 之前必须查窗口标题里的 `*`。** 这是 COM 失效时唯一还能用的未保存检测手段。
5. **`accoreconsole` 在本机不可用**，别指望它做无头转换：实测带 `/s` 脚本会卡住（`exit=124`），输出是「AutoCAD 许可证无效或未安装」。DWG 读写只能靠运行中的 AutoCAD + COM。

---

## 附：本轮实际走过的弯路

为了给用户看「字高 160 vs 250 的纸面对比」，我依次试了：

| 尝试 | 结果 |
|---|---|
| `PrintWindow` 抓 AutoCAD 窗口 | 全白，**且把 COM 搞卡** |
| `BitBlt` 从屏幕 DC | 全白 |
| ezdxf 的 matplotlib 后端渲染 DXF | **文字全部丢失**，只剩几何 |
| matplotlib 按真实 mm 排版字体 | 前两版 `figsize` 用错单位（÷10 而非 ÷25.4），两行字看起来一样大 |
| 修正后按像素量 | 图形尺寸对了，但裁剪坐标三次没落准 |

最后**是用户自己在 AutoCAD 窗口里看的图并确认效果**。教训：这类「让用户看效果」的事，直接让用户打开文件看，比自己造图可靠得多 —— 我花了一小时造替代渲染，不如让用户看一眼。

---

*本文记录 2026-11-19 的排查过程。遇到同类现象请先看「处理」一节。*