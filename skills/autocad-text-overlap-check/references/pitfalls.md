# Pitfalls that make a check silently wrong

Every entry below was found the hard way — by a report that looked plausible and
was wrong. They are ordered by how much damage they do, not by how hard they are.

The common thread: **none of them raise an exception.** A broken measurement here
produces a confident number, and the number is used to judge a drawing.

## 1. `ezdxf.bbox` on MTEXT is wrong by a factor of six

`ezdxf/disassemble.py` reads group 41 and passes it to `text_wrap`:

```python
box_width = mtext.dxf.get("width", 0)              # 0.0 means "do not wrap"
return text_wrap(text, box_width, font.text_width)  # 0.0 used as a width
```

`text_wrap` tests `get_text_width(line) > box_width`. Everything is wider than 0,
so **every token becomes its own line**. Measured on handle `3B6`, one 40-character
note at char height 265:

| | height | width | lines |
|---|---|---|---|
| ezdxf | **2534** | **5489** | 6 |
| AutoCAD | **374** | **11732** | 1 |

Six times too tall, half as wide. On the 310-text sample this produced 30 phantom
text-on-text findings and 51 phantom curve crossings.

**Do:** build the box from glyph outlines yourself, and honour group 41 only when
it is `> 0`.

## 2. A full-path font name silently degenerates the metrics

```python
fonts.make_font("simhei.ttf", 400, 1.0)                      # baseline=11.56, 国 ink 520.2
fonts.make_font(r"C:\Windows\Fonts\simhei.ttf", 400, 1.0)    # baseline=0.00, 国 ink 349.2
```

Both return `TrueTypeFont`. Nothing warns. Every CJK width comes out **33% short**.

This is not hypothetical: assigning a font through COM writes the full path into
the DXF style (`style.fontFile = r"C:\Windows\Fonts\simhei.ttf"`), so drawings
touched by the MCP tools carry exactly this form.

**Do:** `os.path.basename()` before handing a font name to ezdxf.

## 3. `font.measurements.total_height` and `.baseline` are unreliable

Same char height, different fonts disagree, and some `.ttc` collections report
`baseline = 0`:

| font | char_height | `total_height` |
|---|---|---|
| simhei.ttf | 350 | 424.9 |
| simsun.ttc | 350 | 424.0 |
| msyh.ttc | 350 | **465.0** (and `baseline=0`) |

**Do:** measure the `A` glyph's outline. `font.text_path("A").extents()` height
equals `char_height` for every font tested — that is the definition AutoCAD uses
for `char_height`.

## 4. AutoCAD reports the glyph *ink* box, not the font's advance width

```
character "1":  AutoCAD 0.298 em   |   font advance 0.740 em
```

`1` has whitespace on both sides; AutoCAD boxes only what prints.

**Do:** use `text_path(text).extents()`, never `text_width()`.

## 5. MTEXT line pitch is 5/3 of the char height, not 1.0

DXF group 44 absent or `1.0` means AutoCAD's "3-on-5" spacing:

```
2 lines @ 265:  706.7 = 265 + 5/3 × 265          ✓
3 lines @ 200:  866.7 = 200 + 2 × 5/3 × 200      ✓
```

Using 1.0 makes every multi-line note too short, so a note crossing a wall is
missed.

**Do:** `height = line_ink + cap × (5/3) × (lines - 1)`.

## 6. Attachment points 7/8/9 point the other way

1-3 anchor the insertion point on the **top** edge (box hangs down), 4-6 centre,
7-9 anchor on the **bottom** edge (box stands up). A first version treated all
nine as top-anchored; the 7-9 boxes landed 505 units low at char height 250.

**Comparison of width and height alone cannot see this** — the box is the right
size in the wrong place. Only absolute coordinates reveal it.

**Do:** compare **corners**, not sizes, when testing alignment.

Related: setting `AttachmentPoint` over COM makes AutoCAD rewrite the insertion
point to keep the text visually still. The `insert` read back from DXF is
already the anchor, so validate against the DXF value.

## 7. Rotation gets applied **twice** when you re-derive it from the matrix

An earlier note in this project said `transform()` "drops rotation". **That was
wrong.** `transform()` folds the reference's rotation into the entity — MTEXT into
`text_direction`, TEXT into `rotation` — on top of whatever the member already
had.

The bug that actually happened was adding the block's angle again *after*
`transform()`. For MTEXT that was harmless only because `rotation` is absent once
`text_direction` is set, so the base being added to was 0 — which is why the block
tests passed. For TEXT the base was the already-correct 65, and the box came out
at 110°.

The regression test is `test_rotation_is_not_applied_twice`, which asserts the
box's height/width ratio is 1.4–2.2 (the 65° shape), not ~2.75 (110°).

Mirrored or non-uniform transforms cannot be expressed as an axis-aligned box at
all — report them as `not_checked`.

## 7a. `entity.transform()` keeps scale too

An earlier reading of the same experiment concluded "scale survives, rotation is
lost". Scale does survive, and so does rotation — the observation was an artefact
of reading `rotation` instead of `text_direction`. Do not write code against the
old conclusion.

## 8. `virtual_entities()` returns no ATTRIB

Block attributes — the per-insertion values, device tags above all — are absent:

```
virtual_entities(): [('MTEXT', 'FIXED')]   # the ATTRIB is not there
insert.attribs:     2 attributes, neither in the result
```

**Do:** read `insert.attribs`. Their `insert` / `rotation` / `height` are
**already in WCS and already scaled**; applying the block matrix again doubles
the transform.

## 9. Table cells live in an anonymous `*T` block

`ACAD_TABLE` draws nothing itself — cells are MTEXT and rules are LINEs, all
inside a block named by `block_record_handle`:

```
TABLE 49C  block_record_handle=49D  ->  block *T19: {'MTEXT': 31, 'LINE': 15}
```

Skip it and three whole schedules vanish from the report.

**And:** place them with the table's own `insert` plus its
`horizontal_direction` rotation. A first version used `Matrix44()` — the
identity — and stacked all 55 cells at the origin, producing 54 findings at
ratio 1.000. The matrix is:

```python
Matrix44.z_rotate(horizontal_direction_angle) @ Matrix44.translate(table.dxf.insert)
```

## 10. A dimension's `*D` block mixes units

Inside `*D`, positions are drawing units and decoration is style units:

| element | measured | unit |
|---|---|---|
| extension line span | 500.625 | drawing units |
| dimension line span | 2115 | drawing units (matches the 2120 measured value) |
| arrowhead length | 2.534 | = `DIMASZ` 2.5, style units |
| text height | 2.5 | = `DIMTXT` 2.5, style units |
| extension offset | 0.625 | = `DIMEXO` 0.625, style units |

Scaling the whole block moves the text away; using 2.5 raw makes it invisible.

**Do:** take the *shape* from the block's ink box, set the drawn height to
`DIMTXT × DIMSCALE`, and centre it on `text_midpoint` (which is already correct).

`123_check.dxf` has `$DIMSCALE = 50`, so the drawn height is `2.5 × 50 = 125`,
matching the file's other text (120–250).

## 11. `GetBoundingBox` never includes dimension or leader text

Proven twice:

- six `DIMTXT` × `DIMSCALE` combinations (2.5/25/125 × 1/50/200) all returned
  **1000 × 203.1** — the geometry box only.
- three MULTILEADERs at text heights 0.18 / 1.0 / 10 all returned **817 × 805**.

So AutoCAD cannot be used as ground truth for dimension text. The `*D`-block
derivation in item 10 is the only route.

MULTILEADER text lives in `context.mtext.default_content`, with the height in
`context.char_height × context.scale`. `explode()` yields only a HATCH and the
leader polylines.

## 12. Rotated text is not an outlier

`text_scale` first compared axis-aligned box heights. Two 90°-rotated
`封闭冷通道` labels had 1627-high boxes against a normal 348, and were reported
as scale defects. `1627 / 348 = 4.68`, just past the 4× threshold.

**Do:** compare `char_height` — the authored height, independent of rotation —
not the box height. `_natural_height()` returns exactly that.

## 13. `SKIPPED_TYPES` does not mean "skip the text"

`INSERT`, `TABLE`, `DIMENSION` and `LEADER` are in the skipped set so their own
geometry is not tested against text. Their **text** is still read through the
block expansion. Do not "fix" this by removing them from the set — the fix is
in the expansion path.

## 14. An empty result is the easiest thing to be wrong about

A drawing whose labels all live in blocks reported `{'texts_total': 0,
'by_kind': {'text_text': 0}}` — a clean bill of health for a completely unread
file.

The same trap reappeared in the test suite: a test that could not find its
fixture printed `SKIP` and returned, so the run still ended `PASS: all tests`
while the claim that test exists to pin went unchecked. Once the fixture is
committed, a missing file is a broken checkout — **make it fail**.

**Do:** count what was read and what was skipped, and print both. `detect()`
returns `texts_measured`, `texts_in_blocks`, `containers`, and `not_checked`;
`__main__` prints the `not checked` list before the findings. This is AGENTS.md
rule 6 — an incomplete scan is not a pass.

## 15. A text style is not on the entity when it is `Standard`

`entity.dxf.get("style", "")` returns `""` for a text that carries no style
attribute — and DXF says that means `Standard`. Measured on
`draw_test/123.dxf`: 136 of 142 texts have the attribute absent, so the report
said "no style" for almost every label and hid that they all land in
`Standard` — the style whose font is `txt.shx` and which therefore cannot draw
their `²`.

**Do:** `_style_of()` substitutes `Standard` for empty. Anything comparing
styles must do the same or it will miss the most common style in the file.

## 16. A dimension's effective scale is the style's, not the header's

`$DIMSCALE` in the header is not what draws an existing dimension. Measured on
`draw_test/123.dxf`: header `$DIMSCALE = 50`, style `ISO-25` `dimscale = 1.0`, and
the 18 dimension texts rendered 2.0 units tall. Writing 50 into the style took
`text_scale` to zero; the header had said 50 all along and changed nothing.

**Do:** when a `text_scale` finding is dimension text, read and fix
`dimstyle.dxf.dimscale`. Do not report "the header is already 50, so it is fine".

## 17. `txt.shx`'s missing glyphs cannot be detected from font metrics

Every programmatic route to "does this font have `²`" gives the wrong answer:

| approach | what it says | why it is wrong |
|---|---|---|
| `fontTools` cmap | `simhei.ttf` has **no** U+00B2 | AutoCAD renders `m²` in it: TrueType falls back, SHX does not |
| ezdxf `make_font(...).text_path("²")` | always renders, even for `txt` | a missing font silently becomes the default font |
| width of the char vs a space | non-zero for both | a fallback glyph and a drawn glyph both have advance |

So the check is **not** based on glyph introspection. It flags the one case that
is documented and screenshot-verified — an SHX style with no big font — and
leaves TrueType alone. Anything else would be a guess wearing a number.

## Why these numbers

| constant | value | why exactly this |
|---|---|---|
| `TEXT_TEXT_MIN_RATIO` | 0.15 | Share of the **smaller** box. Using the union dilutes a long note over a short axis label. 15% lets tight table padding through. |
| `CORE_INSET` | 0.05 | Curves must cross the box's inner core, so an underline, a frame, or a leader tip touching the edge does not fire. Cutting through the glyphs still does. |
| `TEXT_SCALE_TOLERANCE` | 4.0 | The real defect this catches is 50× (`$DIMSCALE` 1 vs `$DIMTXT` 2.5 → 2.5-unit text among 125-unit labels). 4× leaves room for deliberate emphasis without catching rotated boxes (fixed separately in item 12). |
| `TEXT_SCALE_MIN_SAMPLES` | 5 | Below five texts there is no meaningful median. |
| `DUPLICATE_TOLERANCE` | 0.25 | Two texts match when content is identical **and** boxes are within a quarter text height. Zero misses a paste that landed one unit off; a full height would merge genuinely separate labels. |
| `ISO_3098_MIN_TEXT_MM` | 2.5 | ISO 3098 minimum lettering height, and the same constant `engineering/critique.py` uses, so this check and the project's critique agree. |
| `_glyphless_style` | SHX + no bigfont | The only glyph-coverage rule that can be justified: an SHX stroke font's table is fixed, a big font is exactly what adds CJK, and TrueType's fallback makes any cmap test wrong (item 17). |
| `FLATTEN` | 0.5 | Chord deviation when flattening arcs, in drawing units — fine enough that a curve-through-text test does not miss a shallow crossing. |
| `MAX_BLOCK_DEPTH` | 8 | Deeper nesting is reported as skipped rather than silently truncated. |
| `_WIDTH_RATIO` | per font | See [accuracy.md](accuracy.md). |
| `_THREE_ON_FIVE` | 5/3 | See item 5. |
| `GROUP_X_OVERLAP` | 0.5 | Two lines of one label share most of their horizontal extent. Below half, unrelated labels stacked in neighbouring rooms start grouping. |
| `GROUP_MAX_GAP` | 1.0 | One text height. A label's lines sit immediately on top of each other; a wider gap means a separate label. |

## 18. Grouping by proximity fuses a collision into a "label"

A stacked label's lines must move together, but two texts that **overlap** look
almost identical to two texts that are **stacked** - same layer, same style,
horizontal overlap. Grouping them produced one "fix" that shifted both by the
same vector and left the collision exactly where it was. Measured on
`planted.dxf`: `CRAC-01 40kW` and `精密空调` overlap each other by 41%.

**Do:** require the vertical clearance positively - `_intersection` must be
`None`. Two overlapping texts are a collision to report, never a label to shift.

## 19. "Boxed in on every side" was the wrong explanation

One fallback note hid three different situations, and only one of them suggested
the right action. Measured on `gpu_dc_100.dxf`: the area row is 6026 units wide,
the widest free slot beside it is 1159, and it needs 1916 units of travel to
clear the axis. No translation can ever work; the actionable advice is "split
it".

**Do:** compute the free slot on each side before claiming a text is boxed in.
`_no_shift_reason` returns one of three messages, each naming its own fix.

## 20. A single-line fix on a multi-line label ruins the alignment silently

`253` (`GPU 智算机房`) can be nudged 324 units right and the collision clears -
but the area row under it stays put, so the label comes out ragged. Nothing in
the note said so.

**Do:** when only part of a group can move, set `moves_alone` and name the
handles that stay. The fix is still worth printing; it just must not look free.

## Adding a check

1. Return `Finding` objects with `kind`, `handle`, `layer`, `text`, `box`, and
   `where` filled in. A finding without a handle cannot be acted on.
2. Register the kind in `detect()`'s `by_kind` dict **and** in
   `__main__._human`'s summary, or the count is invisible.
3. Anything you cannot measure goes into `not_checked` with a reason. Never
   drop it.
4. Write a test that fails if the check silently returns nothing: one positive,
   one near-miss that must stay quiet.
5. If the value comes from AutoCAD, capture it in
   `draw_test/overlap_proto/verify/` as a CSV before changing the code. See
   [verification.md](verification.md).