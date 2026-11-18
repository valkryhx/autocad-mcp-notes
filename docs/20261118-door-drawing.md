# 建筑门画法：墙体必须断开

> 记录日期：2026-11-18
> 环境：AutoCAD 2026、ezdxf 生成 DXF
> 相关文档：[`AGENTS.md`](../AGENTS.md) · [`20261117-autocad-troubleshooting.md`](20261117-autocad-troubleshooting.md)

---

## 1. 现象

用 ezdxf 生成的平面图，房门「浮在墙上」：门扇和开启弧画出来了，但**墙体是整条实线，门洞没开**。视觉上门像是贴在墙上的一张纸，而不是穿过墙的开口。

## 2. 根因

最初把墙当成「一个矩形框」整体绘制：

```python
rect(RX0, CY0, RX1, CY1, "A-WALL-IN")     # 整条墙
door(8800, CY1, 900)                       # 再把门叠上去
```

`rect()` 画的是完整闭合矩形，门的位置**没有留洞**。建筑制图里门洞是墙的真实开口，墙体必须在该处断开，并画出洞口两侧的封口线。

## 3. 处理

参照 `123.dwg` 的既有画法（实测其 `A-DOOR-E-N` 图层）：

```text
LINE (3500,120) -> (3500,1620)                        ← 门扇，垂直于墙
ARC  c=(3500,120) r=1500 a=90..180                    ← 开启弧，圆心在铰点
```

墙在门处断开（实测 `123_check.dxf` 的 `A-WALL-E-N`）：

```text
(120,120)->(2000,120)      ← 墙段到门洞止
(2000,120)->(2000,-120)    ← 门洞封口线
(3500,120)->(3800,120)     ← 门洞另一侧封口 + 墙段继续
```

### 正确做法：分段画墙 + 封口

```python
def hwall_with_doors(y1, y2, layer, doors):
    """画水平墙，在 doors 的 (x1,x2) 区间留洞并封口"""
    cur = RX0
    for dx1, dx2 in sorted(doors):
        if dx1 > cur:
            rect(cur, y1, dx1, y2, layer)        # 墙段
        line(dx1, y1, dx1, y2, layer)            # 封口线
        line(dx2, y1, dx2, y2, layer)            # 封口线
        cur = dx2
    if cur < RX1:
        rect(cur, y1, RX1, y2, layer)
```

### 门的画法：铰点在墙线上

```python
def door_h(x_hinge, y_wall, w, opens_up=True, hinge_right=True):
    """水平墙上的门；铰点在墙线上，门扇垂直，1/4 弧表示开启方向"""
    if opens_up:
        line(x_hinge, y_wall, x_hinge, y_wall + w)        # 门扇 +Y
        a0, a1 = (90, 180) if hinge_right else (0, 90)
    else:
        line(x_hinge, y_wall, x_hinge, y_wall - w)        # 门扇 -Y
        a0, a1 = (180, 270) if hinge_right else (270, 360)
    msp.add_arc(P(x_hinge, y_wall), w, a0, a1)            # 圆心 = 铰点
```

**关键点**：`add_arc` 的**圆心必须是铰点**，半径 = 门宽，扫 90°。圆弧从门扇末端扫到墙线，才表达正确的开启方向。

### 双开门

两扇各 900，铰点分别在外侧，`hinge_right` 一真一假，弧相向：

```python
door_h(8800, CY0, 900, opens_up=True, hinge_right=False)   # 左扇，左铰
door_h(10600, CY0, 900, opens_up=True, hinge_right=True)   # 右扇，右铰
```

## 4. 验证方法

画完必须实测，不能看「画了门」就认为对：

```python
# 1. 墙确实断开：门洞区间内不应有墙体矩形
# 2. 封口线存在：门洞两端各一条竖线
# 3. 门扇铰点落在墙线上
for e in msp:
    if e.dxf.layer == 'A-DOOR' and e.dxftype() == 'ARC':
        assert abs(e.dxf.center.y - y_wall) < 1     # 圆心贴在墙面
```

实测输出（正确）：

```text
LINE  (8800, -2640) -> (8800, -1740)     ← 门扇，起点在墙面 y=-2640
ARC   c=(8800, -2640) r=900 a=0..90      ← 圆心 = 铰点
墙体矩形: x 0..8800 和 x 10600..19200    ← 中间 1800 真空
封口线:   x=8800, x=10600
```

## 5. 预防

1. **门洞是墙的开口，不是贴在墙上的符号**。画墙时先确定门洞位置，分段绘制。
2. **ARC 的圆心 = 铰点**，不是门扇末端；半径 = 门宽。
3. **双开门两扇铰点在外侧**，开启弧相向。
4. 画完用几何断言验证：墙体在门洞区间内确实为空、封口线存在、圆心在墙线上。
5. 有既有图纸时先读它的图层与几何（`drawing_understand` / ezdxf），照它的画法做，别自己发明。

---

*2026-11-18 记录。参照 123.dwg 的 A-DOOR-E-N 图层实测画法。*
