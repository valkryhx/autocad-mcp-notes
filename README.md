# AutoCAD MCP 实战笔记

用 Claude Code 驱动 AutoCAD 2026 画图的踩坑记录与可复用经验。

不是工具文档，是**真实项目里撞过的墙**：每一条都来自一次失败、一段报错原文、一个最终生效的做法。

---

## 这个仓库是什么

一个新手带着 AI 学 AutoCAD 的过程记录。核心问题是：

> **「看起来对」和「确认对了」之间，差了什么？**

答案往往是差得很远。比如中文写进图纸、`GetTextString` 读得回来、码点完全正确——屏幕上依然一片空白，而且不报错。

这个仓库把这类**静默失败**一条条挖出来、留证据、写成可检索的记录。

---

## 目录

| 路径 | 内容 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **主文档**。环境基线、九条铁律、工具速查、快速排错表、问题记录制度 |
| [`docs/`](docs/) | 14 篇问题记录，每篇含「现象 / 根因 / 处理 / 预防」四段 |
| [`docs/20261117-autocad-troubleshooting.md`](docs/20261117-autocad-troubleshooting.md) | **问题索引**，按日期和按症状双维度检索 |
| [`drawings/gpu-datacenter/`](drawings/gpu-datacenter/) | 成品：100 台 GPU 机柜的智算中心平面图（DWG/DXF/PDF） |
| [`drawings/table-test/`](drawings/table-test/) | 表格测试图，验证单元格居中与中文显示 |
| [`examples/gen_gpu_dc.py`](examples/gen_gpu_dc.py) | 机房平面图的生成脚本，可直接改参数重跑 |

---

## 最值得读的几条

### 中文「能存不能看」

码点完全正确、`GetTextString` 读得回来、屏幕上什么都没有。

根因：默认 `Standard` 样式的字体是 `txt.shx`，**没有 CJK 字形，AutoCAD 静默跳过不报错**。

→ [`docs/20261117-chinese-text.md`](docs/20261117-chinese-text.md)

### PDF 里中文变 `???`

DWG 里显示正常，导出 PDF 全是问号。

根因：样式用了 `.ttc` 集合字体（`simsun.ttc`），PDF 无法嵌入，AutoCAD 把文字**炸成几何线条**——PDF 内容流里 `Tj` 指令为 0。

修法：换单体 `.ttf`（`simhei.ttf`）。

→ [`docs/20261118-pdf-plot-fixes.md`](docs/20261118-pdf-plot-fixes.md)

### LISP 返回值是上一次调用的结果

`system_run_lisp` 有时返回的不是本次结果——于是「验证通过」可能是假的。

根因：值存在 `USERS1` 系统变量里，它是**跨调用持久**的；表达式出错时最外层 `setvar` 没执行，读到的就是上次残留。

已给上游提交 PR 修复。

→ [`docs/20261118-lisp-stale-result.md`](docs/20261118-lisp-stale-result.md)

### 表格单元格不跟随实体样式

给表格设 `StyleName` 毫无作用。TABLE 的单元格走的是 `SetCellTextStyle`，`AddTable` 把全部格子放在 `Standard` 上——所以中文和 `m²` 都画不出来。

→ [`docs/20261118-table-cell-cjk-and-alignment.md`](docs/20261118-table-cell-cjk-and-alignment.md)

### 门「浮在墙上」

门洞是墙的真实开口，不是贴在墙上的符号。墙体必须**分段绘制**并在门洞处留空，门的 1/4 圆弧**圆心是铰点**。

→ [`docs/20261118-door-drawing.md`](20261118-door-drawing.md)

---

## 一条贯穿始终的教训

**渲染器不等于图纸。**

在这个项目里被渲染器骗过三次：

| 判断依据 | 后果 |
|---|---|
| `view_screenshot` 的 region 模式（`Document.Export` 快照） | **会丢弃文字**，中文显示空白却是误报 |
| ezdxf + matplotlib 渲染 | 缺中文字体，正常的中文画成方块 |
| 仅看 `attachment_point` 属性 | 属性对，几何未必对 |

真正可信的验证是：

1. **真实窗口截图**（`view_zoom_and_screenshot`）
2. **从文件里读回几何并计算**（ezdxf 读 DXF，比对坐标/码点/样式）
3. **对照实验**（同一环境，改一个变量，看差异）

第 3 条最有力。判定「单元格是否居中」不是看属性，而是从表格网格线算出每行中心，再比对文字 y——实测 11 个单元格偏差 `+0.0`。

---

## 环境

| 项目 | 值 |
|---|---|
| AutoCAD | 2026 · `25.1s (LMS Tech)` |
| MCP 服务 | `autocad-mcp-pro` 1.8.0 |
| 驱动 | Claude Code + `autocad-mcp-premium` 技能 |
| 生成库 | ezdxf |
| 平台 | Windows |

---

## 给上游的反馈

探索过程中发现并修复了三个上游缺陷：

| PR | 问题 |
|---|---|
| [#29](https://github.com/U-C4N/Autocad-MCP/pull/29) | `system_run_lisp` 在表达式出错时返回上一次的值 |
| [#30](https://github.com/U-C4N/Autocad-MCP/pull/30) | 表格单元格默认顶部对齐；单元格中文画不出来 |

---

## 许可

文档以 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 共享，脚本以 MIT 授权。

欢迎补充自己的踩坑记录——判断标准只有一句：**下次遇到同样情况，这份记录能让人少走十分钟弯路吗？**

具体格式与登记步骤见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
