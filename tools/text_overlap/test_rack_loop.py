"""Read back CAD geometry. Decorative loop lines are deliberately absent."""

import ezdxf
import pytest
from tools.text_overlap import detect
from tools.text_overlap.test_circulation import plan


def fixture(tmp_path, door=False, pos=(4400, 1000)):
    path = plan(tmp_path, left=door)
    doc = ezdxf.readfile(path)
    model = doc.modelspace()
    block = doc.blocks.new("CAB")
    block.add_lwpolyline([(0, 0), (600, 0), (600, 1200), (0, 1200)], close=True)
    for i in range(2):
        r = model.add_blockref("CAB", (pos[0] + 600 * i, pos[1]))
        r.add_attrib(
            "CAB_ID",
            f"C01-{i+1:02}",
            (pos[0] + 600 * i + 80, pos[1] + 400),
            dxfattribs={"height": 75},
        )
    doc.saveas(path)
    return path


def check(path, width):
    return detect(str(path), rack_loop="C01", min_rack_loop_mm=width)


def test_default_opt_out_and_wall_boundary(tmp_path):
    p = fixture(tmp_path)
    assert "rack_loop" not in detect(str(p))
    result = check(p, 900)["rack_loop"]
    assert (
        result["status"] == "pass"
        and result["room_id"] == "a"
        and result["cabinet_count"] == 2
    )
    assert result["clear_mm"] == pytest.approx(900, abs=0.001)
    assert check(p, 901)["by_kind"]["rack_loop_clearance"] == 1


def test_corner_equipment_interrupts_band(tmp_path):
    p = fixture(tmp_path)
    d = ezdxf.readfile(p)
    m = d.modelspace()
    block = d.blocks.new("PLANT")
    block.add_lwpolyline([(0, 0), (200, 0), (200, 200), (0, 200)], close=True)
    obj = m.add_blockref("PLANT", (5900, 2700))
    handle = obj.dxf.handle
    d.saveas(p)
    r = check(p, 600)["rack_loop"]
    assert (
        r["status"] == "fail"
        and r["clear_mm"] == pytest.approx(500, abs=0.001)
        and handle in r["limiting_handles"]
    )


def test_door_uses_quarter_disc_not_enclosing_square(tmp_path):
    # 'low' swings into the lower office, centered at (2500,3900), SE quadrant.
    p = fixture(tmp_path, door=True, pos=(3600, 2400))
    r = check(p, 200)["rack_loop"]
    assert r["status"] == "fail"
    assert r["limiting_kind"] == "door"
    assert 20 < r["clear_mm"] < 100


def test_ambiguous_or_unresolved_never_passes(tmp_path):
    p = fixture(tmp_path)
    d = ezdxf.readfile(p)
    r = list(d.modelspace().query("INSERT"))
    r[1].dxf.insert = (5601, 1000)
    d.saveas(p)
    assert check(p, 500)["rack_loop"]["status"] == "not_checked"
    assert (
        detect(str(p), rack_loop="unknown", min_rack_loop_mm=500)["rack_loop"]["status"]
        == "not_checked"
    )


@pytest.mark.parametrize("width", [0, -1, float("nan"), float("inf")])
def test_width_must_be_explicit_and_valid(tmp_path, width):
    with pytest.raises(ValueError):
        check(fixture(tmp_path), width)


def test_cli_states_and_no_implicit_room_minimum(tmp_path, capsys):
    from tools.text_overlap.__main__ import main

    p = fixture(tmp_path, door=True)
    assert main([str(p), "--rack-loop", "C01", "--min-rack-loop-mm", "700"]) == 0
    assert "C01" in capsys.readouterr().out
    assert main([str(p), "--rack-loop", "bad", "--min-rack-loop-mm", "700"]) == 2
    assert main([str(p), "--rack-loop", "C01"]) == 2


def test_duplicate_id_and_unsupported_obstacle_are_incomplete(tmp_path):
    p = fixture(tmp_path)
    d = ezdxf.readfile(p)
    ref = list(d.modelspace().query("INSERT"))[-1]
    ref.get_attrib("CAB_ID").dxf.text = "C01-01"
    d.saveas(p)
    assert check(p, 500)["rack_loop"]["status"] == "not_checked"
    ref.get_attrib("CAB_ID").dxf.text = "C01-02"
    unknown = d.modelspace().add_line(
        (4300, 900), (4700, 900), dxfattribs={"layer": "TEMP-FENCE"}
    )
    d.saveas(p)
    result = check(p, 500)["rack_loop"]
    assert result["status"] == "not_checked" and unknown.dxf.handle in result["reason"]


def test_wall_evidence_and_no_blocks(tmp_path):
    p = fixture(tmp_path)
    r = check(p, 901)["rack_loop"]
    assert r["limiting_walls"] == ["south"] and r["limiting_handles"]
    assert (
        detect(str(p), expand_blocks=False, rack_loop="C01", min_rack_loop_mm=900)[
            "rack_loop"
        ]["status"]
        == "not_checked"
    )
