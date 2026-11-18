# Where the files are

## The skill

```
skills/autocad-text-overlap-check/
├── SKILL.md                      the entry point; six checks, run command
├── references/
│   ├── reading-a-finding.md      report format, per-kind guidance, fixes
│   ├── what-not-to-fix.md        normal drafting that gets reported
│   ├── accuracy.md               the measured numbers and their provenance
│   ├── pitfalls.md               14 ways the check goes silently wrong
│   ├── verification.md           test suite, AutoCAD cross-checks
│   └── layout.md                 this file
└── assets/
    ├── sample-report.txt       a real report (human form), for testing a reader
    └── findings.json           the same run as --json
```

Installed copy: `~/.claude/skills/autocad-text-overlap-check/`. Re-sync after
editing the repo copy — the two do not follow each other.

## The code

```
tools/text_overlap/
├── __init__.py        re-exports detect, Finding, TEXT_TYPES
├── __main__.py        the CLI: argument parsing, human and --json output
├── textbox.py         the measured text box (the accuracy lives here)
├── overlap.py         the six checks, block/table/dimension readers, fix search
├── README.md          short usage note for the tool on its own
└── tests_overlap.py   24 functions / 60 assertions, no AutoCAD needed
```

`textbox.py` and `overlap.py` are separate on purpose: the box is a measurement
problem with its own calibration, and every check consumes it. A change to
`textbox.py` invalidates every accuracy claim, so keeping it isolated makes that
risk obvious.

## The verification fixtures

```
draw_test/overlap_proto/
├── clean.py           27 well-spaced texts -> must report 0
├── planted.py         6 planted defects + a control group -> 6/6, 0 false
├── crosscheck.py      11 COM-built texts vs GetBoundingBox
├── anchors.py         9 attachment points + 90° rotation, compares corners
└── verify/
    ├── com_mtext_bb.csv   310 AutoCAD boxes, the ground truth
    ├── anchors_bb.csv     the nine anchor boxes
    ├── clean.dxf          the clean fixture
    ├── planted.dxf        the planted-defect fixture
    ├── anchors.dxf        the anchor fixture
    ├── merged_table.dxf   a real 5x3 table with merged cells, AutoCAD-authored
    ├── mleader.dxf        MULTILEADER fixtures
    └── ml_h.dxf
```

`com_mtext_bb.csv` is the most valuable file here: it is AutoCAD's own answer for
310 real texts, and every accuracy number in
[accuracy.md](accuracy.md) is derived from it. Regenerating it requires a live
AutoCAD; see [verification.md](verification.md).

`merged_table.dxf` is the reason the table-merge behaviour is known rather than
assumed — it was authored in AutoCAD, not synthesised by ezdxf.

## The prose record

| file | what it holds |
|---|---|
| `docs/20261118-text-overlap-check.md` | the long-form investigation: 13 root causes with measurements, the second round (blocks/tables/dimensions), and how to read the 310-text figure |
| `docs/20261118-text-overlap-guide.md` | the beginner manual: how to read a report, how to execute a fix, which findings to leave |
| `AGENTS.md` §10 | the one-line symptom → cause → fix rows |

The skill is the operational doc; these are the evidence. When a new pitfall is
found, it goes in three places: `references/pitfalls.md` (what to avoid),
`AGENTS.md` §10 (a row you can grep), and a new `docs/yyyymmdd-*.md` if the
investigation was long enough to be worth its own file — per AGENTS.md §11.

## Editing this skill

- **`SKILL.md` stays short.** It is a router: run command, the six checks in one
  table, and where to read next. Detail belongs in `references/`, or the skill
  stops being scannable.
- **Every reference file must be reachable from `SKILL.md`.** A file nobody is
  pointed at is a file nobody reads.
- **Numbers in `accuracy.md` are measurements, not estimates.** If you change
  `textbox.py`, re-measure against `com_mtext_bb.csv` and update them; do not
  round them into something that sounds tidier.
- **Do not duplicate content between files.** A pitfall explained twice drifts
  apart. `pitfalls.md` owns the failure modes; `reading-a-finding.md` links to
  it rather than restating it.