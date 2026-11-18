# 画图问题记录索引

> 记录日期：2026-11-17
> 用途：画图过程中遇到的问题与解法总索引。**每次遇到值得记录的问题，都在这里登记一行。**

> **相关文档**
> - [`../AGENTS.md`](../AGENTS.md) — 使用指南（第 11 节为记录制度）
> - [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) — 部署与实测记录

---

## 记录规则速查

| 项 | 规定 |
|---|---|
| 命名 | `yyyymmdd-<简短英文名>.md`，日期用**遇到问题当天** |
| 位置 | `docs/` |
| 格式 | 标题 + 记录日期/环境 + 相关文档块 + 编号章节 + 文末更新说明 |
| 必含 | **现象**（报错原文）/ **根因**（定位证据）/ **处理**（含无效尝试）/ **预防** |
| 登记 | 追加到下方表格；可复用结论同步进 `AGENTS.md` 第 10 节 |

判断是否值得记录：**下次遇到同样情况，这份记录能让我少走十分钟弯路吗？**

---

## 已记录问题

| 日期 | 文件 | 问题摘要 | 状态 |
|---|---|---|---|
| 2026-11-17 | [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) | 部署全流程与 4 个坑：目录改名致 COM `REGDB_E_CLASSNOTREG`、`cad_batch` 键名 `args`、工具名按类型拆分、`ACCORECONSOLE_PATH` 必设 | ✅ 已解决 |
| 2026-11-17 | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 无头 ezdxf 与 COM 直连的选型：COM 单次改图 0.2–3 s 而超时要等 60 s，无头 6–70 ms；无头**写不了 DWG**（需 accoreconsole 转）；`arch_rooms_detect` 无头返回空 | ✅ 已解决（含选型判据） |
| 2026-11-17 | [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) | MCP 反复断开的根因：重连判据漏掉 `0x800706BA`/`0x80010108` 导致死代理被永久缓存；60 s 超时后作业仍在 AutoCAD 里跑；两个会话抢同一 AutoCAD。含杀进程恢复手法与 `COM_CALL_TIMEOUT=180` 配置 | ✅ 已修复，上游 [PR #26](https://github.com/U-C4N/Autocad-MCP/pull/26)；衍生问题 [#27](https://github.com/U-C4N/Autocad-MCP/issues/27) [#28](https://github.com/U-C4N/Autocad-MCP/issues/28) |
| 2026-11-17 | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 中文与特殊符号（`m²`、`Ø`、`±`、`°`）「能存不能看」：数据码点完全正确但屏幕空白/缺失，根因是默认 `Standard` 样式的 `txt.shx` 无这些字形。解法 `textstyle_create(font="simsun.ttc")` 并指定 `StyleName` | ✅ 已解决（含字体清单与 SHX 转义陷阱） |
| 2026-11-17 | [`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md) | 表格单元格文字偏上：`AddTable` 默认顶部对齐，创建时未调 `SetCellAlignment`。已修源码补 `SetCellAlignment(r,c,5)`。另含行高被字高撑大、表格锚点左上角、`InsertionPoint` 只读等坑 | ✅ 已修源码 + 已有表补正 |
| 2026-11-18 | [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md) | LISP 写层默认被禁：1.8.0 `LISP_POLICY=read` 只放行只读调用，`vla-put-*` 全被拒；开关为 `LISP_POLICY=off` / `DANGEROUS_COMMANDS_ENABLED=true`。表格单元格中文空白的真因是 `style=None` 回退 `Standard`(txt.shx)，**数据其实写入正常**。含 ActiveX `GetTextString` 3 参数陷阱、`(command "_.TABLE")` 卡死 COM 线程 | ✅ 已解决（含表格中文正确方案） |
| 2026-11-18 | [`20261118-door-drawing.md`](20261118-door-drawing.md) | 建筑门画法：门洞是墙的真实开口，墙体必须**分段绘制**并在门洞处留空画封口线；门扇 LINE 从铰点起、1/4 ARC **圆心=铰点**。参照 `123.dwg` 的 `A-DOOR-E-N` 图层实测画法，含双开门做法与几何验证断言 | ✅ 已解决 |
| 2026-11-18 | [`20261118-chinese-text-dwg-fix.md`](20261118-chinese-text-dwg-fix.md) | 中文在 DWG 中乱码的完整修复：「数据对、码点对、样式对、显示却错」。根因 `txt.shx` 无 CJK 字形（静默失败）+ DXF `$DWGCODEPAGE=ANSI_1252` 与 UTF-8 实际不符。含三层验证法，以及**最大陷阱：`view_screenshot(region=)` 走 `Document.Export` 快照渲染器会丢弃文字，判断中文显示只认真实窗口截图** | ✅ 已解决 |
| 2026-11-18 | [`20261118-pdf-plot-fixes.md`](20261118-pdf-plot-fixes.md) | PDF 出图三大坑（三个独立根因）：①中文乱码 = `.ttc` 集合字体无法嵌入 PDF，字形被炸成线条；②版面裁切 = A1 可打印区仅 831×560 而图框按 841×594；③`PlotType`/`PlotRotation` 枚举用错（**0=横向**）导致内容只画到 698mm。最终方案：**图纸空间满幅视口 + `plot_area="layout"` + `scale="1:1"`** | ✅ 已解决 |
| 2026-11-18 | [`20261118-lisp-stale-result.md`](20261118-lisp-stale-result.md) | **`system_run_lisp` 返回值不可靠**：表达式出错时返回**上一次调用**的结果，验证会莫名"通过"。根因 `USERS1` 是跨调用持久变量，LISP 出错中止 form 使最外层 `setvar` 未执行。含三步闭环实验。**已修上游源码**（哨兵 + `vl-catch-all-apply`，新增 `LispRuntimeError`/`LispNotExecutedError`，4 个回归测试），上游 [PR #29](https://github.com/U-C4N/Autocad-MCP/pull/29) | ✅ 已修复并提交上游 |
| 2026-11-18 | [`20261118-table-cell-cjk-and-alignment.md`](20261118-table-cell-cjk-and-alignment.md) | **原生 TABLE 两处缺陷**：①单元格默认顶部对齐（实测偏 600 = 半行高）；②**单元格不跟随 `AcDbText.StyleName`，走 `SetCellTextStyle`**，`AddTable` 全放 `Standard`(txt.shx) 使中文与 `m²`/`Ø` 画成空白。MCP 已改为检测非 ASCII 自动指向 CJK 样式（复用或建 `MCP-CJK`），ASCII 表行为不变、无字体时仅警告不失败。含几何级居中验证（11 格偏差 +0.0）。上游 [PR #30](https://github.com/U-C4N/Autocad-MCP/pull/30) | ✅ 已修复并提交上游 |
| 2026-11-18 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | **文字交叠检查**：ezdxf 能做，但**不能用自带 bbox**——组码 41=0 表示「不换行」，ezdxf 传成宽度 0 给 `text_wrap` 导致每个词切一行，框大出 6.8 倍。另 7 个坑：AutoCAD 返回**字形墨迹框**而非 advance 宽、字体**全路径名**让 ezdxf 静默退化 33%、`total_height`/`baseline` 在部分字体退化、行距是 **5/3 字高**、attachment 7-9 方向相反、字体宽度需按字体标定 2.89%、msyh 无法标定。产物 `tools/text_overlap/` + `skills/autocad-text-overlap-check/`，三项验收通过：干净图 0 误报 / 植入 6 类全检出 / 9 对齐点 ≤2.89 单位；310 个真实 MTEXT 中 89%≤3%、97%≤5% | ✅ 已实现并验收 |

| 2026-11-19 | [`20261119-printwindow-com-wedge.md`](20261119-printwindow-com-wedge.md) | **`PrintWindow` 截图把 AutoCAD COM 搞卡死**：GPU 合成导致截图全白，更致命的是 `WM_PRINT` 同步重绘请求打乱 AutoCAD 渲染线程 → COM 自动化服务器不可用（`<unknown>.Count`、`RPC_E_CALL_REJECTED`、`MK_E_UNAVAILABLE`），但进程还活着。`RPC_E_CALL_REJECTED` 的提示「等在命令提示符」有误导性，按 ESC 才有效。含**杀进程前如何用窗口标题 `*` 判断未保存文档**（COM 已失效时唯一可用手段）、`accoreconsole` 本机确认不可用、以及「让用户自己看图比自己造渲染可靠」的教训 | ✅ 已解决（按 ESC 恢复） |

---

## 按症状检索

| 症状 | 文件 | 章节 |
|---|---|---|
| **`PrintWindow` 截图全白，随后 COM 全部失效** | [`20261119-printwindow-com-wedge.md`](20261119-printwindow-com-wedge.md) | 现象一/二/三、处理 1 |
| **COM 报 `<unknown>.Count` 或 `MK_E_UNAVAILABLE`（操作无法使用）** | [`20261119-printwindow-com-wedge.md`](20261119-printwindow-com-wedge.md) | 根因、处理 1 |
| **想 `taskkill` 但怕丢未保存文档** | [`20261119-printwindow-com-wedge.md`](20261119-printwindow-com-wedge.md) | 处理「杀进程前必须确认」 |
| `accoreconsole` 带 `/s` 卡住 `exit=124`、提示「许可证无效」 | [`20261119-printwindow-com-wedge.md`](20261119-printwindow-com-wedge.md) | 预防 5 |
| COM 报 `-2147221164` / `REGDB_E_CLASSNOTREG` | [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) | 4.3 坑 1 |
| `cad_batch` 报 `unexpected key(s) ['arguments']` | [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) | 4.3 坑 2 |
| `describe_tool` 报 `Unknown tool: 'entity_create'` | [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) | 4.3 坑 3 |
| 无头打不开 DWG（`dwg_read` 能力拒绝） | [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) | 4.3 坑 4 |
| 无头写 DWG 被拒（`ezdxf ... cannot write DWG`） | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 1 现象 B / 3.1 转 DWG 流程 |
| COM 调用慢、超时 60 s、`(busy)` / `已为另一线程整理的接口` | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 2.1 / 2.2 / 3.2 选型判据 |
| AutoCAD 重启后仍报 `RPC 服务器不可用 (-2147023174)` | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 3.3 无效尝试第 4 行 |
| `arch_rooms_detect` 返回 `rooms: []` | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 1 现象 C / 2.3 能力边界 |
| `saveas.scr` 路径里 `\t` 被转义、DWG「只读未覆盖」、`.dwl` 占用 | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 3.3 无效尝试第 1–3 行 |
| 渲染预览报 `No module named 'ezdxf'` | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 3.3 无效尝试第 5 行 |
| `predicate` 选择器写 `lwpolyline`/`text` 被拒 | [`20261117-headless-vs-com.md`](20261117-headless-vs-com.md) | 3.3 无效尝试第 7 行 |
| 工具报 `No such tool available: ... server 'autocad' has disconnected` | [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) | 1 现象 C / 3.1 杀进程 + `/mcp` 重连 |
| `RPC 服务器不可用 (-0x7ff8f946)`，重启 AutoCAD 也无效 | [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) | 2.2 死代理被缓存 |
| `AutoCAD refused the lookup of 'Count' (busy)` | [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) | 2.3 超时后作业仍在跑 |
| `应用程序调用一个已为另一线程整理的接口 (-0x7ffefef2)` | [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) | 2.2 / 2.3 |
| 一晚出现大量重复绘图文档、服务实例数暴涨 | [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) | 2.1 / 2.4 两会话争抢 |
| 想知道 MCP 历史上错在哪 | [`20261117-mcp-disconnect.md`](20261117-mcp-disconnect.md) | 5 一条命令速查（journal 查询） |
| 中文写进去了但屏幕上看不见 | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 1 现象 B / 2 根因 / 3.1 建中文字体样式 |
| **面积 `m²` 只显示成 `m`** | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 3.4 上标／特殊符号同一根因 |
| `Ø`、`±`、`°`、`≤` 显示不出来或变方框 | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 3.4 字符对照表 |
| 写了 `%%d`/`%%p`/`%%c` 却画出 `%%d` 字样 | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 3.4 末段：`%%` 转义只对 SHX 字体有效 |
| 中文在控制台显示乱码 | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 1 现象 C（终端编码，非数据问题） |
| 刷新后中文短暂变成 `?` 或空白 | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 4 预防第 9 条 |
| `textstyle_create` 返回 `font_resolved: false` | [`20261117-chinese-text.md`](20261117-chinese-text.md) | 4 预防第 3 条 |
| 表格文字贴在格子上边缘、不居中 | [`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md) | 2.1 / 3.1 修源码 / 3.2 补已有表 |
| `SetRowHeight` 设了但行高不对 | [`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md) | 2.2 字高撑开行高 |
| 表格移动失败（`InsertionPoint` / `Move`） | [`20261117-table-cell-alignment.md`](20261117-table-cell-alignment.md) | 3.3 必须用 Move + VARIANT |
| LISP 报 `needs the write tier (1.8.1)` / `policy_refused` | [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md) | 3.1 两个开关 KV / 重启进程 |
| LISP 报 `waits for the operator's input` | [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md) | 2.1 交互式 `get*` 独占 COM 线程，任何档位都不放行 |
| 表格标题有中文、单元格全空白 | [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md) | 2.2 单元格 `style=None` 回退 txt.shx / 3.2 两条解法 |
| `GetTextString` 返回 `300.0`/`nil` 等怪值 | [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md) | 2.2 末段：ActiveX 是 3 参数签名 |
| `(command "_.TABLE" ...)` 卡死 120s+ | [`20261118-lisp-policy-and-table-text.md`](20261118-lisp-policy-and-table-text.md) | 3.3 无效尝试表 / 改用 `vla-AddTable` |
| 门浮在墙上、墙体没开洞 | [`20261118-door-drawing.md`](20261118-door-drawing.md) | 2 根因 / 3 分段画墙 + 封口线 |
| 门的开启弧方向不对、门扇位置怪 | [`20261118-door-drawing.md`](20261118-door-drawing.md) | 3 门画法：**圆心=铰点**、半径=门宽、扫 90° |
| **中文数据/码点/样式全对，DWG 里仍是乱码** | [`20261118-chinese-text-dwg-fix.md`](20261118-chinese-text-dwg-fix.md) | 2.2 根因 / 3 三层修法（字体+逐实体 style+改 Standard） |
| **快照截图里中文空白**（判断显示是否正常） | [`20261118-chinese-text-dwg-fix.md`](20261118-chinese-text-dwg-fix.md) | 4 验证方法：只认真实窗口截图，快照渲染器会丢字 |
| 开了两个同名 DWG、`document_close` 报 ambiguous | [`20261118-chinese-text-dwg-fix.md`](20261118-chinese-text-dwg-fix.md) | 用 LISP `vla-Close` 按索引关 |
| **PDF 中文变 `???`**（DWG 内正常） | [`20261118-pdf-plot-fixes.md`](20261118-pdf-plot-fixes.md) | 2.1 根因：`.ttc` 无法嵌入 PDF / 3.1 换 `.ttf` |
| **PDF 右侧被裁**、标题栏文字缺失 | [`20261118-pdf-plot-fixes.md`](20261118-pdf-plot-fixes.md) | 2.2 可打印区 831×560 / 2.3 PlotType / 2.4 PlotRotation |
| **PDF 内容只画一半或缩放** | [`20261118-pdf-plot-fixes.md`](20261118-pdf-plot-fixes.md) | 3.1 图纸空间视口 + layout 1:1 出图 |
| `PlotToFile returned False` / PDF 0 字节 | [`20261118-pdf-plot-fixes.md`](20261118-pdf-plot-fixes.md) | 4 无效尝试表 / 用 `batch_plot` |
| **表格单元格中文空白**（标题正常、格子全空） | [`20261118-table-cell-cjk-and-alignment.md`](20261118-table-cell-cjk-and-alignment.md) | 2.2 根因：单元格走 `SetCellTextStyle` 而非实体样式 / 3.2 自动 CJK |
| 表格单元格文字偏上、不居中 | [`20261118-table-cell-cjk-and-alignment.md`](20261118-table-cell-cjk-and-alignment.md) | 2.1 默认 acTopLeft / 3.1 `SetCellAlignment(r,c,5)` |
| 给单元格设 `StyleName` 无效 | [`20261118-table-cell-cjk-and-alignment.md`](20261118-table-cell-cjk-and-alignment.md) | 2.2 必须用 `SetCellTextStyle(row, col, 名)` |
| **`ezdxf.bbox` 量 MTEXT 框大出数倍、凭空报文字重叠** | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因一：组码 41=0 被当成换行宽度，每词切一行 |
| 文字框宽度比 AutoCAD 小 33% 且不报错 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因三：字体名是完整路径，ezdxf 解析出退化度量 |
| `font.measurements.total_height` 换字体就不一致 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因四：从字形轮廓量 `A`，恒等于 char_height |
| MTEXT 多行高度少算 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因五：行距是 **5/3 字高**（3-on-5） |
| MTEXT 底对齐（attachment 7-9）位置偏低一字高 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因六：1-3 顶 / 4-6 中 / 7-9 底，必须比绝对坐标 |
| `accoreconsole` 跑 LISP 没反应、卡在 `命令:` | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 4 验证方法末段：本机未授权，改走 COM |
| `SaveAs("x.dxf")` 得到 `x.dxf.dwg` | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 4 验证方法：显式 `SaveAs(path, 61)` |
| 想让工具自动检查图中文字有没有交叠 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 3 处理：`python -m tools.text_overlap FILE.dxf`，七类检查 |
| **`m²`/中文在图上看着没事，打印出来缺字符** | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | `text_glyphless`：`Standard`=`txt.shx` 无 CJK 与 `²`/`Ø`/`±` 字形，AutoCAD 静默不画。**TrueType 会回退、SHX 不会**，所以不能用 cmap 判断。改样式字体为 `simsun.ttc`/`simhei.ttf` |
| **改了 `$DIMSCALE` 标注文字还是很小** | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 生效的是**样式**的 `dimscale`，不是图纸头。实测 `123.dxf`：头 50、样式 `ISO-25` 为 1.0，18 个标注只有 2.0 高。改样式即归零 |
| **同一行字既报 `text_text` 又报 `text_duplicate`** | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 已修：同一对只报一次，保留 `text_duplicate`（删除比挪开正确） |
| **块内文字角度错了：65° 量成 110°** | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因十（**已更正**）：`transform()` 保留旋转，是测量代码又补一次；只有 TEXT 暴露 |
| 非均匀缩放 / 镜像的块，文字框怎么算都不对 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因十末段：平行四边形，报 `not_checked`，别给近似值 |
| 表格合并后单元格文字位置会错吗 | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因十五：**不会**，`*T` 块已反映合并结果，15→13 格实测 |
| **出图后文字小到看不清，模型里看着没问题** | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 2 根因十六：`text_illegible`，按视口 `view_height/height` 折算纸面毫米，下限 ISO 3098 的 2.5 mm |
| 写 DXF 检查脚本报 `'gbk' codec can't encode character '\xb2'` | [`20261118-text-overlap-check.md`](20261118-text-overlap-check.md) | 3 末尾：`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，检查已成功死在打印上 |

---

*本文档为索引，具体内容在各记录文件中。新增记录后请更新本表两处：日期表与症状检索表。*
