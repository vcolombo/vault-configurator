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


def machine():
    left = plates.catalog_printer("Bambu Lab H2D · left nozzle", "h2d-left")
    right = plates.catalog_printer("Bambu Lab H2D · right nozzle", "h2d-right")
    both = plates.catalog_printer("Bambu Lab H2D · both nozzles (split)", "h2d-both")
    return both, left, right, left["bed"][0], right["origin"][0]


def world(tri, x, y, rot):
    placed = mesh.rotate_z(tri, rot)
    placed = np.array(placed, copy=True)
    placed[:, :, 0] += x
    placed[:, :, 1] += y
    return placed


def test_limits_and_single_nozzle_regression():
    both, left, right, left_w, _right_min = machine()
    assert plates.fits([200, 80, 40], left) is not None
    assert plates.fits([200, 80, 40], right) is not None
    assert plates.fits([418.8, 47, 10], left) is None  # wider than one nozzle and than the combined bed
    assert h2d_split.fit_angle([418.8, 47, 10], 0, both["bed"], left_w) is None
    assert h2d_split.fit_angle([360, 40, 20], 0, both["bed"], left_w) is None
    assert h2d_split.fit_angle([200, 80, 40], 0, both["bed"], left_w) == 0.0
    assert h2d_split.fit_angle([340, 40, 20], 0, both["bed"], left_w) == 0.0
    assert h2d_split.fit_angle([40, 340, 20], 0, both["bed"], left_w) == 90.0
    # A thin bar can still lie on the left nozzle diagonally. Combined mode does not claim that as a split.
    assert plates.fits([400, 20, 10], left) is not None
    assert h2d_split.fit_angle([400, 20, 10], 0, both["bed"], left_w) is None
    short = {**both, "maxH": 10}
    assert plates.fits([200, 40, 20], short) is None  # the shared height limit still applies


def test_cut_conserves_a_box():
    solid = box(340, 100, 20)
    original = mesh.mesh_volume(solid)
    left, right = h2d_split.split_mesh(solid, 175)
    assert h2d_split.watertight(left) and h2d_split.watertight(right)
    assert abs((mesh.mesh_volume(left) + mesh.mesh_volume(right)) - original) < 1e-3
    assert left[:, :, 0].max() <= 175 + 1e-4
    assert right[:, :, 0].min() >= 175 - 1e-4
    # The parts meet. They do not overlap as solids and they do not leave a gap.
    assert abs(left[:, :, 0].max() - right[:, :, 0].min()) < 1e-4
    assert abs(mesh.mesh_volume(left) - 175 * 100 * 20) < 1e-2
    assert abs(mesh.mesh_volume(right) - 165 * 100 * 20) < 1e-2


def test_placed_split_stays_inside_each_nozzle():
    both, _left, _right, left_max, right_min = machine()
    plate_x = both["bed"][0]
    solid = box(340, 80, 15)
    item = {"x": 1, "y": 2, "rot": 0, "w": 340, "d": 80}
    h2d_split.classify(item, plates.footprint_corners(item), both["bed"], left_max, right_min)
    assert item["nozzle"] == "split"
    cut = item["splitX"]
    assert right_min <= cut <= left_max
    halves = h2d_split.split_for_pose(solid, item["x"], item["rot"], cut)
    assert halves is not None
    left, right = (world(half, item["x"], item["y"], item["rot"]) for half in halves)
    assert left[:, :, 0].min() >= -1e-4 and left[:, :, 0].max() <= left_max + 1e-4
    assert right[:, :, 0].min() >= right_min - 1e-4 and right[:, :, 0].max() <= plate_x + 1e-4
    assert abs(mesh.mesh_volume(left) + mesh.mesh_volume(right) - mesh.mesh_volume(solid)) < 1e-2
    # A part that fits the left nozzle is not split.
    narrow = {"x": 0, "y": 0, "rot": 0, "w": 200, "d": 80}
    h2d_split.classify(narrow, plates.footprint_corners(narrow), both["bed"], left_max, right_min)
    assert narrow["nozzle"] == "left" and "splitX" not in narrow
    wide = {"x": 0, "y": 0, "rot": 0, "w": 360, "d": 40}
    h2d_split.classify(wide, plates.footprint_corners(wide), both["bed"], left_max, right_min)
    assert wide["nozzle"] == "unsplittable"
    turned = {"x": 340, "y": 0, "rot": 90, "w": 80, "d": 340}
    h2d_split.classify(turned, plates.footprint_corners(turned), both["bed"], left_max, right_min)
    assert turned["nozzle"] == "split"
    halves = h2d_split.split_for_pose(box(80, 340, 15), turned["x"], 90, turned["splitX"])
    assert halves is not None
    left, right = (world(half, turned["x"], turned["y"], 90) for half in halves)
    assert left[:, :, 0].max() <= left_max + 1e-3
    assert right[:, :, 0].min() >= right_min - 1e-3
    assert abs(mesh.mesh_volume(halves[0]) + mesh.mesh_volume(halves[1]) - mesh.mesh_volume(box(80, 340, 15))) < 1e-2


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
    outside = mesh.verify_3mf(path, (350, 320))
    assert outside == []
    # The right half is its own component. Shifting only that mesh must fail the plate check.
    right = right.copy()
    right[:, :, 0] += 400
    mesh.write_3mf(path, [{
        "name": "synthetic bar",
        "parts": [
            {"name": "synthetic bar · left nozzle", "mesh": left, "extruder": 1},
            {"name": "synthetic bar · right nozzle", "mesh": right, "extruder": 2},
        ],
    }], [{"name": "split", "items": [(0, 0, 0, 0)]}], (350, 320), "h2d split test")
    assert mesh.verify_3mf(path, (350, 320))


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
    _both, _left, _right, left_max, right_min = machine()
    assert right_min <= split[0]["splitX"] <= left_max
    assert all("h2dSplit" not in pl for pl in result["plates"])
    narrow = [it for pl in result["plates"] for it in pl["items"] if it["part"] == "narrow"]
    assert narrow and narrow[0]["nozzle"] == "left"
    left = {**plates.catalog_printer("Bambu Lab H2D · left nozzle", "h2d-left"), "enabled": True, "nozzle": "0.4", "preset": ""}
    left_plan = plates.plan([parts[1]], {"printers": [left], "mode": "h2d-left", "groupBy": "color"}, lambda f: stats[f])
    assert left_plan["placed"] == 1
    assert "nozzle" not in left_plan["plates"][0]["items"][0]


def test_edge_inset_and_shared_wide_plate():
    """A part inside the raw nozzle width can still need the combined bed once the edge is removed.
    Several bars that need that bed share one plate."""
    both, _left, _right, left_w, right_min = machine()
    assert h2d_split.single_nozzle_angle([320, 40, 10], 0, both["bed"], left_w) == 0.0
    assert h2d_split.single_nozzle_angle([320, 40, 10], 5, both["bed"], left_w) is None
    assert h2d_split.fit_angle([320, 40, 10], 5, both["bed"], left_w) == 0.0
    both = {**both, "enabled": True}
    inset = [{"name": f"inset-{n}", "file": "inset", "qty": 1, "role": "main", "group": "g"} for n in ("a", "b")]
    inset.append({"name": "narrow", "file": "narrow", "qty": 1, "role": "main", "group": "g"})
    stats = {"inset": {"size": [320, 40, 10], "volume_cm3": 1, "area_cm2": 1},
             "narrow": {"size": [100, 40, 10], "volume_cm3": 1, "area_cm2": 1}}
    result = plates.plan(inset, {"printers": [both], "mode": "h2d-both", "groupBy": "color", "edge": 5, "spacing": 6}, lambda f: stats[f])
    inset_plates = [pl for pl in result["plates"] if any(it["part"].startswith("inset") for it in pl["items"])]
    assert len(inset_plates) == 1 and len(inset_plates[0]["items"]) == 2
    for it in inset_plates[0]["items"]:
        assert it["x"] == 5
        assert it["x"] + it["w"] <= both["bed"][0] + 1e-6
    narrow = [it for pl in result["plates"] for it in pl["items"] if it["part"] == "narrow"]
    assert len(narrow) == 1 and narrow[0]["nozzle"] == "left" and "splitX" not in narrow[0]
    bars = [{"name": f"bar-{n}", "file": "bar", "qty": 1, "role": "main", "group": "g"} for n in range(3)]
    wide = plates.plan(bars, {"printers": [both], "mode": "h2d-both", "groupBy": "color", "edge": 0, "spacing": 6},
                       lambda f: {"size": [330, 40, 10], "volume_cm3": 1, "area_cm2": 1})
    split = [it for pl in wide["plates"] for it in pl["items"] if it.get("nozzle") == "split"]
    assert len(split) == 3
    assert sum(1 for pl in wide["plates"] if any(it.get("nozzle") == "split" for it in pl["items"])) == 1
    assert all(right_min <= it["splitX"] <= left_w for it in split)


if __name__ == "__main__":
    test_limits_and_single_nozzle_regression()
    test_cut_conserves_a_box()
    test_placed_split_stays_inside_each_nozzle()
    test_3mf_is_one_object_with_two_nozzles()
    test_plan_splits_only_the_wide_part()
    test_edge_inset_and_shared_wide_plate()
    print("test_h2d_split ok")
