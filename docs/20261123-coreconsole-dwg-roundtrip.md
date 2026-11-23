# AutoCAD 控制台转换与机柜图回读

记录日期 2026-11-23。环境为 Windows 11、AutoCAD 2026 W.60、Git Bash 和 Windows Python。

相关文档：[绘图排错索引](20261117-autocad-troubleshooting.md)。

## 1. 现象

直接从 Git Bash 调用控制台时出现 `Usage:` 和 `Example:`，随后停在 `命令:`，没有输出 DWG。独立 COM 尝试返回 `AttributeError: <unknown>.Open`。

## 2. 根因与证据

这次从控制台打印的帮助不能判断许可证失效。换成 Windows Python 的原生 argv 列表和 CRLF 脚本，使用相同安装的 accoreconsole，日志出现 `命令: _.SAVEAS`、格式提示及指定目标路径，输出有效 DWG。本次同时改变了命令行传参和换行，未单独定位是哪一项造成差异。

## 3. 处理

在独立临时目录复制 DXF。用 `subprocess.run([exe, "/i", str(input_path), "/s", str(script_path), "/l", "en-US"])`。ASCII 脚本用 CRLF 逐行传入 `_.SAVEAS`、`2018`、带引号的全新 DWG 正斜杠路径。回读时复制磁盘 DWG，用 `_.SAVEAS`、`_DXF`、空行（默认精度）、新的 DXF 路径。原图不被重新指向。

## 4. 预防

核对新文件头并重开。`DC72_rack_plan` 的两版均回读到 851 个模型实体，192 台机柜的柜号、外框和朝向一致。没有这些证据时，不把终端退出或文件存在当作核验。

更新于 2026-11-23，仅记录本次环境和已实测转换路径。
