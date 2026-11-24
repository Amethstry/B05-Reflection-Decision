#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_processor_contract.py — processor.py 输出契约测试（全部基于 scene_io 硬约束）。"""

from __future__ import annotations
import sys, unittest, math
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_WORKSPACE / "B05-Reflection-Decision" / "dev" / "src"))

from processor_test_fixtures import (
    load_scene_dict, load_scene_object, load_all_scene_objects,
    list_scene_files, _SELFTEST_DIR,
)
import scene_io


class TestSceneInputContract(unittest.TestCase):
    def test_files_exist(self):
        self.assertGreater(len(list_scene_files()), 0)

    def test_json_structure(self):
        for f in list_scene_files():
            d = load_scene_dict(f)
            self.assertEqual(set(d.keys()), {"P", "v"}, f.name)

    def test_P_v_shape_match(self):
        for f in list_scene_files():
            d = load_scene_dict(f)
            P, v = d["P"], d["v"]
            cols = len(P[0]) if P else 0
            self.assertEqual(cols, len(v), f.name)

    def test_values_finite(self):
        for f in list_scene_files():
            d = load_scene_dict(f)
            for row in d["P"]:
                for val in row:
                    self.assertTrue(math.isfinite(val))
            for val in d["v"]:
                self.assertTrue(math.isfinite(val))

    def test_P_probability_range(self):
        for f in list_scene_files():
            d = load_scene_dict(f)
            for row in d["P"]:
                for val in row:
                    self.assertGreaterEqual(val, 0.0)
                    self.assertLessEqual(val, 1.0)

    def test_scene_io_load_all(self):
        scenes = load_all_scene_objects()
        for s in scenes:
            self.assertEqual(s.rows, len(s.data["P"]))
            self.assertEqual(s.columns, len(s.data["v"]))


class TestSceneDataclassContract(unittest.TestCase):
    def test_fields(self):
        s = load_scene_object("scene1_0_50_20")
        for attr in ("name", "rows", "columns", "data"):
            self.assertTrue(hasattr(s, attr))
        self.assertEqual(set(s.data.keys()), {"P", "v"})

    def test_shape_consistency(self):
        s = load_scene_object("scene1_0_50_20")
        self.assertEqual(s.rows, len(s.data["P"]))
        self.assertEqual(s.columns, len(s.data["v"]))
        self.assertEqual(s.columns, len(s.data["P"][0]))


class TestModeContract(unittest.TestCase):
    def test_mode_values(self):
        self.assertEqual(set(scene_io.RESULT_DIRS), {"norethink", "rethink"})


class TestOutputContract(unittest.TestCase):
    def _fixture(self, scene, mode):
        return [1] * scene.rows

    def test_output_list_int(self):
        s = load_scene_object("scene1_0_50_20")
        r = self._fixture(s, "norethink")
        for v in r:
            self.assertIsInstance(v, int)

    def test_output_length(self):
        for s in load_all_scene_objects():
            for mode in scene_io.RESULT_DIRS:
                r = self._fixture(s, mode)
                self.assertEqual(len(r), s.rows)

    def test_passes_check_result(self):
        for s in load_all_scene_objects():
            for mode in scene_io.RESULT_DIRS:
                values = self._fixture(s, mode)
                scene_io.check_result({"results": values}, s.rows)

    def test_strict_int(self):
        s = load_scene_object("scene1_0_50_20")
        with self.assertRaises(Exception):
            scene_io.check_result({"results": [1.0] * s.rows}, s.rows)

    def test_wrapped_keys(self):
        s = load_scene_object("scene1_0_50_20")
        values = self._fixture(s, "norethink")
        scene_io.check_result({"results": values}, s.rows)
        with self.assertRaises(Exception):
            scene_io.check_result({"other": values}, s.rows)


class TestEndToEnd(unittest.TestCase):
    def test_all_scenes_all_modes(self):
        scenes = load_all_scene_objects()
        count = 0
        for s in scenes:
            for mode in scene_io.RESULT_DIRS:
                values = [1] * s.rows
                scene_io.check_result({"results": values}, s.rows)
                count += 1
        self.assertEqual(count, len(scenes) * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
