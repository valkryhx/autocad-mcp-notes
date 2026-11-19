---
name: autocad-text-overlap-check
description: Use for any AutoCAD drawing whose text may collide with other text or with geometry, or that may have text which will not print properly - overlapping labels, a note crossed by a wall or axis, table text running into rules, dimension text too small to read, labels on a switched-off layer, a duplicated tag, or text that prints below the ISO 3098 minimum. Reads text wherever it hides (blocks, attributes, tables, dimensions, multileaders) and reports each finding with handle, layer, text, exact location, and a fix verified not to create a second collision.
---

# AutoCAD text overlap check

A label that overlaps other content is a defect a reader sees immediately and a
CAD check usually misses. This skill ships a measured text box and **seven**
checks built on it.

## Run it

```bash
cd D:/git_codes/test_Autocad_MCP
D:/git_codes/Autocad-MCP/.venv/Scripts/python.exe -m tools.text_overlap FILE.dxf
D:/git_codes/Autocad-MCP/.venv/Scripts/python.exe -m tools.text_overlap FILE.dwg
```

Options: `--json`, `--layout NAME`, `--quiet`, `--no-blocks`, `--no-com`.
Exit code: `0` nothing found, `1` findings, `2` unreadable input.

**A `.dwg` works too**, if AutoCAD is running: the tool converts a *copy* of it
through COM and checks the result. No ODA here, and `accoreconsole` is not
licensed, so a live AutoCAD is the only route. The copy is deliberate — `SaveAs`
re-points the *document*, so running it on a drawing the user has open would turn
their DWG into a temp DXF and delete it. See
[tools/text_overlap/README.md](../../tools/text_overlap/README.md) for the five
safeguards.

Without AutoCAD, `--no-com` or no running instance gives the way out
(`SaveAs(path, 61)`), not just an error.

## Read these next, in this order

| you want to | read |
|---|---|
| know what a report line means, and what to do about it | [references/reading-a-finding.md](references/reading-a-finding.md) |
| know which findings are normal drafting and need no change | [references/what-not-to-fix.md](references/what-not-to-fix.md) |
| understand why the numbers are trustworthy (accuracy, cross-checks) | [references/accuracy.md](references/accuracy.md) |
| fix a wrong measurement, or extend the checker | [references/pitfalls.md](references/pitfalls.md) |
| check that a change did not break the checker | [references/verification.md](references/verification.md) |
| find the tool's own files | [references/layout.md](references/layout.md) |

A real report on a real drawing is in `assets/sample-report.txt` (human form) and
`assets/findings.json` (`--json`), both produced from
`draw_test/gpu_dc_100.dxf`.

## The seven checks

| kind | meaning | needs |
|---|---|---|
| `text_text` | two texts whose boxes intersect by ≥15% of the **smaller** box | — |
| `text_curve` | a curve crossing the inset core of a text box | — |
| `text_scale` | text drawn >4x away from the drawing's median height | ≥5 texts |
| `text_hidden` | text on a layer that is **off or frozen** — it will not print | — |
| `text_duplicate` | the same text twice in the same place | — |
| `text_illegible` | model text that prints below ISO 3098's 2.5 mm | a paper viewport |
| `text_glyphless` | text using an SHX style with no glyphs for its own characters | — |

The last one is the quietest defect of the lot: `Standard` is `txt.shx`, which
has no CJK and no `²`/`Ø`/`±`. AutoCAD stores the string, returns it unchanged
from `entity_list`, draws nothing, and warns nobody. The area label `54.48 m²`
plots as `54.48 m`.

Thresholds are explained in `references/pitfalls.md` under "Why these numbers".

## Where text hides

Skipping any row makes a drawing full of labels report "0 texts, 0 findings" —
an incomplete read passed off as clean.

| where | how it is reached | lost if skipped |
|---|---|---|
| block reference | expanded, nested to 8 deep, transforms applied | every room tag |
| block `ATTRIB` | `insert.attribs` | the text that varies per insertion |
| table cells | the `*T` block via `block_record_handle` | a whole schedule |
| dimension text | its `*D` block, sized `DIMTXT × DIMSCALE` | all dimension values |
| multileader text | `context.mtext.default_content` | leader notes |

Not checked, **by design**: `HATCH` (a filled area often contains a label),
`SOLID`, `POINT`, `LEADER` (no text field of its own), `VIEWPORT`, and a
dimension's own arrows and lines.

## Find something, then fix it

Every collision carries a `fix` — or an explanation of why it has none:

```
fix: entity_move(handle='252', dx=0.0, dy=286.5)  -> 286.50 drawing units up
     verified: tested against every other text box and every curve ...

fix: cad_batch of 2 entity_move step(s), each dx=1145.09, dy=0.0
     moves 8B ROOM NAME
     moves 8C 288.0 m2
     this text is one line of a stacked label, so the lines above and below it
     move with it - moving this line alone always lands on one of them

fix: entity_delete(handle='8DB')
     keep 10F and delete 8DB, or the other way round ...

no safe shift: no shift can free this text: it is 6026 units wide and the
widest free slot beside it is 1159. Shorten it or split it onto two lines

this text lives in block reference 4F5; move or edit it inside the block
definition, not here.  ``entity_move`` needs the handle of a top-level entity
```

**A multi-line label moves as one unit.** Room labels are authored as several
stacked entities (name, number, area). The tool groups them — same layer and
style, horizontal overlap, truly clear of each other vertically, gap under one
text height — and offers a single `cad_batch` so the label cannot end up
half-moved. When the label genuinely cannot travel as a whole, the move offered
for one line says so explicitly and warns that the label will end up misaligned.

Shifts are **tested against every other box and curve** before being offered —
a shift is never suggested on the assumption it will work. The fix is a
suggestion: which entity moves, and whether the crossing is intended, is the
drafter's call. Details in
[references/reading-a-finding.md](references/reading-a-finding.md).

Reported text also carries its **style name**, because that is what fixes a
`text_glyphless` row and it is not visible from layer and content alone.

## Before you claim a change works

Re-run the check **on the saved file**. A fix measured in memory is not a fix.
The checker's own suite is in [references/verification.md](references/verification.md);
36 test functions / 109 assertions run without AutoCAD.

## When the check says nothing

An empty result means *no collision among the entities this check reads*. It
does not mean the drawing is clean: nothing here judges whether the geometry is
correct, whether dimensions match their features, or whether the drawing is
legible to a reader. Say "no text overlap found", never "the drawing is fine".