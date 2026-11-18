# AutoCAD 软件与 MCP 资源链接

> 记录日期：2026-11-17
> 用途：本机 AutoCAD 2026 与 AutoCAD MCP Pro 的获取来源备查。

> **相关文档**
> - [`20261117-autocad_mcp.md`](20261117-autocad_mcp.md) — 部署与实测记录
> - [`../AGENTS.md`](../AGENTS.md) — 日常使用指南

---

## 0. 目录

| 章节 | 内容 |
|---|---|
| [1. AutoCAD 安装包](#1-autocad-安装包) | 迅雷云盘链接与解压密码 |
| [2. 安装教程](#2-安装教程) | 知乎、xiecoding |
| [3. AutoCAD MCP](#3-autocad-mcp) | 项目主页、PyPI、本地仓库 |
| [4. 可选补装](#4-可选补装) | ODA File Converter |

---

## 1. AutoCAD 安装包

| 项目 | 内容 |
|---|---|
| 来源 | 迅雷云盘 |
| 链接 | https://pan.xunlei.com/s/VP3ifUCQTw_xzXZwi_ngSi1yA1 |
| 提取码 | `xvyp` |
| 解压密码 | `313927` |
| 归档目录 | `CAD2027-2003` |
| 备注 | **先转存再下载** |

原始链接（含全部参数）：

```
https://pan.xunlei.com/s/VP3ifUCQTw_xzXZwi_ngSi1yA1?pwd=xvyp&path=%2FCAD2027-2003%28%E5%85%88%E8%BD%AC%E5%AD%98%E5%86%8D%E4%B8%8B%E8%BD%BD%EF%BC%8C%E8%A7%A3%E5%8E%8B%E5%AF%86%E7%A0%81%EF%BC%9A313927%29
```

> ⚠️ 该归档目录名为 `CAD2027-2003`，与本次安装的 **AutoCAD 2026** 不一定对应，使用前请核对版本。
> 安装后**不要修改安装目录名**（原因见部署记录第 4.3 节「坑 1」）。

---

## 2. 安装教程

| 来源 | 链接 |
|---|---|
| 知乎专栏 | https://zhuanlan.zhihu.com/p/2093087586336125840 |
| 写代码（xiecoding） | https://xiecoding.cn/view/1064.html |

---

## 3. AutoCAD MCP

| 项目 | 内容 |
|---|---|
| 项目主页 | https://github.com/U-C4N/Autocad-MCP |
| PyPI 包 | https://pypi.org/project/autocad-mcp-pro/ |
| 版本 | `autocad-mcp-pro==1.8.0` |
| 本地仓库 | `D:\git_codes\Autocad-MCP`（HEAD `6f6a538`） |
| 官方文档 | 仓库内 `README.md`、`plugin/README.md`、`docs/` |

---

## 4. 可选补装

| 组件 | 用途 | 状态 |
|---|---|---|
| [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) | 无头引擎把图纸**写出**为 `.dwg` 的唯一途径 | ❌ 本机未安装 |
| `accoreconsole` | 无头引擎**读取** `.dwg` | ✅ 已就绪（`D:\autocad_26\AutoCAD 2026\accoreconsole.exe`） |

只读不写 DWG 的话，`accoreconsole` 已够用，无需补装 ODA。

---

*本文档记录 2026-11-17 的资源链接。链接失效时请更新本表。*
