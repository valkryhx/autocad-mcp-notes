# AutoCAD MCP Pro 部署与实测记录

> 记录日期：2026-11-17
> 环境：Windows + Claude Code + cc-switch 3.20.4
> 包版本：`autocad-mcp-pro==1.8.0`（PyPI）
> AutoCAD：2026（版本号 25.1s LMS Tech），安装在 `D:\autocad_26\AutoCAD 2026\`

> **相关文档**
> - [`20261117-autocad-links.md`](20261117-autocad-links.md) — 安装包与资源链接
> - [`../AGENTS.md`](../AGENTS.md) — 日常使用指南

---

## 0. 目录

| 章节 | 内容 |
|---|---|
| [1. 目标](#1-目标) | 部署范围与环境基线 |
| [2. 关键认知](#2-关键认知mcp-配置到底写在哪) | MCP 配置写在哪个文件 |
| [3. 最终配置](#3-最终配置) | 完整 JSON 与各变量说明 |
| [3.1 环境变量](#31-各环境变量说明) | 逐条解释 |
| [3.2 版本锁定](#32-为什么-180-是硬锁) | `==1.8.0` 的行为 |
| [4. 安装过程](#4-安装过程) | 步骤、备份、踩过的坑 |
| [4.3 踩过的坑](#43-踩过的坑) | 四个已排查问题 |
| [5. 实测验证](#5-实测验证) | COM / accoreconsole / 产物校验 |
| [6. Premium 技能部署](#6-premium-技能部署) | 决策与部署 |
| [7. 生效方式](#7-生效方式) | 重启与验证 |
| [8. 能力差异](#8-附autocad-有无的能力差异) | 双引擎对照 |
| [9. 参考](#9-参考) | 外链与本地仓库 |

---

## 1. 目标

在 cc-switch 管理的 Claude Code 环境中接入 [AutoCAD MCP Pro](https://github.com/U-C4N/Autocad-MCP)，并部署它附带的 `premium` 绘图工作流技能。

---

## 2. 关键认知：MCP 配置到底写在哪

cc-switch 里「湛卢」供应商那段 JSON 是 **`settings.json`** 的内容（`env` / `permissions` / `enabledPlugins` / `statusLine`），**MCP 服务器不在其中**。

| 文件 | 内容 | 由谁写入 |
|---|---|---|
| `~/.claude/settings.json` | 模型、环境变量、权限、hooks | cc-switch 切换供应商时整体覆盖 |
| `~/.claude.json` → `mcpServers` | **MCP 服务器定义** | cc-switch 的「MCP 服务器」页面 |
| `~/.claude/mcp.json` | 旧位置（本机仅剩 `exa` 残留） | 不应再使用 |

验证依据：cc-switch 库中 `fetch`、`exa` 两条 `enabled_claude=1`，`~/.claude.json` 的 `mcpServers` 中恰好只有这两个 —— 说明 cc-switch 的 MCP 页面写的就是 `.claude.json`。因此**切换供应商不会冲掉 MCP 配置**。

---

## 3. 最终配置

写入两处，内容一致：

- `~/.claude.json` → `mcpServers.autocad`
- cc-switch DB（`~/.cc-switch/cc-switch.db`）→ `mcp_servers` 表 `id='autocad'`

```json
{
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "autocad-mcp-pro[com,pdf,office]==1.8.0", "autocad-mcp"],
  "env": {
    "AUTOCAD_MCP_BACKEND": "auto",
    "ALLOWED_PATHS": "C:/,D:/",
    "TOOL_PROFILE": "full",
    "TOOL_PACKS": "all",
    "DISCOVERY_MODE": "search",
    "ACCORECONSOLE_PATH": "D:\\autocad_26\\AutoCAD 2026\\accoreconsole.exe"
  }
}
```

### 3.1 各环境变量说明

| 变量 | 值 | 作用与选择理由 |
|---|---|---|
| `AUTOCAD_MCP_BACKEND` | `auto` | AutoCAD 运行时走 COM 实时引擎；未运行或未装则落到 `ezdxf` 无头引擎。装完 AutoCAD 无需改配置。 |
| `ALLOWED_PATHS` | `C:/,D:/` | 文件访问白名单。整盘放开但系统目录仍被硬编码黑名单挡住。相比留空更安全，且只需改一个值即可收紧。 |
| `TOOL_PROFILE` | `full` | 共注册 257 个工具，`full` 默认启用 252 个（`ENABLE_3D` 未开则隐藏 5 个 `solid_*`）。改用 `lean` 可得 67 个精选工具（`TOOL_PACKS=core` 时 57 个）。 |
| `TOOL_PACKS` | `all` | 广告全部垂直包：core / pid / settings / mech / arch / plant。 |
| `DISCOVERY_MODE` | `search` | 1.8.0 默认值。客户端只看到 6 个入口工具（`search_tools` / `call_tool` / `describe_tool` + 3 个 pinned），prompt 开销从 59,138 token 降到 1,026，其余工具仍可按名直接调用。 |
| `ACCORECONSOLE_PATH` | `D:\autocad_26\AutoCAD 2026\accoreconsole.exe` | **必须设置**。代码 `backends/dwg_read.py:79` 把默认路径硬编码为 `C:\Program Files\Autodesk\AutoCAD 2026\`，非默认安装位置会导致无头读 DWG 失败。 |

### 3.2 为什么 `==1.8.0` 是硬锁

实测三种写法的行为：

| 写法 | 上游发布 1.9.0 后的行为 |
|---|---|
| `autocad-mcp-pro[com,pdf,office]==1.8.0` | 永远 1.8.0，**不下载新版** |
| `autocad-mcp-pro[com,pdf,office]` | 每次启动重新解析，**自动取最新** |
| `autocad-mcp-pro[com,pdf,office]>=1.8,<1.9` | 自动吃 1.8.x 补丁，不吃 1.9 |

验证：改成 `==1.7.0` 后立刻重新下载并装上 1.7.0；去掉版本号则解析到当前 `1.8.0`。

**注意**：即使锁死版本，uvx 每次启动仍会对 PyPI 索引发一次条件 GET（`stale response → revalidation → not-modified`）。锁死保证的是**版本不变**，不是**不联网**。断网时有缓存仍可启动（`UV_OFFLINE=1` 实测通过）。

**保持 pin 的理由**：上游在 `plugin/.mcp.json` 和 `server.json` 中均有意 pin 版本，`tests/test_plugin_package.py` 还断言 pin 与版本号一致。升级时手动改数字后重启即可；若异常则 `uv cache clean autocad-mcp-pro`。

---

## 4. 安装过程

### 4.1 步骤

1. 备份
   ```bash
   cp ~/.cc-switch/cc-switch.db ~/.cc-switch/cc-switch.db.bak-autocad-20261117190756
   cp ~/.claude.json ~/.claude.json.bak-autocad-20261117190757
   ```

2. 确认工具链
   ```bash
   uv --version      # 0.11.0
   uvx --version     # /c/anaconda3/Scripts/uvx.exe
   ```

3. 预验证包可运行
   ```bash
   uvx --from "autocad-mcp-pro[com,pdf,office]==1.8.0" autocad-mcp --help
   # → Installed 86 packages，输出 usage，搜索模式日志正常
   ```

4. 写入 Claude Code 配置（官方 CLI 方式）
   ```bash
   claude mcp add autocad -s user \
     -e AUTOCAD_MCP_BACKEND=auto \
     -e ALLOWED_PATHS="C:/Users/drago/Documents/AutoCAD" \
     -e TOOL_PROFILE=full \
     -e TOOL_PACKS=all \
     -e DISCOVERY_MODE=search \
     -- uvx --from "autocad-mcp-pro[com,pdf,office]==1.8.0" autocad-mcp
   ```

5. 在 cc-switch DB 登记（界面同步用）
   ```sql
   INSERT OR REPLACE INTO mcp_servers
     (id, name, server_config, description, homepage, docs, tags,
      enabled_claude, enabled_codex, enabled_gemini, enabled_opencode,
      enabled_hermes, enabled_grokbuild, enabled_mcode)
   VALUES (...);
   ```

6. 连通性验证
   ```bash
   claude mcp list
   # autocad: uvx --from autocad-mcp-pro[com,pdf,office]==1.8.0 autocad-mcp - ✔ Connected
   ```

### 4.2 备份清单

```
~/.claude.json.bak-autocad-20261117190757
~/.claude.json.bak-unlimit-20261117192157
~/.claude.json.bak-accore-20261117193401
~/.cc-switch/cc-switch.db.bak-autocad-20261117190756
```

### 4.3 踩过的坑

**坑 1：AutoCAD 安装目录改名导致 COM 注册失效**

`acad.exe` 被手动改名（去掉路径空格）后，COM 报 `-2147221164`（`REGDB_E_CLASSNOTREG`，类未注册）。

排查结果：注册表 **97 处**引用全部指向带空格的 `D:\autocad_26\AutoCAD 2026\`，而实际目录是 `D:\autocad_26\AutoCAD2026`，`LocalServer32` 指向的 exe 不存在，COM 无法拉起进程。

```python
# 诊断脚本的核心判断
v = winreg.QueryValueEx(winreg.OpenKey(HKEY_CLASSES_ROOT,
        'CLSID\\{363E5B47-885D-44C3-89EB-A2AB2129B57E}\\LocalServer32'), '')[0]
# → 'D:\autocad_26\AutoCAD 2026\acad.exe /Automation'
# exe 存在? False   ← 根因
```

**结论**：目录名改回带空格后自愈，`Dispatch` 与 `GetActiveObject` 均恢复正常。**安装目录名不可改**，一改就会回到 `REGDB_E_CLASSNOTREG`。

**坑 2：`cad_batch` 的步骤键是 `args` 不是 `arguments`**

```json
// 错误
{"steps": [{"tool": "entity_create_circle", "arguments": {...}}]}
// 正确
{"steps": [{"tool": "entity_create_circle", "args": {...}}]}
```

错误信息明确：`step 0 has unexpected key(s) ['arguments']; a step is {'tool', 'args', 'bind'}`。`cad_batch` 默认 `on_error=rollback`，整批拒绝，不会执行任何一步。

**坑 3：工具名不是 `entity_create`**

按类型分成了独立工具：
- `entity_create_circle(cx, cy, radius)`
- `entity_create_line(x1, y1, x2, y2)`
- 批量场景用 `entity_batch_create(entities)`

用 `search_tools` 查询真实名称与必填参数最可靠。

**坑 4：`ACCORECONSOLE_PATH` 必须显式设置**

因为装在 `D:\autocad_26\`，而代码硬编码默认值是 `C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe`。不设置则无头打开 DWG 报 `dwg_read` 能力拒绝。

---

## 5. 实测验证

### 5.1 COM 实时引擎

```json
{
  "backend": "com",
  "connected": true,
  "cad_progid": "AutoCAD.Application",
  "autocad_version": "25.1s (LMS Tech)",
  "open_documents": 1,
  "capabilities": ["live_control", "screenshot", "transactions",
                   "com_api", "lisp_execution", "entities_2d"],
  "tool_count": 257,
  "state_store": {"mode": "durable", "degraded": false}
}
```

绘图测试：一个法兰轮廓（外圆 R100、内孔 R40、4×R8 螺栓孔 @±70、两条中心线 @±120），8 个实体全部成功，返回真实 handle（`95`~`9C`）。

```
BATCH 1/8 entity_create_circle  ok
...
BATCH 8/8 entity_create_line    ok
TOOL OK  cad_batch  985.0ms
TOOL OK  drawing_save_as  78.0ms
```

`drawing_new` 自动 bootstrap 了 10 个 ISO 图层（GEOMETRY / HIDDEN / CENTER / PHANTOM / DIM / TEXT / HATCH / TITLEBLOCK / CONSTRUCTION）和 8 种线型（CENTER / HIDDEN / PHANTOM / DASHED / DASHDOT 等）。

### 5.2 accoreconsole 无头读 DWG

```
route:      "accoreconsole"
exit_code:  0
seconds:    1.343
timeout_s:  60.0
log: "AutoCAD Core Engine Console - Copyright 2025 Autodesk, Inc. (W.60.0.0)"
```

全链路：AutoCAD 存 DWG（103 KB）→ 无头引擎用 `accoreconsole` 转回 DXF 并成功打开。

### 5.3 产物校验

用 `ezdxf` 精确读取 `flange_test.dxf`：

```
DXF 版本: AC1027 | 编码: gbk | 实体数: 8
  CIRCLE  center=(0,0)      r=100
  CIRCLE  center=(0,0)      r=40
  CIRCLE  center=(70,0)     r=8
  CIRCLE  center=(-70,0)    r=8
  CIRCLE  center=(0,70)     r=8
  CIRCLE  center=(0,-70)    r=8
  LINE    (-120,0) -> (120,0)
  LINE    (0,-120) -> (0,120)
图层: 0, GEOMETRY, HIDDEN, CENTER, PHANTOM, DIM, TEXT,
      HATCH, TITLEBLOCK, CONSTRUCTION, Defpoints
线型: ByBlock, ByLayer, Continuous, CENTER, HIDDEN, PHANTOM, DASHED, DASHDOT
```

渲染 PNG 目视确认法兰轮廓正确。

### 5.4 测试产物

位于 `D:\git_codes\test_Autocad_MCP\draw_test\`：

| 文件 | 大小 | 说明 |
|---|---|---|
| `flange_test.dxf` | 88,845 B | COM 引擎绘制并保存 |
| `flange_test.dwg` | 102,965 B | AutoCAD 原生格式 |
| `flange_test.png` | 21,618 B | ezdxf + matplotlib 渲染预览 |
| `headless_test.dxf` | 21,115 B | 无头引擎绘制验证（含 sha256 与 cp-1 检查点） |
| `e2e_test.py` | — | 端到端测试脚本 |
| `test_dwg_read.py` | — | DWG 读写全链路测试脚本 |

---

## 6. Premium 技能部署

### 6.1 决策：只装 skill，不装插件

插件包含 MCP 服务器 + skill 两部分。**已有 MCP 的情况下装插件会重复启动第二个 AutoCAD 服务器**，两者争抢同一个 AutoCAD 实例。

上游 README 原文：

> Already running the server yourself? Keep one server. Either turn off this plugin's server in `/mcp` ... or skip the plugin and copy the skill folder — `.claude/skills/autocad-mcp-premium/` from the repository — into your project's or your user's `.claude/skills/`.

因此采用「拷贝 skill 文件夹」方案。

### 6.2 内容一致性验证

```bash
diff -r D:/git_codes/Autocad-MCP/.claude/skills/autocad-mcp-premium \
        D:/git_codes/Autocad-MCP/plugin/skills/premium
# → 完全一致
```

且 skill 内**零处**引用 `CLAUDE_PLUGIN_ROOT`、`plugin:` 前缀等插件运行时变量 —— 独立安装不丢任何功能。

### 6.3 部署步骤

```bash
# 1. 复制到用户 skills 目录
cp -r "D:/git_codes/Autocad-MCP/.claude/skills/autocad-mcp-premium" ~/.claude/skills/

# 2. 同步到 cc-switch 的 skills 存储
cp -r ~/.claude/skills/autocad-mcp-premium ~/.cc-switch/skills/
```

```sql
-- 3. 在 cc-switch 登记
INSERT OR REPLACE INTO skills
  (id, name, description, directory, repo_owner, repo_name, repo_branch,
   readme_url, enabled_claude, enabled_codex, enabled_gemini, enabled_opencode)
VALUES ('local:autocad-mcp-premium', 'autocad-mcp-premium', '...',
        'autocad-mcp-premium', 'U-C4N', 'Autocad-MCP', 'main',
        'https://github.com/U-C4N/Autocad-MCP', 1, 0, 0, 0);
```

### 6.4 部署结果

```
~/.claude/skills/autocad-mcp-premium/     17 个文件，100 KB
├── SKILL.md
├── examples/         5 个案例（法兰、P&ID、交付报告、歧义孔位、过期版本）
└── references/      11 篇方法论（需求绑定、机械编辑、P&ID 项目、外来图纸…）
```

cc-switch DB：`skills` 表 `id='local:autocad-mcp-premium'`，`enabled_claude=1`。

### 6.5 技能的作用

一套**方法论**而非工具，核心把「画完就算完」变成「在 CAD 上实测过才算完」：

```
需求绑定 → 几何 → 在 CAD 上验证 → 保存 → 重开验证 → 交付
```

按输入源自动分流：

| 输入 | 引导路径 |
|---|---|
| 带尺寸的草图/PDF | `drawing_preflight` → `mech_part_draw` → `drawing_verify_requirements` |
| 要改的现有图纸 | `cad_batch(dry_run=True)` → `mech_part_revise` → `drawing_history` |
| P&ID | `pid_from_spec` / `pid_graph` / `pid_project` |
| 别人的 DWG/DXF | `drawing_understand` / `drawing_topology_check` / `drawing_diff` |
| 平面图 | `arch_plan_from_spec` / `arch_rooms_detect` / `arch_schedule` |
| 算量（管道/电缆） | `drawing_scale_check` / `pipe_takeoff` / `cable_takeoff` |

同时收录一批「**看起来对但其实错**」的捷径（截图好看就交付、凭记忆确认已保存等），会主动拦截。

**触发**：画图类任务自动加载；手动调用 `/autocad-mcp-premium`。

**更新方式**：本地拷贝不会自动跟随上游。上游更新时重新 `cp -r`，或改为指向仓库的符号链接（`git pull` 后自动生效）。

---

## 7. 生效方式

**重启 Claude Code**。新环境变量（尤其 `ACCORECONSOLE_PATH`）需下次启动才读取。

验证清单：

```bash
# MCP 连通
claude mcp list | grep autocad

# 技能可见
/skills          # 在 Claude Code 中查看 autocad-mcp-premium
```

---

## 8. 附：AutoCAD 有无的能力差异

| 能力 | 无 AutoCAD（`ezdxf`） | 有 AutoCAD（`com`） |
|---|---|---|
| 新建/画图/图层/标注/导入导出 DXF | ✅ | ✅ |
| 导出 PDF / PNG | ✅ | ✅ |
| 打开真实 `.dwg` | ⚠️ 需 `accoreconsole`（已配置）或 ODA 转换器 | ✅ 原生 |
| 实时在 AutoCAD 窗口绘制、`view_screenshot` 截图 | ❌ | ✅ |
| `system_run_command` / AutoLISP（`system_run_lisp`） | ❌ | ✅ |
| 3D 实体（需 `ENABLE_3D=true`） | ❌ | ✅ |

README 中「autocad not needed」指的是**绘图能力本身**（ezdxf 引擎全平台可用），而非「装了没意义」。

---

## 9. 参考

- 项目主页：https://github.com/U-C4N/Autocad-MCP
- PyPI：https://pypi.org/project/autocad-mcp-pro/
- 本地仓库：`D:\git_codes\Autocad-MCP`（HEAD `6f6a538`，v1.8.0）

---

*本文档记录 2026-11-17 的部署与实测结果。配置变更后请同步更新。*
