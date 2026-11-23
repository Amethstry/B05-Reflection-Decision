"""Exercise B05 I/O with official self-test files and small invalid inputs."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.main import main
from src.scene_io import check_result, load_scene, read_json


class IoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.inputs = self.root / "input"
        self.inputs.mkdir()
        self.output = self.root / "output"
        self.scene = self.inputs / "scene1_0_2_3.json"

    def write_scene(self, **fields):
        data = {"P": [[0.0, 0.2, 0.4], [0.5, 1, 0]], "v": [1, 2, 3]}
        self.scene.write_text(json.dumps(data | fields), encoding="utf-8")

    def run_cli(self, source=None, *, fixture=False, validate_only=False, output=None):
        env = os.environ | {"DATA_ROOT": str(source or self.inputs), "OUTPUT_DIR": str(self.output)}
        command = [sys.executable, "src/main.py", "--task", "all", "--test"]
        if fixture:
            command.append("--fixture")
        if validate_only:
            command.append("--validate-only")
        if output is not None:
            command.extend(["--out-dir", str(output)])
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)

    def test_all_official_scenes_and_fixture_outputs(self):
        default_data = Path(__file__).resolve().parents[2] / "data/selftest"
        data = Path(os.environ.get("DATA_ROOT", default_data))
        sources = sorted(data.glob("*.json"))
        self.assertEqual(len(sources), 10)
        for source in sources:
            with self.subTest(scene=source.name):
                expected_rows = int(source.stem.split("_")[-2])
                self.assertEqual(load_scene(source).rows, expected_rows)

        # Explicit argument wins over OUTPUT_DIR; verify the actual serialized JSON.
        actual_output = self.root / "explicit-output"
        result = self.run_cli(data, fixture=True, output=actual_output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual({p.name for p in actual_output.iterdir()}, {"norethink", "rethink"})
        for mode in ("norethink", "rethink"):
            directory = actual_output / mode
            self.assertEqual({p.name for p in directory.iterdir()}, {src.name for src in sources})
            for source in sources:
                with self.subTest(scene=source.name, mode=mode):
                    value = json.loads((directory / source.name).read_bytes())
                    expected_rows = int(source.stem.split("_")[-2])
                    self.assertEqual(value, {"results": [1] * expected_rows})
                    check_result(value, expected_rows)

    def test_json_syntax_encoding_and_duplicates(self):
        bad_json = [
            (b'{"P":', "invalid JSON"),
            (b'{"P": []}\xff', "invalid JSON"),
            (b'{"P": [],"P": [],"v": []}', "duplicate JSON key 'P'"),
            (b'{"P": [],"v": [NaN]}', "invalid JSON constant NaN"),
        ]
        for payload, message in bad_json:
            with self.subTest(message=message):
                self.scene.write_bytes(payload)
                with self.assertRaisesRegex(ValueError, message):
                    read_json(self.scene)

    def test_required_fields_and_top_level_object(self):
        for payload, message in (
            ("[]", "top level must be an object"),
            ('{"v":[]}', "missing required fields: P"),
            ('{"P":[],"V":[]}', "missing required fields: v"),
        ):
            with self.subTest(payload=payload):
                self.scene.write_text(payload, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    load_scene(self.scene)

    def test_extra_input_fields_are_allowed(self):
        self.write_scene(note="synthetic")
        self.assertEqual(load_scene(self.scene).rows, 2)

    def test_matrix_and_vector_shapes(self):
        for fields, message in (
            ({"P": [[0, 0, 0]]}, "P must have 2 rows"),
            ({"P": [[0, 0, 0], [1, 1]]}, r"P\[1\] must be an array of length 3"),
            ({"P": [[0, 0, 0], "123"]}, r"P\[1\] must be an array of length 3"),
            ({"v": [0, 0]}, "v must be an array of length 3"),
            ({"v": {}}, "v must be an array of length 3"),
        ):
            with self.subTest(fields=fields):
                self.write_scene(**fields)
                with self.assertRaisesRegex(ValueError, message):
                    load_scene(self.scene)

    def test_values_must_be_finite_numbers(self):
        for value in (True, None, "0.5"):
            with self.subTest(value=value):
                self.write_scene(P=[[0, 0, value], [0, 0, 0]])
                with self.assertRaisesRegex(ValueError, "must be a finite number"):
                    load_scene(self.scene)
        self.scene.write_text('{"P":[[0,0,0],[0,0,0]],"v":[1e999,0,0]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"v\[0\] must be a finite number"):
            load_scene(self.scene)

    def test_filename_dimensions_and_indices(self):
        for name in ("wrong.json", "scene3_0_2_3.json", "scene1_5_2_3.json", "scene1_0_0_3.json"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "expected scene"):
                load_scene(self.inputs / name)

    def test_result_schema_does_not_assume_index_base(self):
        check_result({"results": [0, 1]}, 2)
        check_result({"results": [1, 2]}, 2)
        for malformed in (
            [],
            {"result": [1, 1]},
            {"results": [1, 1], "extra": {}},
            {"results": 1},
            {"results": [1]},
            {"results": [1, True]},
            {"results": [1, 2.0]},
        ):
            with self.subTest(result=malformed), self.assertRaises(ValueError):
                check_result(malformed, 2)

    def test_missing_or_empty_input_directory_fails(self):
        for source in (self.root / "missing", self.inputs):
            with self.subTest(source=source):
                proc = self.run_cli(source, fixture=True)
                self.assertEqual(proc.returncode, 1)
                self.assertIn(str(source), proc.stderr)
                self.assertFalse(self.output.exists())

    def test_invalid_later_input_fails_without_outputs(self):
        self.write_scene()
        invalid = self.inputs / "scene1_1_2_3.json"
        invalid.write_text('{"P": []}', encoding="utf-8")
        proc = self.run_cli(fixture=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(invalid.name, proc.stderr)
        self.assertIn("missing required fields: v", proc.stderr)
        self.assertFalse(self.output.exists())

    def test_formal_entry_reports_unimplemented_without_writing(self):
        with patch("src.main.load_formal_processor", return_value=None):
            with self.assertLogs("src.main", level="ERROR") as log:
                code = main(["--task", "all", "--test", "--out-dir", str(self.output)])
        self.assertEqual(code, 3)
        self.assertIn("Provide src/processor.py", log.output[0])
        self.assertFalse(self.output.exists())

    def test_validate_only_checks_inputs_without_writing_fixtures(self):
        self.write_scene()
        proc = self.run_cli(validate_only=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Validated 1 scene files", proc.stderr)
        self.assertFalse(self.output.exists())

    def test_fixture_and_validate_only_are_mutually_exclusive(self):
        self.write_scene()
        proc = self.run_cli(fixture=True, validate_only=True)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(self.output.exists())

    def test_fixture_uses_output_dir_environment(self):
        self.write_scene()
        proc = self.run_cli(fixture=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.output / "rethink" / self.scene.name).is_file())

    def test_fixture_leaves_existing_output_untouched(self):
        self.write_scene()
        self.output.mkdir()
        existing = self.output / "existing.txt"
        existing.write_text("keep", encoding="utf-8")
        proc = self.run_cli(fixture=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("must be empty", proc.stderr)
        self.assertEqual(list(self.output.iterdir()), [existing])
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_fixture_refuses_to_write_inside_inputs(self):
        self.write_scene()
        out_dir = self.inputs / "output"
        proc = self.run_cli(fixture=True, output=out_dir)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("outside DATA_ROOT", proc.stderr)
        self.assertFalse(out_dir.exists())


if __name__ == "__main__":
    unittest.main()
