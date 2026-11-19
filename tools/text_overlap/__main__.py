"""Command line for the text-overlap check.

    python -m tools.text_overlap FILE.dxf [--layout Layout1] [--json] [--quiet]

Exit codes: 0 = no overlap found, 1 = overlaps found, 2 = could not read the
file. This is what the ``autocad-text-overlap-check`` skill calls.

``--json`` writes the report to stdout so a caller can act on handles; the
human form groups the findings and prints one line per collision.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .overlap import detect

#: A Chinese Windows console is GBK, which cannot encode `²`, `Ø` or `±` — every
#: one of which appears in real drawing text. Printing a report then died with
#: `UnicodeEncodeError: 'gbk' codec can't encode character '\xb2'` *after* the
#: check had already succeeded, turning a good result into a crash. Re-encode
#: the streams as UTF-8 and, if the terminal still cannot show a glyph, print a
#: replacement rather than lose the whole report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - redirected streams
        pass


def _human(report: dict) -> str:
    lines = [
        f"{report['path']}  [{report['layout']}]",
    ]
    if report.get("source"):
        # Say how a DWG was read. Otherwise the temp DXF is invisible and the
        # report looks like it came from the DWG directly.
        lines.append(f"  {report['source']}")
    lines += [
        f"  measured {report['texts_measured']} text entities "
        f"({report['texts_total']} in the space, {report['texts_in_blocks']} from "
        f"{report['containers']} block/table container(s)), {report['curves']} curves",
    ]
    findings = report["findings"]
    counts = report["by_kind"]
    # A grouped finding (text_scale / text_illegible / text_glyphless /
    # text_hidden) is one row for many texts. Counting rows alone understates the
    # damage: `gpu_dc_100.dxf` has 6 illegible rows covering 129 texts, and
    # "6 too small" reads as six labels.

    def label(key: str, text: str) -> str:
        rows = counts[key]
        if not rows:
            return ""
        group = sum(f.get("affected_texts", 1) for f in findings if f["kind"] == key)
        if group > rows:
            return f"{rows} {text} ({group} texts)"
        return f"{rows} {text}"

    parts = [part for part in (
        label("text_text", "text-on-text"),
        label("text_curve", "text-on-geometry"),
        label("text_scale", "off-scale"),
        label("text_hidden", "on hidden layers"),
        label("text_duplicate", "duplicate"),
        label("text_illegible", "too small on paper"),
        label("text_glyphless", "with unplottable glyphs"),
    ) if part]
    # Every kind `detect()` knows about must appear here, or a finding count
    # silently disappears from the summary while still being in the list.
    listed = sum(counts[kind] for kind in (
        "text_text", "text_curve", "text_scale", "text_hidden",
        "text_duplicate", "text_illegible", "text_glyphless",
    ))
    summary = ", ".join(parts) if parts else "all clean"
    lines.append(f"  {len(findings)} finding(s): {summary}")
    if listed != len(findings):
        # A new kind was added to `detect()` and not to the summary above.
        lines.append(f"  {len(findings) - listed} finding(s) of unsummarised kind(s)")
    if report["not_checked"]:
        lines.append(f"  not checked ({len(report['not_checked'])}):")
        for reason in report["not_checked"][:10]:
            lines.append(f"     - {reason}")
        if len(report["not_checked"]) > 10:
            lines.append(f"     ... and {len(report['not_checked']) - 10} more")
    if not findings:
        return "\n".join(lines)

    lines.append("")
    for index, finding in enumerate(findings, 1):
        where = finding.get("at")
        spot = f" at ({where[0]:.0f}, {where[1]:.0f})" if where else ""
        lines.append(f"  {index}. {finding['kind']}{spot}")
        style = finding.get("style")
        tag = f" [style {style}]" if style else ""
        lines.append(
            f"     {finding['handle']} [{finding['layer']}] "
            f"{_excerpt(finding['text'])}{tag}"
        )
        other = finding.get("with")
        if other:
            label = other["type"]
            if other.get("text") is not None:
                label += f" {_excerpt(other['text'])}"
            other_tag = f" [style {other['style']}]" if other.get("style") else ""
            lines.append(
                f"     crosses {other['handle']} [{other['layer']}] {label}{other_tag}"
            )
        if finding.get("overlap_ratio") is not None and finding["kind"] == "text_text":
            lines.append(f"     overlap {finding['overlap_ratio'] * 100:.0f}% of the smaller box")
        if finding.get("in_block"):
            lines.append(f"     text is inside block reference {finding['in_block']}")
        if finding.get("note"):
            lines.append(f"     note: {finding['note']}")
        fix = finding.get("fix")
        if fix:
            if fix.get("tool") == "cad_batch":
                steps = fix["args"]["steps"]
                offset = steps[0]["args"]
                lines.append(
                    f"     fix: cad_batch of {len(steps)} entity_move step(s), "
                    f"each dx={offset['dx']}, dy={offset['dy']}  -> {fix['moves']}"
                )
                for member in fix.get("moves_with", []):
                    excerpt = _excerpt(member["text"], 40)
                    lines.append(f"          moves {member['handle']} {excerpt}")
                if fix.get("verified"):
                    lines.append(f"          verified: {fix['verified']}")
                if fix.get("note"):
                    lines.append(f"          {fix['note']}")
            elif fix.get("tool") == "entity_move":
                args = fix["args"]
                lines.append(
                    f"     fix: entity_move(handle={args['handle']!r}, "
                    f"dx={args['dx']}, dy={args['dy']})  -> {fix['moves']}"
                )
                if fix.get("verified"):
                    lines.append(f"          verified: {fix['verified']}")
                if fix.get("note"):
                    lines.append(f"          {fix['note']}")
            elif fix.get("tool") == "entity_delete":
                args = fix["args"]
                lines.append(f"     fix: entity_delete(handle={args['handle']!r})")
                if fix.get("note"):
                    lines.append(f"          {fix['note']}")
            elif fix.get("note"):
                # The prefix has to match the reason: a block-nested text is not
                # "boxed in", it simply has no movable handle here.
                prefix = "" if fix.get("tool") is None and "block" in fix["note"] else "no safe shift: "
                lines.append(f"     {prefix}{fix['note']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _excerpt(text: str, limit: int = 60) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="text-overlap",
        description="Report text that overlaps other text or drawing geometry.",
    )
    parser.add_argument(
        "path", help="a DXF file, or a DWG (read through a running AutoCAD)"
    )
    parser.add_argument("--layout", default=None, help="layout name; default Model")
    parser.add_argument("--json", action="store_true", help="write the report as JSON")
    parser.add_argument(
        "--quiet", action="store_true", help="exit code only, print nothing unless JSON"
    )
    parser.add_argument(
        "--no-blocks",
        action="store_true",
        help="do not expand block references (their text is then reported as not checked)",
    )
    parser.add_argument(
        "--no-com",
        action="store_true",
        help="refuse to touch a running AutoCAD; a DWG is then an error",
    )
    args = parser.parse_args(argv)

    temp_dxf = None
    report = None
    try:
        source = args.path
        how = None
        if args.path.lower().endswith(".dwg"):
            # Reading a DWG is not part of the check - it is a conversion that
            # needs a live AutoCAD. Announce it: opening a document in the
            # user's session is visible, and an unexplained one looks like the
            # tool did something it was not asked to do.
            if args.no_com:
                print(
                    f"error: {args.path} is a DWG and --no-com was given. A DWG "
                    "needs a running AutoCAD to read (no ODA here). Save a DXF "
                    "and check that.",
                    file=sys.stderr,
                )
                return 2
            from .dwg import DwgUnavailable, to_dxf

            try:
                temp_dxf, how = to_dxf(args.path)
            except DwgUnavailable as exc:
                print(f"error: cannot read {args.path} as a DWG.", file=sys.stderr)
                print(f"  {exc}", file=sys.stderr)
                print(f"  do this: {exc.remedy}", file=sys.stderr)
                return 2
            source = temp_dxf

        report = detect(source, layout=args.layout, expand_blocks=not args.no_blocks)
        if how:
            report["source"] = how
            report["path"] = args.path
    except FileNotFoundError:
        print(f"error: no such file: {args.path}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: could not read {args.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if temp_dxf:
            # to_dxf() returns a path inside its own temp directory; remove the
            # whole directory so a failed run leaves no `tc_dwg_*` behind.
            import shutil

            shutil.rmtree(os.path.dirname(temp_dxf), ignore_errors=True)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(_human(report))
    return 0 if not report["findings"] else 1


if __name__ == "__main__":
    sys.exit(main())