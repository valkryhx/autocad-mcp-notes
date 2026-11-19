# OpenBLAS 内存失败与渲染器字形盲区

> 记录日期：2026-11-19
> 环境：AMD Ryzen 7 8845HS（8C/16T，15.3 GB），AutoCAD 2026，numpy 2.4.6，matplotlib 3.11.2，ezdxf 1.4.4

> **相关文档**
> - [`20261119-printwindow-com-wedge.md`](20261119-printwindow-com-wedge.md) — GPU 合成导致截图全白，渲染器的由来
> - [`20261117-chinese-text.md`](20261117-chinese-text.md) — `txt.shx` 无 CJK 字形
> - 技能：`~/.claude/skills/autocad-mcp-premium/references/rendering-without-autocad.md`

---

## 现象

三条独立的现象在同一次会话里依次出现，最初被误判为同一个根因。

**① `import numpy` 崩溃**

```text
OpenBLAS error: Memory allocation still failed after 10 retries, giving up.
```

**② 升级 matplotlib 时中断**

```text
error: failed to remove file
`D:\git_codes\Autocad-MCP\.venv\Lib\site-packages\fontTools/misc/bezierTools.cp311-win_amd64.pyd`:
拒绝访问。 (os error 5)
```

**③ 之后 `import matplotlib` 报缺模块**

```text
ModuleNotFoundError: No module named 'fontTools.agl'
```

---

## 根因

### ① 内存压力，不是版本

我最初把 ① 当成 matplotlib/numpy 的版本缺陷，提议 `pip install --upgrade`。实测推翻：

```text
numpy 2.4.6 / matplotlib 3.11.2   ← 已经是 PyPI 最新版
uv pip install --upgrade           ← "Would make no changes"（numpy）
                                   ← 只动 fonttools 4.63→4.68、pyparsing 3.3.2→3.3.3
```

真正的证据是内存：

```text
物理内存 15.3 GB   可用 0.7 GB   提交余量 0.6 GB
acad.exe 私用 1365 MB
```

释放内存后，不加任何环境变量连续 `import numpy` 4 次、完整渲染 DXF 5 次**全部成功**。用户当场指出「刚才是 autocad 吃内存」。

OpenBLAS 崩溃是**症状**，内存压力是**病**。

### ②③ pip 先删后装，删完才失败

pip 的升级顺序是「删旧包 → 装新包」。`fontTools` 的 `bezierTools.cp311-win_amd64.pyd` 被**运行中的 MCP 服务进程**（PID 48632，`autocad-mcp.exe`）加载并持有，删不掉：

```text
python (48632) : D:\git_codes\Autocad-MCP\.venv\Lib\site-packages\fontTools\misc\bezierTools.cp311-win_amd64.pyd
```

于是 pip 在「删了一半」的状态失败，**留下了 67 个源码文件被删、`.pyd` 还留着的坏包**。重装同样失败（还是要删那个被锁的文件），`import matplotlib` 立刻因为缺 `fontTools.agl` 而挂。

### ③ 渲染器的字形盲区

这是本次最有价值的发现，因为它决定工具归属。

同一张图渲染两次，只改文字样式：

| 样式字体 | AutoCAD 里的表现 | matplotlib 渲染 |
|---|---|---|
| `simhei.ttf` | `76.00 m²` 正常 | 正常 |
| `txt`（SHX，无 `²` 字形） | 显示成 `76.00 m` | **照样画出 `²`** |

两张渲染图的差异：

```text
max diff: 46     nonzero px: 168 of 1,813,000  (0.009%)
diff 散布在全部文字上：世界坐标 x 410..9803, y 514..7722
```

**ezdxf 对缺失字形静默回退到替代字体，照样画。** 所以渲染图干净 ≠ 文字能打印出来。

---

## 处理

### ① 内存

```powershell
# 先量，再判断
Get-CimInstance Win32_OperatingSystem | Select-Object @{n='FreeGB';e={[math]::Round($_.FreePhysicalMemory/1MB,1)}}
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 ProcessName,WorkingSet64
```

渲染脚本内设 `OPENBLAS_NUM_THREADS=1`（缩小 arena 预留）。释放内存是主解。

### ②③ 修复半删的 fontTools

**不动被锁的 `.pyd`，只补缺失文件：**

```powershell
# 1. 建临时 venv，装同版本干净副本
uv venv $env:TEMP\ft_fix\.venv --python 3.11
uv pip install --python $env:TEMP\ft_fix\.venv\Scripts\python.exe "fonttools==4.63.0"

# 2. 逐文件拷贝，只补不存在的（被锁的 pyd 自动跳过）
$src = "$env:TEMP\ft_fix\.venv\Lib\site-packages\fontTools"
$dst = "D:\git_codes\Autocad-MCP\.venv\Lib\site-packages\fontTools"
Get-ChildItem $src -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($src.Length+1)
    $target = Join-Path $dst $rel
    if (-not (Test-Path -LiteralPath $target)) {
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target
    }
}
# copied=67 failed=0
```

**复核方式（不要只看 `import matplotlib` 是否成功）：**

```python
import importlib, pkgutil, fontTools
bad = []
for m in pkgutil.walk_packages(fontTools.__path__, "fontTools."):
    try: importlib.import_module(m.name)
    except Exception as e: bad.append((m.name, type(e).__name__))
print(len(bad), bad)
```

期望：336 个子模块里只剩 6 个失败，且**全是可选第三方依赖**：

| 模块 | 缺的包 | 是否需要 |
|---|---|---|
| `fontTools.misc.symfont` | `sympy` | 否 |
| `fontTools.pens.freetypePen` | `freetype` | 否 |
| `fontTools.pens.quartzPen` | `Quartz` | 否（macOS） |
| `fontTools.pens.reportLabPen` | `reportlab` | 否 |
| `fontTools.ttLib.removeOverlaps` | `pathops` | 否 |
| `fontTools.varLib.interpolatablePlot` | `cairo` | 否 |

matplotlib 只需要 `fontTools.agl` / `misc.bezierTools` / `ttLib`，全部已恢复。

### 渲染器

新增两个脚本，都不依赖 AutoCAD 窗口：

| 脚本 | 验收的是什么 | 用法 |
|---|---|---|
| `scripts/render_svg.py` | 图层颜色（可卡在构建里） | `--expect A-FURN-E-N=#ff7f00`，不符退出码 1 |
| `scripts/render_mpl.py` | 像素（颜色数、上色比例） | 单色即判失败 |

`render_mpl.py` 里两个坑已封：

```python
# 1. finalize() 会覆盖 figsize
backend = MatplotlibBackend(ax, adjust_figure=False)

# 2. 固定 figsize 会加黑边丢像素，按 extents 算长宽比
size = fitted_size(doc, long_side_in=14.0)
```

---

## 预防

| 规则 | 理由 |
|---|---|
| **见到 OpenBLAS 报错先量内存，别查版本** | 本机只有 15.3 GB，AutoCAD 一开就没余量。版本号是最容易查却最没用的线索 |
| **不要为了渲染升级 numpy** | 它是 MCP 服务自身的运行时依赖，坏升级会把所有工具一起弄挂——这次就是活例 |
| **升级 venv 里的包之前先确认没有进程持有它** | MCP 服务长期驻留并加载了 `bezierTools.pyd`，任何升级都会被拒；而且 pip 是**先删后装**，删到一半失败就留下坏包 |
| **修半删的包：只补缺失文件，别整包覆盖** | 被锁的 `.pyd` 覆盖不了，整包 `--reinstall` 必然失败 |
| **验收要遍历子模块，不能只看顶层 `import`** | `import fontTools` 成功，`import fontTools.agl` 照样可以失败 |
| **渲染图不能当字形证据** | ezdxf 对缺失字形静默回退。字形只能用 `text_glyphless`（需 AutoCAD）或真实 PDF/操作者屏幕判断 |
| **渲染器不放进 text-overlap 技能** | 那个技能的职责包含 `text_glyphless`，而渲染器会把同一张图的缺陷画得「正常」，放一起会教错 |