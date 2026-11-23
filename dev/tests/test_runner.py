"""Connect the B05 entry point to test processors and verify batch output."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.main import main


class RunnerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.inputs = root / "input"
        self.inputs.mkdir()
        self.output = root / "output"
        self.first = self.inputs / "scene1_0_2_3.json"
        self.second = self.inputs / "scene1_1_1_2.json"
        self.first.write_text('{"P":[[0,0,0],[0,0,0]],"v":[0,0,0],"note":"first"}', encoding="utf-8")
        self.second.write_text('{"P":[[0,0]],"v":[0,0],"note":"second"}', encoding="utf-8")

    def run_main(self, processor, *flags):
        args = ["--task", "all", "--test", "--out-dir", str(self.output), *flags]
        with patch.dict(os.environ, {"DATA_ROOT": str(self.inputs)}):
            with self.assertLogs("src.main", level="INFO") as captured:
                code = main(args, processor=processor)
        return code, "\n".join(captured.output)

    def test_processor_receives_validated_scenes_and_modes(self):
        calls = []
        shared_buffer = []
        tokens = {"norethink": 10, "rethink": 20}

        def processor(scene, mode):
            calls.append((scene.name, scene.rows, scene.columns, scene.data["note"], mode))
            shared_buffer[:] = [tokens[mode]] * scene.rows
            return shared_buffer

        code, log = self.run_main(processor)
        self.assertEqual(code, 0, log)
        self.assertEqual(calls, [
            (self.first.name, 2, 3, "first", "norethink"),
            (self.first.name, 2, 3, "first", "rethink"),
            (self.second.name, 1, 2, "second", "norethink"),
            (self.second.name, 1, 2, "second", "rethink"),
        ])
        self.assertEqual({item.name for item in self.output.iterdir()}, set(tokens))
        for mode, value in tokens.items():
            group = self.output / mode
            self.assertEqual({item.name for item in group.iterdir()}, {self.first.name, self.second.name})
            for source, length in ((self.first, 2), (self.second, 1)):
                payload = json.loads((group / source.name).read_bytes())
                self.assertEqual(payload, {"results": [value] * length})
        self.assertRegex(log, r"mode=formal exit=0 total=[0-9.]+s")

    def test_explicit_local_modes_do_not_call_formal_processor(self):
        processor = Mock()
        code, log = self.run_main(processor, "--validate-only")
        self.assertEqual(code, 0, log)
        self.assertFalse(self.output.exists())

        code, log = self.run_main(processor, "--fixture")
        self.assertEqual(code, 0, log)
        processor.assert_not_called()
        for mode in ("norethink", "rethink"):
            result = json.loads((self.output / mode / self.first.name).read_bytes())
            self.assertEqual(result, {"results": [1, 1]})

    def test_invalid_input_stops_before_formal_processing(self):
        self.second.write_text('{"P":[[0,0]]}', encoding="utf-8")
        processor = Mock()
        code, log = self.run_main(processor)
        self.assertEqual(code, 1)
        self.assertIn(f"{self.second.name}: missing required fields: v", log)
        processor.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_processor_error_identifies_scene_and_mode_without_writing(self):
        def processor(scene, mode):
            if scene.name == self.second.name and mode == "rethink":
                raise RuntimeError("test processor failed")
            return [0] * scene.rows

        code, log = self.run_main(processor)
        self.assertEqual(code, 1)
        self.assertIn(f"{self.second.name} [rethink]: test processor failed", log)
        self.assertFalse(self.output.exists())

    def test_invalid_processor_output_stops_batch_before_writing(self):
        def processor(scene, mode):
            if scene.name == self.second.name and mode == "rethink":
                return [True]
            return [0] * scene.rows

        code, log = self.run_main(processor)
        self.assertEqual(code, 1)
        self.assertIn(f"{self.second.name} [rethink]: results entries must be integers", log)
        self.assertFalse(self.output.exists())

    def test_publication_failure_rolls_back_first_directory_and_allows_retry(self):
        def processor(scene, _mode):
            return [0] * scene.rows

        rename = Path.rename

        def fail_second(source, target):
            if target == self.output / "rethink":
                raise OSError("test publication failure")
            return rename(source, target)

        with patch.object(Path, "rename", fail_second):
            code, log = self.run_main(processor)
        self.assertEqual(code, 1)
        self.assertIn("test publication failure", log)
        self.assertEqual(list(self.output.iterdir()), [])

        code, log = self.run_main(processor)
        self.assertEqual(code, 0, log)
        self.assertEqual({item.name for item in self.output.iterdir()}, {"norethink", "rethink"})


if __name__ == "__main__":
    unittest.main()
