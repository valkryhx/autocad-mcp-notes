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
        label("opening_blocked", "blocking a door swing"),
        label("solid_overlap", "solid-on-solid"),
    ) if part]
    # Every kind `detect()` knows about must appear here, or a finding count
    # silently disappears from the summary while still being in the list.
    from .circulation import KINDS
    if 'rack_loop' in report:
        from .rack_loop import KIND
        KINDS = (*KINDS, KIND)
        loop = report['rack_loop']
        evidence = (f"可留 {loop['clear_mm']:g} mm，要求 {loop['required_mm']:g} mm" if 'clear_mm' in loop else loop['reason'])
        lines.append(f"  机柜排 {loop['row']} 环道 {loop['status']}，{evidence}")
    for kind in KINDS:
        if counts.get(kind):
            parts.append(f"{counts[kind]} {kind}")
    listed = sum(counts[kind] for kind in (
        "text_text", "text_curve", "text_scale", "text_hidden",
        "text_duplicate", "text_illegible", "text_glyphless",
        "opening_blocked", "solid_overlap", *KINDS,
    ))
    summary = ", ".join(parts) if parts else ("no findings in checked scope" if report["not_checked"] else "all clean")
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
    access = report['circulation']
    if access['status'] == 'not_checked':
        lines.append(f"  circulation: not_checked ({access['reason']})")
    if access['status'] in ('checked', 'partial'):
        lines.append(f"  可达空间 {access['reachable']}/{access['rooms']}，已核对 {len(access['doors'])} 樘平开门（几何连通）。")
        for door in access['doors']:
            side = door['opens_into']
            if 'corridor_id' in door:
                width = door.get('remaining_mm')
                section = f"单扇全开后局部余宽 {width:g} mm" if width is not None else door.get('section_status', '')
                lines.append(f"    {door['id']} [{door['handle']}] 开向 {side}，{section}")
    if not findings:
        return "\n".join(lines)

    lines.append("")
    for index, finding in enumerate(findings, 1):
        where = finding.get("at")
        spot = f" at ({where[0]:.0f}, {where[1]:.0f})" if where else ""
        lines.append(f"  {index}. {finding['kind']}{spot}")
        style = finding.get("style")
        tag = f" [style {style}]" if style else ""
        physical = finding["kind"] in ("opening_blocked", "solid_overlap")
        if finding['kind'] in KINDS:
            lines.append(f"     {finding['handle']} [{finding['layer']}] {finding.get('text', '')} {finding['note']}")
            if finding.get('with'):
                lines.append(f"     关联门弧 {finding['with']['handle']}")
            continue
        if physical:
            # These name two plan objects, not a text and whatever crosses it:
            # there is no text on either side, so the text-shaped lines below
            # would print an empty excerpt and the word "crosses".
            handle = finding["handle"]
            layer = finding["layer"]
            in_block = finding.get("in_block")
            what = (f"block reference {in_block}" if in_block
                    else f"handle {handle}")
            lines.append(f"     {what} [{layer}]")
            other = finding.get("with")
            if other:
                relation = ("stands inside the swing of" if finding["kind"] == "opening_blocked"
                            else "overlaps")
                lines.append(
                    f"     {relation} {other['handle']} [{other['layer']}] {other['type']}"
                )
            if finding.get("note"):
                lines.append(f"     note: {finding['note']}")
            continue
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
    parser.add_argument('--circulation', action='store_true', help='要求检查建筑通行，无法检查时返回 2')
    parser.add_argument('--min-corridor-width-mm', type=float, help='项目规定的门口剩余走廊净宽（mm）')
    parser.add_argument('--corridor-id', action='append', default=[], help='指定走廊房间 ID，可重复')
    parser.add_argument('--rack-loop', metavar='ROW', help='可选，按 CAB_ID 前缀选择机柜排')
    parser.add_argument('--min-rack-loop-mm', type=float, metavar='WIDTH', help='该排四周连续环带所需净宽（毫米）')
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

        report = detect(source, layout=args.layout, expand_blocks=not args.no_blocks,
                        min_corridor_width_mm=args.min_corridor_width_mm, corridor_ids=args.corridor_id,
                        require_circulation=args.circulation, rack_loop=args.rack_loop,
                        min_rack_loop_mm=args.min_rack_loop_mm)
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
    if report.get('rack_loop', {}).get('status') == 'not_checked':
        return 2
    if report["circulation"]["status"] in ("partial", "not_checked") and (args.circulation or args.min_corridor_width_mm is not None or args.corridor_id):
        return 2
    return 0 if not report["findings"] else 1


if __name__ == "__main__":
    sys.exit(main())