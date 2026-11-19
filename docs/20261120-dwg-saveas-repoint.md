# DWG 读不了，以及 `SaveAs` 把用户的文档改指向

> 记录日期：2026-11-20
> 环境：Windows，AutoCAD 2026 `25.1s (LMS Tech)`，`D:\autocad_26\AutoCAD 2026\`
> 输入：`draw_test/overlap_proto/Drawing8.dwg`

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 使用指南（第 10 节排错、第 11 节记录制度）
> - [`20261117-autocad-troubleshooting.md`](20261117-autocad-troubleshooting.md) — 问题索引
> - [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) — 检查工具本体
> - [`../tools/text_overlap/README.md`](../tools/text_overlap/README.md) — 工具用法

---

## 背景

用户看图后提出：**「配电柜 PD-1 和 PD-2 的文字肉眼明显重叠，为什么没被抓出来？」**

这条重叠确实存在，而且检查器**抓到了**——它是 `Drawing8` 报告的第 1 条：

```
1. text_text at (4000, 8925)
   CB [A-TEXT] 配电柜 PD-2 [style CN]
   crosses CA [A-TEXT] text 配电柜 PD-1 [style CN]
   overlap 56% of the smaller box
   fix: entity_move(handle='CB', dx=0.0, dy=-241.308)
```

阈值 `TEXT_TEXT_MIN_RATIO = 0.15`，56% 是它的近 4 倍。判定逻辑没有漏。

真正的问题有两层，本文各记一条。

---

## 现象一：指向 `.dwg` 时工具什么都不查

```bash
python -m tools.text_overlap Drawing8.dwg
# error: Drawing8.dwg is a DWG, which this check cannot read. Save it as DXF first...
# 退出码 2
```

用户手上的图绝大多数是 DWG。工具对最常见的情况直接退出，只给一句
「转成 DXF 再来」。CLI 上确实是这么写的（`SKILL.md` 里也写着「DXF only」），
但**结果是：用户拿自己真正关心的那张图去跑，看到的是一个错误页，而不是发现列表。**
「是不是漏掉了这个场景」的怀疑，源头就在这里。

## 根因一

检查本身是纯 ezdxf，不需要 AutoCAD。但 DWG 不是 DXF，本机两条离线路都不通：

| 路线 | 状态 | 证据 |
|---|---|---|
| ODA File Converter（ezdxf `odafc` 唯一通道） | **未安装** | `odafc` 需要外部 exe |
| `accoreconsole.exe` | **不可用** | 带 `/s` 卡在 `命令:` 提示符，`timeout` 退出 124，输出「AutoCAD 许可证无效或未安装」 |

唯一可行的是**运行中的 AutoCAD**，走 COM。工具原本没有接这条路。

## 处理一

新增 `tools/text_overlap/dwg.py`，`detect()` 之前先把 DWG 转成临时 DXF：

```python
app = win32com.client.GetActiveObject("AutoCAD.Application")   # 不 Dispatch
document.SaveAs(dxf_out, 61)                                    # 61 = ac2013_dxf
```

用 `GetActiveObject` 而不是 `Dispatch`：`Dispatch` 会**再起一个** AutoCAD，
检查跑在用户看不见的进程里，而真正卡死的那个实例依然卡着。

AutoCAD 没开时给的是**出路**，不是纯错误：

```
error: cannot read X.dwg as a DWG.
  AutoCAD is not running (or its COM automation server is not responding: ...).
  do this: Start AutoCAD and open the drawing, or save a DXF first (SaveAs with
  AcSaveAsType 61). If AutoCAD *is* running, press ESC in it: a wedged modal
  state makes COM refuse every call while the process stays alive.
```

`--no-com` 可显式禁止碰 AutoCAD。

---

## 现象二（更严重）：`SaveAs` 把用户的文档改指向

第一版实现里，如果 DWG 已经在 AutoCAD 中打开，代码会复用那个文档，然后对它
`SaveAs` 到临时 DXF。跑完发现：

```
ActiveDocument.Name = tc_dwg_ij_admuf.dxf
FullName           = C:\Users\drago\AppData\Local\Temp\tc_dwg_ij_admuf.dxf
Documents.Count    = 1
```

磁盘上的 `Drawing8.dwg` 完好（MD5 `c08a5345…` 前后一致），但**用户的会话里那个
文档已经不再指向 DWG 了**。而工具随后把临时文件删掉，于是 AutoCAD 挂着一个
**已不存在的路径**。

后果不是「这一次错了」：用户下一次 `SAVE` 会写到 `%TEMP%`，而标题栏显示的是
一个随机名字。这种损坏**不会报错**，只会在某天发现「图纸丢了」时才发现。

## 根因二

`SaveAs` 的语义是 **「这个文档现在就是那个文件」**，不是「导出一份副本」。
作用在别人的文档上，就等于把别人的文档挪走。

原代码有两个错误叠加：

1. 复用了用户已打开的文档（`Documents.Open` 在路径已打开时可能返回既有文档，
   或者后续 `SaveAs` 作用到了错误的文档上）；
2. 用「这个文件是不是已经打开了」来决定是否关闭，而不是**验证自己操作的是哪个文档**。

## 处理二

改成**只对副本操作**，并且保存前做一次身份核对：

```python
workdir  = tempfile.mkdtemp(prefix="tc_dwg_")
dwg_copy = os.path.join(workdir, f"{stem}.dwg")
shutil.copy2(path, dwg_copy)          # ① 复制，不碰原件

document = app.Documents.Open(dwg_copy, True)   # ② 只打开副本

if not _same_file(document.FullName, dwg_copy):  # ③ 身份核对
    document.Close(False)
    raise DwgUnavailable("AutoCAD opened a different file than the temporary copy", ...)

document.SaveAs(dxf_out, AC2013_DXF)             # ④ 只可能作用在副本上
finally:
    document.Close(False)                        # ⑤ 无论成败，只关副本
```

五条保障合起来：用户开的文档**不保存、不关闭、不被改指向**。

验证方式是哈希比对，不是「看起来没事」：

```
转换前：Drawing8.dwg  c08a534544c4a486c5bcc333db4f2f63
转换后：Drawing8.dwg  c08a534544c4a486c5bcc333db4f2f63   ← 一致
转换后 AutoCAD 文档数 = 0                                ← 没留下任何文档
临时目录 tc_dwg_* 残留 = 无
```

## 预防

1. **绝不 `SaveAs` 不是自己打开的文档。** 这条已写进
   `skills/.../references/pitfalls.md` 第 21 条。
2. 新增回归测试 `test_dwg_conversion_never_touches_open_documents`：用假 app
   记录每一次 `SaveAs` 的目标，断言只对副本生效、关闭时传 `False`。
   **不需要真 AutoCAD**，所以每次跑测试都会检查。
3. 另一条 `test_dwg_without_autocad_explains_the_way_out` 守住「错误必须带出路」。
4. 判断「有没有动到用户的东西」用**哈希**，不要用「看起来正常」。会话被改指向
   这件事在磁盘上完全看不出来。

---

## 顺带修正的文档计数

`SKILL.md`、`references/layout.md`、`references/verification.md` 里写的是
「six checks」「24 functions / 60 assertions」「33 functions / 100 assertions」，
实际已是 **七个检查、35 个测试函数、106 条断言**。三处一并改正，并在
`layout.md` 的文件树里补上 `dwg.py`。

---

## 更新说明

- 2026-11-20 建立。两条现象各有独立根因：一条是能力缺口（DWG 读不了），
  一条是**破坏性副作用**（`SaveAs` 改指向），后者严重得多。
- 用户最初的疑问「56% 重叠没被抓出来」经复核**不成立**：它是报告第 1 条。
  真正需要修的是「用户拿 DWG 去问，得到的是一个错误页」。