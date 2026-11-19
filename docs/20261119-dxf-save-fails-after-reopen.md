# DXF 文档「关闭后重开」保存必失败（`0x80210063`），DWG 正常

> 记录日期：2026-11-19
> 环境：AutoCAD 2026 (`25.1s`)、pywin32、`autocad-mcp-pro` 1.8.0
> 相关文档：[`20261119-system-status-stale-proxy-p0.md`](20261119-system-status-stale-proxy-p0.md)、[`20261120-dwg-saveas-repoint.md`](20261120-dwg-saveas-repoint.md)

## 现象

对一个 **DXF** 文档：SaveAs 保存 → 关闭 → 重新打开 → 改图 → `Save()` 必失败，每次都一样：

```text
(-2147352567, '发生意外。', (0, 'AutoCAD', '保存文档时出错',
 'D:\\autocad_26\\AutoCAD 2026\\HELP\\OLE_ERR.CHM', -2145320861, -2145320861), None)
```

`drawing_save` 报的就是这个（它走 `doc.Save()`）：

```text
Internal error: Error calling tool 'drawing_save': AutoCAD COM error
(-0x7ffdfff7): 发生意外。 (保存文档时出错)
```

`Measurement`/`TextOverride` 之外，`-2145320861` = **`0x80210063`**：
facility 33（AutoCAD 自己的错误设施）、code 99。项目此前未记录这个码。

## 根因

**不是** MCP 的 bug，也不是文件锁、路径、权限或 `ISAVEPERCENT` —— 逐项排除过。
是 AutoCAD 2026 对 **DXF 格式**文档保存路径的行为缺陷；DWG 完全正常。

### 精确规律（2026-11-19 二次核定，8 用例矩阵）

初版结论写作"任意已存在的 DXF 都失败"——**这个说法过宽，已修正**。
真实约束是**文档打开时所在的那个路径**，不是扩展名本身：

| # | 文档经历的路径 | `Save()` | 落盘 |
|---|---|---|---|
| C1 | `Add()` → `SaveAs(a.dxf,61)` → 改 → `Save()` | ✅ | 写入 |
| C2 | `SaveAs(a.dxf)` → **关闭** → `Open(a.dxf)` → 改 → `Save()` | ❌ `0x80210063` | 未变 |
| C3 | 复制 → `Open(a.dxf)` → 改 → `Save()` | ❌ `0x80210063` | 未变 |
| C4 | 复制 → `Open(a.dxf)` → 改 → `SaveAs(a.dxf)`（同路径） | ❌ `0x80210063` | 未变 |
| C5 | 复制 → `Open(a.dxf)` → 改 → `SaveAs(b.dxf)`（**新路径**） | ✅ | 写入 |
| C6 | 复制 → `Open(a.dwg)` → 改 → `Save()` | ✅ | 写入 |
| C7 | `Add()` → `SaveAs(a.dwg,64)` → 改 → `Save()` | ✅ | 写入 |
| C8 | 复制 → `Open(a.dxf)` → `SaveAs(b.dxf)` → 改 → `Save()` | ✅ | 写入 |

> **规律：DXF 只能保存到「本次会话里由 `SaveAs` 新获得的路径」。
> 文档 `Open` 进来的那个路径写不了，`Save()` 和 `SaveAs(同路径)` 都不行。**

这解释了为什么 `draw_test/` 里那么多 DXF 是"保存成功"的——它们由 ezdxf 无头生成，
或由 `SaveAs` 写到新路径，都不是"打开旧 DXF 再覆盖写"。

### 救援的有效期：仅限本次会话

`SaveAs` 到新名字能救这个文档**直到关闭**；重开后缺陷回归，要再 `SaveAs` 一次。
实测（`scripts/save_rescue_lifetime.py`）：

```text
D0  Open(已有 DXF) -> 改 -> Save()          FAIL  0x80210063
D1  SaveAs(新名字) -> 改 -> Save()          OK
    再 Save() 一次                           OK
D2  重开那个被救过的文件 -> 改 -> Save()    FAIL  0x80210063   ← 回归
D3  再 SaveAs(又一个新名字) -> Save()       OK
```

所以"另存为新名字"是**每次会话都要重做的动作**，不是一次性修复。

### 旧矩阵（2026-11-19 首次记录，部分行结论已被上表细化）

| 场景 | 结果 |
|---|---|
| DXF：新建 → SaveAs → **不关闭** → 改 → Save | ✅ 成功 |
| DXF：SaveAs → **关闭** → 重开 → 改 → Save | ❌ `0x80210063` |
| DXF：SaveAs → **关闭** → 重开 → 改 → SaveAs(同一路径) | ❌ `0x80210063` |
| DXF：已存在的文件 → 打开 → 改 → Save | ❌ **全部失败**（试了 3 个不同来源的 DXF） |
| DWG：SaveAs → 关闭 → 重开 → 改 → Save | ✅ 成功 |
| DXF 在项目目录 / TEMP 目录 | ❌ 都失败 |
| DWG 在项目目录 / TEMP 目录 | ✅ 都成功 |
| DXF：`ISAVEPERCENT=0`（强制全量保存）后 Save | ❌ 仍失败 |
| DWG SaveAs 到新路径 | ✅ 成功 |

### 一个容易误判的细节

`SaveAs` 会让文档改指向，但 **AutoCAD 不释放原文件的句柄**。实测：文档从
`a.dxf` SaveAs 到 `b.dxf` 后，磁盘上 `a.dxf` 仍被独占锁定，直到关闭整个文档才释放。
所以"`SaveAs` 到新路径 → 再 `SaveAs` 回原路径"也会失败。

这解释了为什么会出现 `0x80210063`：AutoCAD 要覆盖写一个它自己仍持有独占句柄的文件。

**另一条同样后果的路径**：`Documents.Open(path, True)` 的第二个参数是 `ReadOnly`。
传 `True` 会只读打开，之后 `Save()` 报的错误与本问题**完全同码**（`0x80210063`），
但根因只是自己设的只读标志。做对照实验时必须传 `False` 并回读 `doc.ReadOnly` 确认，
否则会把"我开的只读"记成"AutoCAD 的缺陷"。

已排除的假设：
- 不是文件被别处占用（`open(p,'r+b')` 成功，无 `.dwl`/`.dwl2`）
- 不是权限/只读（`doc.ReadOnly = False`，文件属性可写）
- 不是磁盘空间（D: 剩 24 G）
- 不是 `ISAVEPERCENT` 增量保存（设为 0 仍失败）
- 不是 ezdxf 生成文件的问题（AutoCAD 自建的 DXF、项目里既有的 3 个 DXF 同样失败）
- 不是模态对话框阻塞（`#32770` 存在但都不可见）
- 不是路径问题（TEMP 目录同样失败）

## 处理

### MCP 侧已补偿（2026-11-19，`b874e25`）

`drawing_save()` 现在遇到这个失败会**自动降级为往返保存**，调用方无感：

```text
1. SaveAs 到同目录的临时文件
2. 关闭文档（这一步才真正释放原文件的句柄）
3. 把临时文件复制到目标路径
4. 重新打开目标文件，重新绑定会话
```

返回里多一个字段说明走了降级：

```json
"save_fallback": {
  "reason": "dxf_in_place_save_unsupported",
  "error": "AutoCAD COM error (-0x7ffdfff7): 发生意外。 (保存文档时出错)",
  "method": "saveas_temp_close_copy_reopen"
}
```

实测（AutoCAD 2026）：

| 验证 | 结果 |
|---|---|
| 单次：1078 实体的 DXF → 加圆 → `drawing_save()` | ✅ 1078 → 1079，新圆在磁盘上 |
| 连续 5 次保存 | ✅ 1083 实体，5 个测试圆全在 |
| 保存后会话状态 | ✅ `connected=True`，仍绑定同一个文档 |

判据 `_is_dxf_save_failure()` 故意收窄：必须**同时**满足「有保存字样」和
「是那两个 HRESULT 之一」，且**连接丢失永不匹配**。这样真正因为别的原因失败的保存
（只读目录等）仍会如实报给调用方，不会被误当成本问题重试。

### 仍然不建议的做法

虽然现在能保存了，往返保存比直接 Save 慢（关闭 + 复制 + 重开三步）。所以：

- **DWG 仍是首选工作文件**，可反复 `Save()`，无额外开销
- DXF 用来交付/交换；要迭代就接受往返开销，或写新路径

### ⚠️ 在 AutoCAD 界面里按 Ctrl+S 仍然会失败

**MCP 的补偿只在 `drawing_save()` 里。你人在 AutoCAD 里按 Ctrl+S 走的是
`Document.Save()`，不经过 MCP，所以照样失败。** 2026-11-19 实测复现：

```python
doc = app.ActiveDocument            # D:\\...\\draw_test\\multi_save.dxf
doc.Saved, doc.ReadOnly
# -> True, False                   （文件不脏、非只读，条件都满足）
doc.Save()                          # 与 Ctrl+S 完全同一个调用
```

```text
hresult : -2147352567 (DISP_E_EXCEPTION)
strerror: '发生意外。'
excepinfo: (0, 'AutoCAD', '保存文档时出错',
            'D:\\autocad_26\\AutoCAD 2026\\HELP\\OLE_ERR.CHM',
            -2145320861, -2145320861)     <- 0x80210063
```

同一会话、同一时刻的 DWG 对照实验（复制件、`Documents.Open(copy, False)`）：

```text
entities: 1078 -> 1079
Save() -> SUCCEEDED, Saved = True
原件 sha256 前后一致 -> True     （未被动过）
```

**结论：这是文件格式层面的差别，不是 MCP 的、也不是会话状态的。**
DXF 在 AutoCAD 界面里就是存不了，DWG 可以。

给使用者的实操建议：

| 你在做什么 | 怎么办 |
|---|---|
| 迭代画图 | **用 DWG 当工作文件**，Ctrl+S 随时可用 |
| 手上是 DXF 且必须保内容 | 用 `drawing_save()`（MCP 会走往返降级），**别按 Ctrl+S** |
| 手上是 DXF，想 Ctrl+S | 另存为新文件名（`SaveAs` 到新路径可以成功），或先转 DWG |
| 想让 DXF 这次会话能反复 Ctrl+S | 先 `SaveAs` 到一个新名字，之后的 `Save()` 就是直写 |

> 判断"我的改动到底存没存"：看 `drawing_info` 的 `saved` 字段，别只看标题栏的 `*`。
> `saved: false` + 标题带 `*` = 改动只在内存里。本例中 `multi_save.dxf` 就是
> 1083 个实体全在内存、磁盘还是旧的。

### 手动绕法（不经 MCP 时）

如果直接用 COM 脚本操作 DXF，按下面选：

```python
# ❌ 打开已存在的 DXF 后，这两个都失败
doc.Save()
doc.SaveAs(同上路径, 61)

# ✅ 写出到一个新路径（不改指向就不会踩锁）—— 之后本会话可反复 Save()
doc.SaveAs(new_path, 61)
doc.Save()            # ✅ 同一个文档，新路径，直接写

# ✅ 或必须回原文件名时：用和 MCP 一样的往返法
doc.SaveAs(tmp, 61); doc.Close(False); shutil.move(tmp, target)
doc = app.Documents.Open(target, False)   # 重开后 Save() 又会失败，属预期

# ⚠️ 这个"救援"只活到关闭为止
#    D2 实测：重开被救过的文件 -> Save() 又失败；要再 SaveAs 一次
```

⚠️ **绝不要用 `Close(True)` 当保存手段**——实测它不报错但**静默丢弃改动**
（1078 实体进，1078 实体出，新加的圆没了）。这比报错危险得多。

## 预防

1. **`drawing_save()` 现在能保存 DXF 了**（往返降级），但返回里会带
   `save_fallback` —— 看到它就知道走了三步往返，不是直接保存。
   每次都走降级，因为往返后文档又指向原路径，下一次 `Save()` 同样会失败。**更省事的做法是先 `drawing_save_as` 换个新路径**，之后 `drawing_save` 就是直写。
2. **工作文件优先用 DWG**：可反复 `Save()`，没有往返开销。
3. **千万别把 `Close(True)` 当保存手段**：它不报错但静默丢改动。
   这是本项目里最危险的一个假象，实测 1078 实体进、1078 实体出、新加的圆消失。
4. **`SaveAs` 改指向后原文件句柄不会立即释放**，要关闭文档才放。
   这也是 [`20261120-dwg-saveas-repoint.md`](20261120-dwg-saveas-repoint.md) 里
   "绝不 SaveAs 不是自己打开的文档"那条规矩的物理原因。
5. **在 AutoCAD 界面里对 DXF 按 Ctrl+S 仍会失败**（2026-11-19 实测确认）。
   MCP 的往返降级只覆盖 `drawing_save()`；**人工 Ctrl+S 不经过 MCP**。
   工作文件用 DWG，或改用 `drawing_save()` 保存 DXF。
6. **`Documents.Open(path, True)` 的第二个参数是 `ReadOnly`**。传 `True` 会以只读
   打开，之后 `Save()` 报的错误和本问题的 `0x80210063` **一模一样**，极易误判。
   做对照实验时务必传 `False` 并回读 `doc.ReadOnly` 确认。
7. 附带一条：**`doc.SendCommand("_.QSAVE\n")` 会卡死 COM 线程**（本机实测卡 >120s，
   ESC 也解不开，只能重启 AutoCAD）。保存只用 ActiveX 的 `Save`/`SaveAs`，不要用命令。

## 更新说明

- 2026-11-19 首次记录。发现于「绑定与关闭功能测试」，与 P0 死代理无关，是独立问题。
- 2026-11-19 修正归因：初判为"关闭后重开"特有，实测**任意已存在的 DXF** 都失败；
  并查明 `SaveAs` 改指向后原文件句柄不释放是 `0x80210063` 的物理原因。
- 2026-11-19 **MCP 侧已补偿**（`b874e25` 合并 main）：`drawing_save()` 自动走
  「存临时 → 关闭 → 复制 → 重开」往返，实测单次与连续 5 次均成功，内容无丢失。
  新增 9 个回归测试。
- 2026-11-19 **补充确认：人工 Ctrl+S 仍失败**。在同一 AutoCAD 会话里实测
  `Document.Save()` → `0x80210063`，而同一时刻的 DWG 副本 `Save()` 成功。
  MCP 的补偿只在 `drawing_save()` 内，不覆盖界面操作。另记一个易误判点：
  `Documents.Open(path, True)` 是只读打开，其保存失败错误与本问题**完全同码**。
- 2026-11-19 **二次核定，修正过宽论断**。初版写"任意已存在的 DXF 都失败"，
  经 8 用例矩阵（`scripts/save_matrix.py`）收窄为：**DXF 只能保存到本次会话里
  由 `SaveAs` 新获得的路径**；`Open` 进来的那个路径写不了。C5/C8 证明
  `SaveAs(新路径)` 成功且之后可反复 `Save()`（这解释了 `draw_test/` 里为何有
  大量保存成功的 DXF——它们是 ezdxf 无头生成或 `SaveAs` 到新路径的）。
  另测出**救援有效期**（`scripts/save_rescue_lifetime.py`）：D2 重开被救过的文件后
  `Save()` 又失败，需再 `SaveAs` 一次。技能已新增
  `references/saving-formats.md` 承载完整矩阵与两种格式的正确代码。