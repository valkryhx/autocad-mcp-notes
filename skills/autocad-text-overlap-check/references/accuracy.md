# Accuracy, and why the numbers are trustworthy

Every figure here comes from comparing the checker's box against **AutoCAD's own
`GetBoundingBox`**, taken over COM. Nothing here is the checker validating
itself — that would prove nothing.

## The ground truth

`draw_test/overlap_proto/verify/com_mtext_bb.csv` — 310 rows, one per MTEXT in
`gpu_dc_100.dxf`, each the box AutoCAD itself reported:

```python
app = win32com.client.Dispatch("AutoCAD.Application")
doc = app.Documents.Open(r"...\gpu_dc_100.dxf")
for e in doc.ModelSpace:
    if e.ObjectName == "AcDbMText":
        mn, mx = e.GetBoundingBox()
```

The sample is not a subset — it is every text in that drawing, all in
`simhei.ttf`.

## Box size: 98.4% within 8%

Error is the larger of the width and height error.

| error ≤ | count | share |
|---|---|---|
| 1% | 34 | 11.0% |
| 2% | 60 | 19.4% |
| 3% | 276 | **89.0%** |
| 5% | 302 | **97.4%** |
| 8% | 305 | **98.4%** |
| 15% | 308 | 99.4% |

The tail past 8% is entirely labels containing `m²`:

```
3A3  w 18.72%  h 19.08%  '288 m²'
27A  w 15.96%  h 17.75%  '70.8 m²'
363  w 14.17%  h  2.89%  '面积 (m²)'
```

AutoCAD stacks `²` as a superscript (smaller, raised). The checker lays it inline
at full size. The box therefore comes out **wider, never narrower** — meaning it
can over-report, never under-report. That is the safe direction for a collision
check.

## Box position: exact

Size error and position error are different things and must be reported
separately. Comparing only width and height hides whole classes of bug — the
attachment-point 7/8/9 defect had a *perfectly correct* size and a box one text
height too low.

Measured on the anchor corner/edge of each box:

| metric | result |
|---|---|
| anchor horizontal error, median | **0.000** |
| anchor horizontal error, max | **0.000** |
| anchor vertical error, median | **0.000** |
| anchor vertical error, max | **0.000** |
| boxes exact (rotated ones excluded) | **282 / 282** |

So: **where the text sits is exact; how big the box is, is within 8% and always
errs large.** It is wrong to summarise this as "89% accurate".

The 8% figure is a *size* residual and it appears as a corner offset only because
a wide box has a far corner. The one case that looked like a 222-unit position
error decomposes to:

```
left edge   mine=58000.0   acad=58000.0    <- identical
right edge  mine=68606.0   acad=68383.8    <- 222 wider, from '²'
```

## Calibrated fonts: width is exact

Two fonts are benchmarked against AutoCAD and corrected by a measured constant:

```python
_WIDTH_RATIO = {
    "simhei.ttf": 1.028902,
    "simsun.ttc": 1.022867,
}
```

With the ratio applied, width error is **0.00%** for both (`crosscheck.py`
verifies this on a purpose-built 11-text drawing).

`msyh.ttc` (微软雅黑) is the reverse: 16% narrow, and **no constant fits all
three**. It is listed in `_UNRELIABLE_FONTS`; findings on it carry a note rather
than false confidence.

Uncalibrated fonts are measured from their own glyph outlines and are typically
a few percent wide. They are flagged, not silently trusted.

## Alignment and rotation

`anchors.py` builds a fixture with all nine MTEXT attachment points plus a 90°
rotation and compares **absolute corner coordinates**, not sizes:

| metric | result |
|---|---|
| corner offset | ≤ 2.89 units at char height 250 (≈1.2%) |

Size-only comparison would have passed the broken version, which is why the
fixture compares corners.

## The detector itself

Accuracy of the box is necessary but not sufficient — the thresholds could still
be wrong.

| check | result |
|---|---|
| `clean.py` — 27 texts, all with clearance | **0 findings** |
| `planted.py` — 6 planted defect classes + a well-spaced control group | **6/6 found, 0 false positives** |
| `crosscheck.py` — 11 known texts, AutoCAD-built | width 0.00%, height ≤2.89%, multi-line height 0.00% |
| `gpu_dc_100.dxf` — all 310 texts | 6 findings, each hand-verified as a real defect |

The control group in `planted.py` is what makes the 15% threshold meaningful: a
threshold that fired on everything would also score 6/6.

## The fix suggestions

The offered shift is verified, not guessed. It is tested against **every other
text box and every curve in the drawing**, and the shortest working distance
wins.

Measured failure of the naive approach, on `gpu_dc_100.dxf`: nudging axis label
`D7` up by 182.5 units — just enough to clear neighbour `D2` — put it straight
onto the circle `D1`. `_try_shift` was written because of that.

| metric | result |
|---|---|
| fixes that cleared their collision | **12 / 12** |
| fixes that created a new one | 0 |
| distance range | 286.5 – 920 units |

A text boxed in on all sides gets `fix: None` and a plain explanation, rather
than a move that trades one collision for another.

## The `text_illegible` cross-check

The paper-size computation (model height → mm on sheet, via the viewport's
`view_height / height`) was verified against a real plotted PDF:

| | checker | PDF measurement |
|---|---|---|
| a 10 mm-at-1:10 label | 10 | 10 |
| a 100-unit label | 100 | 100 |

Counts match exactly; a 1.4% residual is explained by the em/cap ratio between
the two measurement conventions. See
[verification.md](verification.md) for how to reproduce.

## What is not verified

- **Fonts other than `simhei.ttf` / `simsun.ttc`** are measured but not
  calibrated. Expect a few percent of extra width.
- **`msyh.ttc`** is 16% off in the opposite direction and unfixable by constant.
- **`²` superscripts** over-report by up to 19%.
- **Non-uniform or mirrored block transforms** produce a parallelogram, which an
  axis-aligned box cannot express. These are reported as `not_checked`, never
  approximated.
- **`explode()` / `virtual_entities()`** were both tried and are wrong in
  different ways; see [pitfalls.md](pitfalls.md).