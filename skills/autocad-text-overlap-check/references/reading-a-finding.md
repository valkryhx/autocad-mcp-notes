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
| `252 [A-TEXT] CRAC-5 [style CN]` | handle `252`, layer `A-TEXT`, reading `CRAC-5`, text style `CN` |
| `crosses C1 [A-AXIS] LINE` | the other entity: handle `C1`, layer `A-AXIS`, a LINE |
| `fix: entity_move(...)` | a concrete call that clears it |

The `[style ...]` tag is not decoration. A style whose font lacks the glyphs for
the text is a defect in its own right (`text_glyphless`), and the style name is
the thing you have to change — it cannot be inferred from the layer or the
content.

The header before the list tells you the scope, and it is worth reading:

```
  measured 319 text entities (310 in the space, 0 from 0 block/table container(s)), 377 curves
  12 finding(s): 2 text-on-text, 4 text-on-geometry, 6 too small on paper (129 texts)
```

`texts_in_blocks > 0` means block/table contents were expanded and read. If a
drawing has block references and that number is 0, something went wrong — check
`not_checked`.

**A row is not a text.** `text_scale`, `text_hidden`, `text_illegible` and
`text_glyphless` group a whole class into one row each, so the row count
understates the damage. That is what the parenthesised `(129 texts)` is for:
six rows, 129 labels. Never quote the row count as "six problems" when a group
is involved.

## Acting on a `fix`

The `fix` block says exactly what to do. Four shapes:

| `tool` | meaning |
|---|---|
| `entity_move` | shift one entity by `dx`, `dy` |
| `cad_batch` | shift several entities by the **same** vector — a stacked label |
| `entity_delete` | remove a duplicate |
| absent, with a `note` | no move works, and the note says why |

1. **Via the MCP tools** — tell the agent to move it, and it calls
   `entity_move(handle='252', dx=0.0, dy=286.5)`, or runs the whole
   `cad_batch` block for a stacked label.
2. **By hand in AutoCAD** — select the text, `MOVE`, pick any base point, press
   `F8` for ortho, drag the direction, type the distance, Enter.
3. **By editing the property** — `Ctrl+1`, add the delta to X or Y.

Then **save, and run the check again on the saved file.**

### A stacked label moves as one block

Room labels are authored as separate entities stacked in a column — name,
number, area. The tool recognises them (same layer and style, real horizontal
overlap, vertically clear of each other, gap under one text height) and offers
a `cad_batch` that moves every line by the same vector:

```
fix: cad_batch of 2 entity_move step(s), each dx=1145.09, dy=0.0
     moves 8B ROOM NAME
     moves 8C 288.0 m2
```

Run all the steps. Moving one line only would leave the label ragged.

**When the label cannot move as a whole**, the fix for a single line says so:

```
fix: entity_move(handle='253', dx=324.392, dy=0.0)  -> 324.39 drawing units right
     this line belongs to a 2-line label, but the label cannot move as a whole -
     so only 253 moves and 254 stays put. Moving this line alone will leave the
     label misaligned; shortening or re-laying-out the label is the better fix
```

Treat that as a prompt to re-lay-out the label, not as a one-click fix.

### Why the offered shift is trustworthy

- It is tested against **every other text box and every curve in the drawing**,
  not just the one thing it collides with. The naive version — move just clear
  of your collision — was measured to fail: nudging label `D7` 182.5 units up
  cleared its neighbour and dropped it onto a circle.
- It is the **smallest** shift that works, searched outward from a fraction of
  the text's height. Offered shifts on the sample drawings run 286–920 units.
- When no shift works it says so, and gives the reason that decides what to do:

```
no safe shift: no shift can free this text: it is 6026 units wide and the
widest free slot beside it is 1159. Shorten it or split it onto two lines
```

That is not the tool giving up — it tested every direction and distance and
found none clear. **Read which reason you got**, because the fix differs:

| reason | what it means | what to do |
|---|---|---|
| `... units wide and the widest free slot ... is N` | no translation can ever work; the text is wider than the space around it | shorten it, or split it onto two lines |
| `no shift clears this text even when its whole N-line label moves together` | the label was already tried as a unit | move the thing crossing it, or resize the text |
| `something is on every side of it` | genuinely boxed in | move or shorten whatever crosses it |

## Per-kind guidance

### `text_text` — two labels on top of each other

Usually one label placed badly. The fix moves one of them clear. Two axis labels
240 apart with 486-high boxes (the `gpu_dc_100` case) cannot both stay where they
are — one label or one axis spacing has to change.

### `text_curve` — a line through a label

The note gives the crossing count and **how deep the worst one cuts**:

```
note: 2 curve(s) cross this text; the worst one runs 100% of the text height inside the box
note: ARC crosses this text; the worst one runs 40% of the text height inside the box
```

100% means the label is cut clean through — unreadable. A small percentage is a
graze at an edge and may be acceptable. Both are reported because both cross the
inset core, but only the first is certain to need a change.

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

The finding already carries the fix:

```
fix: entity_delete(handle='8DB')
     keep 10F and delete 8DB, or the other way round - the two are identical
     apart from their handle
```

Either one can go; the report names the later of the two only as a default.
Matters for counts: a door schedule that says 4 while the plan shows 5 tags is
usually this.

**The pair is reported once, not twice.** Two coincident texts also trip
`text_text`, and listing both made one defect look like two — measured on
`draw_test/123.dxf`, where two duplicate pairs produced four rows. Only the
`text_duplicate` row survives, because it is the better instruction: a shift
would leave both texts in the drawing.

The check only fires when the boxes **also** coincide, so two rooms both
labelled 走廊 are not reported.

### `text_illegible` — too small once printed

The size is in millimetres **on paper**, derived from the model height divided by
the viewport's scale. A 160-unit label prints at 1.6 mm at 1:100 and 8 mm at
1:20. The note names the culprit so you do not have to work it out:

```
note: 100 text(s) print at 1.6 mm on layout 'Layout1'; ISO 3098 sets the minimum
      at 2.5 mm. The label is 160 units tall, so the viewport scale (1:100) or
      the text height is what to change - not this label alone
```

- If the whole drawing is affected, the viewport scale is wrong — not the labels.
- If a few are, raise just those.
- ISO 3098's minimum is 2.5 mm for lettering; the project's own critique uses
  the same constant (`engineering/critique.py`).

**This is a group, and the group is the message.** 129 texts at 1.5–2.3 mm in one
drawing is a scale decision, not 129 mistakes. Changing the viewport from 1:100
to 1:50 doubles every printed size and fixes all of them at once.

**The usual root cause is a dimension style, not the drawing header.** `$DIMSCALE`
in the file header is not what AutoCAD uses to draw an existing dimension — the
style it references is. Measured on `draw_test/123.dxf`: the header said
`$DIMSCALE = 50` while style `ISO-25` had `dimscale = 1.0`, and its 18 dimension
texts rendered 2.0 units tall against a 125 median. Setting `dimscale = 50` on
the **style** took the finding to zero.

### `text_glyphless` — the characters never plot

```
text_glyphless at (3847, 3662)
   EC [A-ROOM-T-N] 52.92 m² [style Standard]
   note: 7 text(s) use style 'Standard' (font 'txt', no CJK/Unicode fallback)
         and contain '²': those characters do not plot. Point the text at a
         TrueType style (simsun.ttc / simhei.ttf) ...
```

`Standard` is `txt.shx`, a stroke font whose glyph table has no CJK and no
`²`/`Ø`/`±`. AutoCAD stores the string, returns it unchanged, draws nothing, and
does not warn. Every other tool agrees the text is fine, because it is — the
*font* is not.

Note the `[style ...]` tag on the text line. That is why the report prints it:
the fix is a style change, and the style is not visible from layer and content.

**How to fix**

1. In AutoCAD: `STYLE` → pick the style → change the font to a TrueType face
   (`simsun.ttc`, `simhei.ttf`, `msyh.ttc`), or
2. point the offending texts at an existing TrueType style, or
3. edit the style's font in the DXF.

Do **not** rewrite the characters as `%%d` / `%%178` escapes — those are SHX
control codes and they will print literally as `%%d` once the style is TrueType.
Write the Unicode character.

**What is deliberately not flagged:** a TrueType style is never reported, even
when the font's cmap lacks the character. Measured: `simhei.ttf` has no U+00B2 in
its cmap, yet AutoCAD renders `m²` in it — TrueType gets a fallback that SHX does
not. A cmap-based test would raise false alarms, so the check sticks to the
documented, screenshot-verified SHX failure. An SHX style **with a big font** is
also skipped, because a big font is exactly what supplies the CJK glyphs.

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