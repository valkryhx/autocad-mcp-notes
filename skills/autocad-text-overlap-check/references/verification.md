# Verifying a change

Two things need verifying and they are different: that a **drawing** was really
fixed, and that a **code change** did not break the checker.

## Verifying a fix in a drawing

Never trust a fix measured in memory. In DXF terms that means:

```bash
# 1. write the fixed geometry out
python -m tools.text_overlap before.dxf          # note the findings
#    ... apply entity_move / ERASE / DIMSCALE ...
drawing_save_as("after.dxf")

# 2. re-run on the saved file and compare the same handles
python -m tools.text_overlap after.dxf
python -m tools.text_overlap after.dxf --json > after.json
```

What to confirm:

- the **handles you fixed** no longer appear in `findings`
- **no new finding** carries a handle you did not touch
- `not_checked` did not grow — a fix that turns text into an unmeasurable
  transform is not a fix

The last one is the one that gets skipped. A move that clears a collision by
pushing text somewhere unmeasurable (`not_checked`) has improved the report and
not the drawing.

For a fix suggested by the tool, the report already states it was tested against
every other box and curve — but re-running on the saved file is what proves the
edit landed.

## Verifying a code change

```bash
cd D:/git_codes/test_Autocad_MCP
D:/git_codes/Autocad-MCP/.venv/Scripts/python.exe tools/text_overlap/tests_overlap.py
```

**24 test functions / 60 assertions, none needing AutoCAD.** They cover the
error paths, every entity type read, blocks (rotated / nested / non-uniform),
tables, dimensions, multileaders, and the regression tests for the bugs listed
in [pitfalls.md](pitfalls.md).

A clean run ends with:

```
PASS: all tests
```

Exit status is non-zero on any failure. `check()` prints `PASS`/`FAIL` per
assertion, so the failing clause is named, not counted.

### The regression tests that matter most

| test | what it protects |
|---|---|
| `test_rotation_is_not_applied_twice` | asserts the box's height/width ratio lands in 1.4–2.2 (a 65° shape). The broken double-rotation version measured ~110°, which is outside that band. Both TEXT and MTEXT are covered, because the bug hit only TEXT. |
| `test_boxed_in_text_gets_no_fix` | a text surrounded on all four sides must get `fix: None`, never a move that trades one collision for another. |
| `test_fix_is_verified_safe` | the offered shift must not land on another box or curve. |
| `test_non_uniform_block_is_reported` | a block scaled non-uniformly must appear in `not_checked`, not be silently approximated. |
| `test_no_blocks_flag` | `--no-blocks` must say the block text was not checked. |
| `test_merged_table_cells_keep_correct_text` | a merged cell in a real AutoCAD-authored table must read as one cell, correctly placed. |
| `test_illegible_text_uses_viewport_scale` | 160 units is illegible at 1:100 and legible at 1:20, and a model-only file gets no rows. |
| `test_near_miss_is_quiet` | the 15% threshold must not fire on a well-spaced pair. |

## Verifying against AutoCAD

These need AutoCAD 2026 running with COM available:

```bash
cd draw_test/overlap_proto
```

### `crosscheck.py` — box against AutoCAD, character by character

Builds a drawing with 11 known texts through COM, saves it as DXF
(`AcSaveAsType` **61** — without the type argument AutoCAD appends `.dwg`),
measures them, and compares against `GetBoundingBox`.

Expect: width **0.00%** for `simhei.ttf` / `simsun.ttc`, height ≤2.89%,
multi-line height 0.00%, `msyh.ttc` flagged unreliable.

### `anchors.py` — all nine attachment points plus rotation

Builds its own fixture (9 texts at the nine attachment points + one at 90°),
exports `anchors.dxf` and `anchors_bb.csv`, and compares **absolute corner
coordinates**.

Expect: ≤2.89 units at char height 250. Comparing sizes alone would pass a
box that is the right shape in the wrong place — which is exactly the 7/8/9 bug.

### `clean.py` — a drawing with nothing wrong

27 texts, all with clearance. Expect **0 findings**. If this ever reports
anything, the thresholds have drifted.

### `planted.py` — six known defects plus a control group

Expect **6/6 found, and the control group silent**. The control group is what
makes the number mean something: a checker that fired on everything would also
score 6/6.

### The 310-text sample

`verify/com_mtext_bb.csv` holds AutoCAD's own boxes for every text in
`gpu_dc_100.dxf`. Regenerating it:

```python
app = win32com.client.Dispatch("AutoCAD.Application")
doc = app.Documents.Open(r"D:\git_codes\test_Autocad_MCP\draw_test\gpu_dc_100.dxf")
with open("verify/com_mtext_bb.csv", "w", encoding="utf-8") as fh:
    for e in doc.ModelSpace:
        if e.ObjectName == "AcDbMText":
            mn, mx = e.GetBoundingBox()
            fh.write(f"{e.Handle},{mn[0]:.6f},{mn[1]:.6f},{mx[0]:.6f},{mx[1]:.6f}\n")
```

Acceptance after any change to `textbox.py`: the distribution in
[accuracy.md](accuracy.md) must not regress — 89% ≤3%, 97.4% ≤5%, 98.4% ≤8%,
and anchor error still 0.000.

## `accoreconsole` does not work here

`D:\autocad_26\AutoCAD 2026\accoreconsole.exe` on this machine reports
`Version W.60.0.0` and "未授权、运行于评估模式". It **does not execute LISP** —
a script hangs at the `命令:` prompt and `timeout` exits 124.

All AutoCAD ground truth therefore comes from a **running AutoCAD through COM**.
Do not build a verification path on `accoreconsole`.

## Other AutoCAD traps hit while verifying

| symptom | cause | fix |
|---|---|---|
| `x.dxf.dwg` instead of `x.dxf` | `SaveAs` without a type | `doc.SaveAs(path, 61)` |
| "文件处理器错误" setting a style font | COM needs the full path | `style.fontFile = r"C:\Windows\Fonts\simhei.ttf"` |
| COM wedged, `被呼叫方拒绝接收呼叫` | modal state left by a failed call | `taskkill //F //IM acad.exe`, let it restart, then re-check `drawing_info` — **do not resend** the failed call |
| a check "passes" against stale data | `USERS1` persists across LISP calls; a failed expression leaves the previous value | verify with ezdxf reading the file or `drawing_info`, not with a LISP return value |
| dimension text never appears in `GetBoundingBox` | it is not geometry | derive from `*D`; see [pitfalls.md](pitfalls.md) item 11 |

## Checklist before reporting a change

- [ ] `tests_overlap.py` → `PASS: all tests`
- [ ] the fixed drawing re-checked **on the saved file**
- [ ] `not_checked` did not grow
- [ ] if `textbox.py` changed: the 310-text distribution did not regress
- [ ] if the fix suggestions changed: `planted.py` still reports 0 false
      positives, and `clean.py` is still 0 findings