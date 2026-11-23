# 房间、门和走廊的通行检查

在项目根目录用配置了 `ezdxf` 和 AutoCAD MCP `engineering.arch` 的 Python 运行。需要验证通行的场合，加 `--circulation`。检查器读取保存后的文件。

```bash
D:/git_codes/Autocad-MCP/.venv/Scripts/python.exe -m tools.text_overlap draw_test/Drawing2.dxf --circulation
```

报告中的 `circulation.rooms` 是有标签的空间总数，包含走廊。`reachable` 是沿已核验门洞从室外几何连通的数量。窗户可参与划分内外空间，不能充当入口。无标签的闭合空间可作为途中节点。门扇被机柜阻挡由 `opening_blocked` 独立报告，判断实际能否使用时要一起看。

| 报告项 | 在图上核查什么 |
|---|---|
| `room_no_entrance` | 用房间名和标签句柄定位。检查墙上是否真的留了门洞。 |
| `room_unreachable` | 房间有门，但这组空间没有接到室外。沿相邻门检查缺失的那一段。 |
| `door_swing_conflict` | 用两扇门的编号与门弧句柄定位。同一空间内的开启范围相交，同时操作可能互挡。仅相切不报。 |
| `corridor_clearance` | 门口单扇全开时的局部剩余净宽低于**项目提供**的限值。检查改门向、错开门位或拓宽走廊是否可行，再复测。 |

`--json` 的 `circulation.doors` 给出每樘门连接的两个空间、开启侧、门扇及门弧句柄。走廊门另列净宽 `section_mm` 和 `remaining_mm`。向室内开，取该处走廊墙面间距；向走廊开，扣除该扇门完全开启的投影。只有已知项目限值才传 `--min-corridor-width-mm 数值`。例如墙面净距 1800 mm、门向走廊伸入 1100 mm，单扇全开余宽为 700 mm。开向走廊本身不能判错。

走廊名称识别“走廊”“通廊”“corridor”“hallway”，其他命名可加 `--corridor-id R28`，可重复指定。`section_status` 表示端墙或交叉口局部方向需复核。测量限于门口横断面，设备沿途侵占、两扇门同时开启的组合剩余宽度、整段走廊的最窄处、门禁、楼梯及消防疏散要求需另行检查。扫掠扇区采用内接多边形（最大弦高 0.05 mm），近切触应在 CAD 中复核。

**适用图纸**：声明毫米的单层模型空间，墙、房间、平开门有 `ACADMCP_ARCH` 记录，门洞、门扇和门弧与实物图元一致。外来散线图、推拉门、卷帘门、块内门和跨层路径不在这项检查的支持范围。`not_checked` 或 `partial` 需要补数据或人工复核。显式要求检查时退出码 `2` 表示未充分检查，`1` 表示发现问题，`0` 表示已检查范围内无发现。检查只读。
