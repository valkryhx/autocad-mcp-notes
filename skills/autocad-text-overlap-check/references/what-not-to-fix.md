# What not to fix

The checker reports **geometry that overlaps**. It does not know what the
drafter intended. Several findings on a correct drawing are correct findings —
report them, note them as accepted, and move on.

> The tool reports; the drafter decides. Never edit geometry just to make the
> report empty.

## Normal drafting that will be reported

### An axis number sitting on its axis line

An axis/grid bubble and its label are anchored **on** the axis line by
convention. `A-AXIS` / `AXIS` / `DOTE` crossing a label is not a defect.

How to tell it apart: look at the crossing entity's layer in the finding. If it
is an axis layer, it is normal. If it is `A-WALL`, `A-DOOR`, or a table rule,
it is probably real.

**Do this:** leave it, and say so explicitly — "4 text-on-geometry findings,
all axis numbers on their axis lines, accepted as normal practice."

### A label inside a room, crossed by a leader line's tip

`LEADER` is in the never-measured list, but a leader drawn as a plain `LINE` on
an annotation layer will be measured. A leader that points **at** a label and
stops at its edge is fine; one that runs **through** it is not. Check whether
the line ends at the text box or crosses it entirely.

### Dimension text touching its own dimension line

Already excluded: a `DIMENSION`'s own lines and arrows are never tested against
its text. Only *other* entities are. So a dimension text finding is always a
real cross-entity collision, never the dimension's own decoration.

### Underline, frame, or box around a label

The curve check insets each text box by 5% before testing, so an underline
touching the bottom edge, or a frame drawn around a label, does not fire. One
that cuts through the glyphs still will — that one is real.

### Text on a layer that is deliberately off

`text_hidden` fires on off/frozen layers, because text there will not print. If
a layer is off **on purpose** (a construction/reference layer kept in the same
file), the finding is correct but needs no change. Say which layer, and that it
is intentional.

### `m²` / superscript labels measured slightly wide

Text using `²` measures up to 19% wider than AutoCAD's box, because AutoCAD
stacks `²` as a superscript and the checker lays it inline. **The error is always
in the "too big" direction**, so it can produce a finding that AutoCAD would not
— never miss one that AutoCAD would. If a borderline finding involves `m²`,
re-check it visually before editing.

## Findings that look alarming but are not

### `text_scale` on a drawing where every dimension is affected

This is one global setting, not many hand edits. Fixing `$DIMSCALE` once clears
all of them. **Do not resize the individual texts** — that leaves the drawing
with a broken dimension style and correct-looking text, which is worse.

### `text_duplicate` on two rooms both labelled 走廊

Does not fire. The check requires the boxes to coincide as well as the content,
so repeated room names at different locations are silent.

### `text_illegible` on a model-only DXF

Does not fire. Without a paper viewport there is no sheet, so nothing can be
"too small on paper". If the drawing is meant to be plotted, add a layout and
re-run — that is a real gap in the drawing, not a checker failure.

### A finding on an entity you did not expect to have text

`INSERT`, `ACAD_TABLE`, `DIMENSION` and `MULTILEADER` in the *skipped types*
list refers to their own geometry, not their text. Their text is measured via
the block. So a finding whose handle starts with a table handle is a cell, and
one from a dimension's `*D` block is the dimension value.

## What "nothing found" does not mean

An empty report means *no geometry overlap among the entities this check reads*.
It is not a certificate. The checker does **not** judge:

- whether the geometry is correct
- whether dimensions match their features
- whether annotation is complete
- whether the drawing reads well to a human

Report "no text overlap found", never "the drawing is fine".

And if `not_checked` is non-empty, something was **not** measured. Do not call a
drawing clean while that list has entries. See
[reading-a-finding.md](reading-a-finding.md#the-not_checked-list).