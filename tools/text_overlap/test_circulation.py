"""Small saved plans: missing entrance, isolated suite, conflicting swings and a narrow aisle."""

import pytest
import ezdxf
from tools.text_overlap import detect


def plan(tmp_path, *, entrance=True, left=True, right=True, outward=False, width=2000):
    from engineering.arch.model import Wall, Opening, Room, encode, to_payload
    from engineering.arch.walls import wall_geometry_by_wall
    from engineering.arch.openings import opening_prims
    from engineering.mech.primitives import Line

    top = 8000 + width
    d = ezdxf.new("R2013", units=4)
    d.appids.new("ACADMCP_ARCH")
    d.appids.new("ACADMCP_ARCH_H")
    m = d.modelspace()
    walls = [
        Wall("rim", ((0, 0), (8000, 0), (8000, top), (0, top)), 200, closed=True),
        Wall("lower", ((0, 4000), (8000, 4000)), 200),
        Wall("upper", ((0, 4000 + width), (8000, 4000 + width)), 200),
    ]
    ops = []
    if entrance:
        ops.append(Opening("entry", "rim", "door", 8000 + 4250, 1000))
    if left:
        ops.append(
            Opening(
                "low", "lower", "door", 2500, 1100, "in" if outward else "out", "left"
            )
        )
    if right:
        ops.append(
            Opening(
                "up", "upper", "door", 2500, 1100, "out" if outward else "in", "right"
            )
        )
    geom = wall_geometry_by_wall(walls, ops, poche=False)

    def record(e, obj, children):
        e.set_xdata("ACADMCP_ARCH", encode(to_payload(obj)))
        e.set_xdata("ACADMCP_ARCH_H", [(1000, k.dxf.handle) for k in children])

    for w in walls:
        g = geom[w.id]
        es = [
            m.add_line(p.p1, p.p2, dxfattribs={"layer": "A-WALL-E-N"})
            for p in (*g.faces, *g.jambs)
        ]
        record(es[0], w, es)
    for o in ops:
        es = []
        attr = {"layer": "A-DOOR-E-N"}
        for s in opening_prims(next(w for w in walls if w.id == o.wall), o):
            es.append(
                m.add_line(s.p1, s.p2, dxfattribs=attr)
                if isinstance(s, Line)
                else m.add_arc(
                    s.center, s.radius, s.start_deg, s.end_deg, dxfattribs=attr
                )
            )
        record(es[0], o, es)
    for key, name, at in [
        ("a", "Office", (4500, 2000)),
        ("c", "Corridor", (4500, 4000 + width / 2)),
        ("b", "Store", (4500, top - 2000)),
    ]:
        e = m.add_text(
            name, dxfattribs={"insert": at, "height": 100, "layer": "A-ROOM-T-N"}
        )
        record(e, Room(key, name, key, at), [])
    path = tmp_path / "plan.dxf"
    d.saveas(path)
    return path


def test_closed_room_and_isolated_suite(tmp_path):
    r = detect(str(plan(tmp_path, right=False)))
    assert [f["text"] for f in r["findings"] if f["kind"] == "room_no_entrance"] == [
        "Store"
    ]
    r = detect(str(plan(tmp_path, entrance=False)))
    assert {f["text"] for f in r["findings"] if f["kind"] == "room_unreachable"} == {
        "Office",
        "Corridor",
        "Store",
    }


def test_opposed_leaves_and_width(tmp_path):
    p = plan(tmp_path, outward=True)
    r = detect(str(p), min_corridor_width_mm=900)
    assert r["by_kind"]["door_swing_conflict"] == 1
    assert r["by_kind"]["corridor_clearance"] >= 1
    lows = [d for d in r["circulation"]["doors"] if d["id"] == "low"]
    assert lows[0]["opens_into"] == "c" and lows[0]["remaining_mm"] == pytest.approx(
        700
    )
    assert not detect(str(p))["by_kind"]["corridor_clearance"]


def test_room_side_swings_and_tangent(tmp_path):
    r = detect(str(plan(tmp_path)), min_corridor_width_mm=1200)
    assert r["circulation"]["reachable"] == 3 and not any(
        r["by_kind"][k]
        for k in (
            "room_no_entrance",
            "room_unreachable",
            "door_swing_conflict",
            "corridor_clearance",
        )
    )
    r = detect(str(plan(tmp_path, outward=True, width=2400)))
    assert not r["by_kind"]["door_swing_conflict"]


def test_stale_geometry_blocks_verdict(tmp_path):
    p = plan(tmp_path)
    d = ezdxf.readfile(p)
    next(iter(d.modelspace().query("ARC"))).dxf.radius += 999
    d.saveas(p)
    r = detect(str(p))
    assert r["circulation"]["status"] == "not_checked" and r["not_checked"]


def test_corridor_width_when_leaf_opens_away(tmp_path):
    r = detect(str(plan(tmp_path)), min_corridor_width_mm=2000)
    low = next(d for d in r["circulation"]["doors"] if d["id"] == "low")
    assert low["corridor_id"] == "c" and low["opens_into"] == "a"
    assert low["remaining_mm"] == pytest.approx(1800)
    assert r["by_kind"]["corridor_clearance"] == 2


def test_explicit_audit_on_foreign_plan_is_incomplete(tmp_path, capsys):
    from tools.text_overlap.__main__ import main

    p = tmp_path / "foreign.dxf"
    ezdxf.new("R2013", units=4).saveas(p)
    assert main([str(p), "--circulation"]) == 2
    assert "not_checked" in capsys.readouterr().out


def test_cli_names_both_doors(tmp_path, capsys):
    from tools.text_overlap.__main__ import main

    p = plan(tmp_path, outward=True)
    assert main([str(p), "--circulation"]) == 1
    text = capsys.readouterr().out
    assert "door_swing_conflict" in text and "low / up" in text


def test_missing_corridor_not_a_width_pass(tmp_path, capsys):
    from tools.text_overlap.__main__ import main
    from engineering.arch.model import from_payload, encode, to_payload
    from dataclasses import replace

    p = plan(tmp_path)
    d = ezdxf.readfile(p)
    e = next(t for t in d.modelspace().query("TEXT") if t.dxf.text == "Corridor")
    old = from_payload(
        __import__("json").loads("".join(t.value for t in e.get_xdata("ACADMCP_ARCH")))
    )
    e.dxf.text = "C"
    e.set_xdata("ACADMCP_ARCH", encode(to_payload(replace(old, name="C"))))
    d.saveas(p)
    assert main([str(p), "--min-corridor-width-mm", "1200"]) == 2
    assert "not_checked" in capsys.readouterr().out
