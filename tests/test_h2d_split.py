"""H2D dual-nozzle split, using synthetic meshes only.

The numbers under test are the guide's 350 mm plate and 325 mm nozzle reach, and this
repo's catalog placement of the right nozzle at x = 25.
"""
import os
import re
import sys
import tempfile
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import h2d_split  # noqa: E402
import mesh  # noqa: E402
import plates  # noqa: E402

CUBE = np.array([
    [[0, 0, 0], [1, 1, 0], [1, 0, 0]], [[0, 0, 0], [0, 1, 0], [1, 1, 0]],
    [[0, 0, 1], [1, 0, 1], [1, 1, 1]], [[0, 0, 1], [1, 1, 1], [0, 1, 1]],
    [[0, 0, 0], [1, 0, 0], [1, 0, 1]], [[0, 0, 0], [1, 0, 1], [0, 0, 1]],
    [[0, 1, 0], [1, 1, 1], [1, 1, 0]], [[0, 1, 0], [0, 1, 1], [1, 1, 1]],
    [[0, 0, 0], [0, 0, 1], [0, 1, 1]], [[0, 0, 0], [0, 1, 1], [0, 1, 0]],
    [[1, 0, 0], [1, 1, 1], [1, 0, 1]], [[1, 0, 0], [1, 1, 0], [1, 1, 1]],
], dtype=float)


def box(w, d, h):
    out = CUBE.copy()
    out[:, :, 0] *= w
    out[:, :, 1] *= d
    out[:, :, 2] *= h
    return out


def test_limits_and_single_nozzle_regression():
    left = plates.catalog_printer("Bambu Lab H2D · left nozzle", "h2d-left")
    right = plates.catalog_printer("Bambu Lab H2D · right nozzle", "h2d-right")
    assert plates.fits([200, 80, 40], left) is not None
    assert plates.fits([200, 80, 40], right) is not None
    assert plates.fits([418.8, 47, 10], left) is None  # wider than 325 and than 350
    assert h2d_split.fit_angle([418.8, 47, 10]) is None
    assert h2d_split.fit_angle([360, 40, 20]) is None
    assert h2d_split.fit_angle([200, 80, 40]) == 0.0
    assert h2d_split.fit_angle([340, 40, 20]) == 0.0
    assert h2d_split.fit_angle([40, 340, 20]) == 90.0
    # A thin bar can still lie on the left nozzle diagonally. Combined mode does not claim that as a split.
    assert plates.fits([400, 20, 10], left) is not None
    assert h2d_split.fit_angle([400, 20, 10]) is None


def test_cut_conserves_a_box():
    solid = box(340, 100, 20)
    original = h2d_split.mesh_volume(solid)
    left, right = h2d_split.split_mesh(solid, 175)
    assert h2d_split.watertight(left) and h2d_split.watertight(right)
    assert abs((h2d_split.mesh_volume(left) + h2d_split.mesh_volume(right)) - original) < 1e-3
    assert left[:, :, 0].max() <= 175 + 1e-4
    assert right[:, :, 0].min() >= 175 - 1e-4
    # The parts meet. They do not overlap as solids and they do not leave a gap.
    assert abs(left[:, :, 0].max() - right[:, :, 0].min()) < 1e-4
    assert abs(h2d_split.mesh_volume(left) - 175 * 100 * 20) < 1e-2
    assert abs(h2d_split.mesh_volume(right) - 165 * 100 * 20) < 1e-2


def test_placed_split_stays_inside_each_nozzle():
    solid = box(340, 80, 15)
    placed = h2d_split.place_mesh(solid, 1, 2, 0)
    item = {"x": 1, "y": 2, "rot": 0, "w": 340, "d": 80}
    h2d_split.annotate_item(item)
    assert item["nozzle"] == "split"
    cut = item["splitX"]
    assert h2d_split.RIGHT_MIN <= cut <= h2d_split.LEFT_MAX
    halves = h2d_split.split_placed(solid, 1, 2, 0, cut)
    assert halves is not None
    left, right = halves
    assert left[:, :, 0].min() >= -1e-4 and left[:, :, 0].max() <= h2d_split.LEFT_MAX + 1e-4
    assert right[:, :, 0].min() >= h2d_split.RIGHT_MIN - 1e-4 and right[:, :, 0].max() <= h2d_split.PLATE_X + 1e-4
    assert abs(h2d_split.mesh_volume(left) + h2d_split.mesh_volume(right) - h2d_split.mesh_volume(placed)) < 1e-2
    # A part that fits the left nozzle is not split.
    narrow = {"x": 0, "y": 0, "rot": 0, "w": 200, "d": 80}
    h2d_split.annotate_item(narrow)
    assert narrow["nozzle"] == "left" and "splitX" not in narrow
    wide = {"x": 0, "y": 0, "rot": 0, "w": 360, "d": 40}
    h2d_split.annotate_item(wide)
    assert wide["nozzle"] == "unsplittable"


def test_3mf_is_one_object_with_two_nozzles():
    solid = box(340, 60, 12)
    cut = 175.0
    left, right = h2d_split.split_mesh(solid, cut)
    path = os.path.join(tempfile.mkdtemp(prefix="h2d-"), "split.3mf")
    mesh.write_3mf(path, [{
        "name": "synthetic bar",
        "parts": [
            {"name": "synthetic bar · left nozzle", "mesh": left, "extruder": 1},
            {"name": "synthetic bar · right nozzle", "mesh": right, "extruder": 2},
        ],
    }], [{"name": "split", "items": [(0, 0, 0, 0)]}], (350, 320), "h2d split test")
    with zipfile.ZipFile(path) as zf:
        model = zf.read("3D/3dmodel.model").decode()
        cfg = zf.read("Metadata/model_settings.config").decode()
    assert model.count("<item ") == 1  # one object, not two bodies to glue
    assert cfg.count("<part ") == 2
    extruders = re.findall(r'<part id="\d+"[^>]*>.*?<metadata key="extruder" value="(\d+)"', cfg, re.S)
    assert extruders == ["1", "2"]
    names = re.findall(r'<part id="\d+"[^>]*>.*?<metadata key="name" value="([^"]+)"', cfg, re.S)
    assert names == ["synthetic bar · left nozzle", "synthetic bar · right nozzle"]
    # Read the stored meshes back and check the reach after the identity transform.
    assert "experimental" not in path
    outside = mesh.verify_3mf(path, (350, 320))
    assert outside == []


def test_plan_splits_only_the_wide_part():
    both = {**plates.catalog_printer("Bambu Lab H2D · both nozzles (split)", "h2d-both"), "enabled": True, "nozzle": "0.4", "preset": ""}
    assert both["nozzleMode"] == "h2d-split" and both["bed"] == [350, 320]
    stats = {
        "wide": {"size": [340, 40, 20], "volume_cm3": 10, "area_cm2": 10},
        "narrow": {"size": [100, 40, 20], "volume_cm3": 1, "area_cm2": 1},
        "too": {"size": [418.8, 47, 10], "volume_cm3": 1, "area_cm2": 1},
    }
    parts = [
        {"name": "wide", "file": "wide", "qty": 1, "role": "main", "group": "g"},
        {"name": "narrow", "file": "narrow", "qty": 1, "role": "main", "group": "g"},
        {"name": "too", "file": "too", "qty": 1, "role": "main", "group": "g"},
    ]
    result = plates.plan(parts, {"printers": [both], "mode": "h2d-both", "groupBy": "color"}, lambda f: stats[f])
    assert any(row["name"] == "too" for row in result["unplaceable"])
    split = [it for pl in result["plates"] for it in pl["items"] if it.get("nozzle") == "split"]
    assert len(split) == 1 and split[0]["part"] == "wide"
    assert h2d_split.RIGHT_MIN <= split[0]["splitX"] <= h2d_split.LEFT_MAX
    narrow = [it for pl in result["plates"] for it in pl["items"] if it["part"] == "narrow"]
    assert narrow and narrow[0]["nozzle"] == "left"
    left = {**plates.catalog_printer("Bambu Lab H2D · left nozzle", "h2d-left"), "enabled": True, "nozzle": "0.4", "preset": ""}
    left_plan = plates.plan([parts[1]], {"printers": [left], "mode": "h2d-left", "groupBy": "color"}, lambda f: stats[f])
    assert left_plan["placed"] == 1
    assert "nozzle" not in left_plan["plates"][0]["items"][0]


if __name__ == "__main__":
    test_limits_and_single_nozzle_regression()
    test_cut_conserves_a_box()
    test_placed_split_stays_inside_each_nozzle()
    test_3mf_is_one_object_with_two_nozzles()
    test_plan_splits_only_the_wide_part()
    print("test_h2d_split ok")
