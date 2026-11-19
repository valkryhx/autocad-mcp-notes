# 嵌套块的 `via` 变成字符串 `'None'`，以及 COM 的两个参数陷阱

> 记录日期：2026-11-21
> 环境：Windows，AutoCAD 2026 `25.1s (LMS Tech)`，ezdxf 1.4.4
> 触发方式：新画 `draw_test/overlap_proto/drawing9.py` 做验收

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 使用指南（第 10 节排错、第 11 节记录制度）
> - [`20261117-autocad-troubleshooting.md`](20261117-autocad-troubleshooting.md) — 问题索引
> - [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) — 检查工具本体
> - [`20261120-dwg-saveas-repoint.md`](20261120-dwg-saveas-repoint.md) — `SaveAs` 改指向

---

## 背景

Drawing8 证明了七个检查在**图空间里的文字**上会响。它没证明的是另一半：
**文字藏在容器里**时检查器还看不看得见。所以新画 `drawing9.py`，把每一处
碰撞都塞进一种容器：块属性、嵌套块、旋转块、多重引线、表格单元格。

这张图刚造出来就抓到一个真缺陷。

---

## 现象一：`via` 是字符串 `'None'`

```
3. text_text at (2861, 3048)
   9B in None [0] DN100 [style CN]
   crosses 9B in None [0] text DN100 [style CN]
   text is inside block reference None
   this text lives in block reference None; move or edit it inside the block
   definition, not here. ``entity_move`` needs the handle of a top-level entity
```

三句话都在说 `None`。**参考号 `None` 并不存在**，所以这条发现里唯一可执行的那句
（「去块定义里改」）实际无法执行。

## 根因一

`_expand()` 往下钻嵌套块时是这样走的：

```python
if kind == "INSERT":
    nested = member.copy()
    nested.transform(matrix)
    yield from _expand(nested, depth + 1, blocked)     # ← 丢了上一层
else:
    yield member, matrix, str(insert.dxf.handle)       # ← 深一层的 insert 是副本
```

`member.copy()` **不携带 handle**——副本没进 entitydb：

```
原始 INSERT in block def: handle = '91'
copy() 之后:              handle = None
```

于是 `str(insert.dxf.handle)` 得到 `'None'`，一个**非空字符串**，所以一路
畅通无阻地写进报告。没有任何异常、没有 `not_checked`、没有警告。

更糟的是：这份代码在**一层嵌套**时完全正确，因为最外层那次调用用的是真实
`INSERT`，有 handle。现有两个夹具（`test_nested_block`、`test_attrib_*`）
都只有一层，所以六年不遇。**递归里的 bug 需要递归形状的夹具才能暴露。**

## 处理一

把最外层的 handle 作为 `_via` 沿递归传下去，而不是每层重新推导：

```python
def _expand(insert, depth, blocked, _via=None):
    via = _via if _via is not None else str(insert.dxf.handle)
    ...
    if kind == "INSERT":
        nested = member.copy(); nested.transform(matrix)
        yield from _expand(nested, depth + 1, blocked, _via=via)
    else:
        yield member, matrix, via
```

`_expand_table` 里同样的 `yield from _expand(...)` 也补了 `_via=via`。

修后：

```
9B in C2 [0] DN100
text is inside block reference C2
this text lives in block reference C2; move or edit it inside the block definition
```

`C2` 是顶层引用，可以据此选中、进入块定义修改。

回归测试 `test_nested_block_names_the_outer_reference` 锁住两点：嵌套文字的
`via` 必须等于顶层引用的 handle，`origin` 里不许出现 `None`。**不需要 AutoCAD。**

---

## 现象二：`AddTable` 返回 `E_INVALIDARG`

```
com_error: (-2147352567, '发生意外。', (0, None, None, None, 0, -2147024809), None)
```

`-2147024809` = `E_INVALIDARG`。参数个数是对的（5 个），所以错误文案指向的不是
真正原因。

## 根因二

插入点必须是 **VARIANT 数组**，不能是元组。和 AGENTS.md 第 10 节记录的
`Table.Move` 是同一个 COM 要求：

```python
from win32com.client import VARIANT
from array import array
point = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, array("d", [x, y, z]))
table = msp.AddTable(point, rows, cols, row_h, col_w)
```

## 处理二

见上。`AddTable` 就此成功。

---

## 现象三：`t.SetCellTextString(r, c, "设备表")` 报 `ValueError`

```
ValueError: invalid literal for int() with base 10: '设备表'
```

## 根因三

这个 COM 绑定里 `SetTextString` 的签名**不是** `(row, col, text)`。写成这样
时 pywin32 把字符串往后塞进了某个整型参数位。真正可用的方法是：

| 目的 | 方法 | 签名 |
|---|---|---|
| 写单元格文字 | `SetText` | `(row, col, text)` |
| 设单元格字高 | `SetCellTextHeight` | `(row, col, height)` |
| 设单元格对齐 | `SetCellAlignment` | `(row, col, code)`，5 = acMiddleCenter |
| 设单元格样式 | `SetCellTextStyle` | `(row, col, style_name)` |

注意 `SetTextHeight` / `SetAlignment` / `SetTextStyle`（**不带 `Cell`**）是
**对 content 操作**的，只吃 1–2 个参数，传 3 个会 `TypeError`。

`SetCellTextStyle(r, c, "CN")` 还会报「未找到主键」——样式必须**在该文档里存在**。
我们的 DXF 里有 `CN`，复制成临时副本后一起带过去了，所以成功；在
`documents.Add()` 新建的空白图里调用就会失败。

---

## 现象四：COM 返回 `RPC_E_CALL_REJECTED`，反复失败

```
com_error: (-2147418111, '被呼叫方拒绝接收呼叫。', None, None)
```

`Documents.Count` 都读不到，但进程活着、窗口标题是 `[开始]`、没有 `*`
（没有未保存文档）。

## 根因四

AutoCAD 忙（重生成、出图、用户正在命令中途）时会**立即拒绝** COM 调用，而不是排队。
这不是连接断了——同样的调用等一会儿就成功。pywin32 这个版本**没有**
`pythoncom.CoRegisterMessageFilter`（`AttributeError`），所以标准解法（注册消息
过滤器让 COM 自动重试）用不了。

## 处理四

自己退避重试。实测两次 1.5 s 等待就恢复：

```python
for _ in range(COM_RETRIES):
    try:
        return fn(*args)
    except Exception as exc:
        if getattr(exc, "hresult", None) != -2147418111:
            raise                 # 别的错误是真答案，立刻抛
        time.sleep(1.5)
```

**只重试 `RPC_E_CALL_REJECTED`**，其他错误立即抛——否则一次明确失败会被拖成
一次慢失败。

这条已进 `tools/text_overlap/dwg.py::_call`，`documents.Open` / `SaveAs` /
`Close` / `Activate` 全部走它。

---

## 现象五：重启 AutoCAD 每次都弹「无法找到图形文件」

```
acad.exe /automation "D:/.../Drawing9.dwg"
→ AutoCAD 弹框：无法找到图形文件
```

## 根因五

**`/automation` 不是 AutoCAD 2026 的命令行开关。** AutoCAD 把它当成一个要打开的
**图形文件名**逐字解析，自然找不到。每重启一次就弹一次，而且标题栏停在 `[开始]`。

这是我自己编的开关，不是 AutoCAD 的问题。

顺带确认：**用命令行启动 AutoCAD 不能可靠地拿到 COM**。这类启动下 AutoCAD 不注册
到 Running Object Table，`GetActiveObject` 拿到的对象读 `Documents.Count` 会报
`AttributeError: <unknown>.Count`，或 `MK_E_UNAVAILABLE (-2147221021)`，一直不通。

## 处理五

**让 COM 自己启动 AutoCAD，命令行不传任何路径：**

```python
app = win32com.client.Dispatch("AutoCAD.Application")   # 立刻可用
app.Documents.Count                                      # 第 1 次就绪
```

`Dispatch` 在实例不存在时会启动它，并保证 ROT 注册正确。要传文件就在启动后
用 `app.Documents.Open(path, True)` 打开，不要塞在命令行里。

> `dwg.py` 里用 `GetActiveObject` 而不是 `Dispatch` 是对的（避免再起一个用户看不见
> 的实例），但前提是**AutoCAD 是由 COM 或正常方式启动的**。诊断顺序：
> ① 窗口标题有没有 `*`、② 有没有模态对话框（`图形修复`、许可）、③ ROT 里有没有条目。

---

## 预防

1. **递归子程序必须有递归形状的夹具。** 一层嵌套的测试对递归 bug 是免疫的，
   因为最外层那次调用永远是对的。`drawing9.py` 特意嵌了两层。
2. **`str(None)` 是 `'None'`，不是空串。** 任何「取 handle 再转字符串」的地方
   都要先判 None。写进报告的值尤其危险——它看起来像一个真参考号。
3. **COM 的两个反复出现的坑**已汇总：插入点/移动点要 VARIANT 数组、AutoCAD 忙要
   自己退避重试。两条都在 AGENTS.md 第 10 节留了行。
4. 表格单元格方法名按上表记：写内容用 `SetText`，设属性用 `SetCell*`。
5. **不要给 `acad.exe` 编命令行开关。** 启动 AutoCAD 用 COM `Dispatch`；
   命令行传路径的启动方式拿不到可靠 COM。

---

## 更新说明

- 2026-11-21 建立。四条现象里第一条是**检查器的真缺陷**（`via='None'` 让发现
  无法执行），后三条是 COM 参数与重试问题，属工具链而非检查逻辑。
- 这个缺陷是**画新图**逼出来的，不是读代码读出来的。`drawing8` → `drawing9`
  的增量价值就在这里：换一种藏法，就暴露出只对一种藏法成立的那个假设。