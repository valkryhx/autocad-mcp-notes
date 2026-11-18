# Reading a finding

This skill reports findings in a plain-text list (or JSON with `--json`). Each
entry names the text, the thing it collides with, the location, and — where one
exists — a verified way out.

## The shape of an entry

```
3. text_curve at (27600, 27480)
   252 [A-TEXT] CRAC-5
   crosses C1 [A-AXIS] LINE
   note: LINE crosses this text
   fix: entity_move(handle='252', dx=0.0, dy=286.5)  -> 286.50 drawing units up
        verified: tested against every other text box and every curve in this drawing
        one option: moving whatever crosses the text may suit the drawing better
```

| line | meaning |
|---|---|
| `3. text_curve at (x, y)` | finding 3, its kind, and the centre of the offending text box |
| `252 [A-TEXT] CRAC-5` | handle `252`, on layer `A-TEXT`, reading `CRAC-5` |
| `crosses C1 [A-AXIS] LINE` | the other entity: handle `C1`, layer `A-AXIS`, a LINE |
| `fix: entity_move(...)` | a concrete call that clears it |

The header before the list tells you the scope, and it is worth reading:

```
  measured 319 text entities (310 in the space, 0 from 0 block/table container(s)), 377 curves
  6 finding(s): 2 text-on-text, 4 text-on-geometry
```

`texts_in_blocks > 0` means block/table contents were expanded and read. If a
drawing has block references and that number is 0, something went wrong — check
`not_checked`.

## Acting on a `fix`

The `fix` block is an `entity_move` call: which handle, and by how much.

1. **Via the MCP tools** — tell the agent to move it, and it calls
   `entity_move(handle='252', dx=0.0, dy=286.5)`.
2. **By hand in AutoCAD** — select the text, `MOVE`, pick any base point, press
   `F8` for ortho, drag the direction, type the distance, Enter.
3. **By editing the property** — `Ctrl+1`, add the delta to X or Y.

Then **save, and run the check again on the saved file.**

### Why the offered shift is trustworthy

- It is tested against **every other text box and every curve in the drawing**,
  not just the one thing it collides with. The naive version — move just clear
  of your collision — was measured to fail: nudging label `D7` 182.5 units up
  cleared its neighbour and dropped it onto a circle.
- It is the **smallest** shift that works, searched outward from a fraction of
  the text's height. Offered shifts on the sample drawings run 286–920 units.
- When no shift works it says so:

```
no safe shift: no short shift clears this text - something is on every side of it.
Move or shorten whatever crosses it, or resize the text
```

That is not the tool giving up — it tested every direction and distance and
found none clear. The answer is to move or shorten **the other thing**, or
shorten the label.

## Per-kind guidance

### `text_text` — two labels on top of each other

Usually one label placed badly. The fix moves one of them clear. Two axis labels
240 apart with 486-high boxes (the `gpu_dc_100` case) cannot both stay where they
are — one label or one axis spacing has to change.

### `text_curve` — a line through a label

Check the layer of the crossing entity **before acting**:

| crossing layer looks like | usually |
|---|---|
| `A-AXIS`, `AXIS`, `DOTE` | normal — an axis number sits on its axis line |
| `A-WALL`, `WALL` | a real defect — the wall should stop, or the label should move |
| `A-DOOR`, `DOOR` | often real — a door swing across a label is unreadable |
| a table's rule | real — cell text should stay inside its cell |
| `A-TEXT` | two labels, same as `text_text` |

An axis label on its axis line is correct architectural practice. Report it and
leave it, or say explicitly that it was checked and accepted.

### `text_scale` — text far from the drawing's habit

One row per group of same-height text. The typical cause is a **global setting**,
not a hand edit: when every dimension is small at once, `$DIMSCALE` is 1 while
`$DIMTXT` is 2.5. Fix it once:

- command `DIMSCALE`, set it to the plot scale (e.g. 50 for 1:50), or
- `DIMSTYLE` → Modify → Fit → "Use overall scale of" → 50

### `text_hidden` — text that will not print

The layer is off or frozen. In `LAYER` (layer manager) turn the bulb back on or
unfreeze the snowflake. Re-run afterwards: the text may now collide with
something it was previously hiding from.

### `text_duplicate` — the same text twice

Delete one with `ERASE`, then confirm the survivor's content is the right one.
Matters for counts: a door schedule that says 4 while the plan shows 5 tags is
usually this.

Note the check only fires when the boxes **also** coincide, so two rooms both
labelled "走廊" are not reported.

### `text_illegible` — too small once printed

The size is in millimetres **on paper**, derived from the model height divided by
the viewport's scale. A 160-unit label prints at 1.6 mm at 1:100 and 8 mm at
1:20.

- If the whole drawing is affected, the plot scale or the text style is wrong.
- If a few are, raise just those.
- ISO 3098's minimum is 2.5 mm for lettering; the project's own critique uses
  the same constant (`engineering/critique.py`).

## The `not_checked` list

Anything measured as impossible prints a reason instead of being silently
dropped:

```
not checked (2):
   - 2F1 (block 2F0): non-uniform or mirrored transform, text box not measured
   - 3A2 (dimension): no readable text in its block
```

An entry here means that entity was **not** checked. Do not report a drawing as
clean while this list is non-empty without saying so.