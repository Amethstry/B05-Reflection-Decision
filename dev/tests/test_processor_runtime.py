#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_processor_runtime.py — processor_runtime.py 单元测试。"""

from __future__ import annotations
import json, os, sys, tempfile, time, unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_HERE))
import processor_runtime as rt


class TestStopwatch(unittest.TestCase):
    def test_initial_state(self):
        sw = rt.Stopwatch()
        self.assertFalse(sw.is_running)
        self.assertEqual(sw.elapsed(), 0.0)
        self.assertEqual(sw.laps, [])

    def test_start_stop_elapsed(self):
        sw = rt.Stopwatch()
        sw.start()
        time.sleep(0.02)
        sw.stop()
        self.assertGreater(sw.elapsed(), 0.01)
        self.assertLess(sw.elapsed(), 1.0)

    def test_lap(self):
        sw = rt.Stopwatch()
        sw.start()
        time.sleep(0.005)
        sw.lap("first")
        sw.stop()
        self.assertEqual(len(sw.laps), 1)
        self.assertEqual(sw.laps[0]["name"], "first")

    def test_measure_context_manager(self):
        sw = rt.Stopwatch()
        with sw.measure("solve"):
            time.sleep(0.01)
        self.assertEqual(len(sw.laps), 1)
        self.assertEqual(sw.laps[0]["name"], "solve")


class TestTimeBudget(unittest.TestCase):
    def test_no_budget(self):
        sw = rt.Stopwatch()
        budget = rt.TimeBudget(None, sw)
        sw.start()
        status = budget.checkpoint()
        self.assertIsNone(status.total_seconds)
        self.assertFalse(status.is_exhausted)

    def test_within_budget(self):
        sw = rt.Stopwatch()
        budget = rt.TimeBudget(10.0, sw)
        sw.start()
        status = budget.checkpoint()
        self.assertEqual(status.total_seconds, 10.0)
        self.assertFalse(status.is_exhausted)

    def test_exhausted(self):
        sw = rt.Stopwatch()
        budget = rt.TimeBudget(0.01, sw)
        sw.start()
        time.sleep(0.02)
        status = budget.checkpoint()
        self.assertTrue(status.is_exhausted)

    def test_negative_rejected(self):
        sw = rt.Stopwatch()
        with self.assertRaises(ValueError):
            rt.TimeBudget(-1.0, sw)


class TestStructuredLogger(unittest.TestCase):
    def test_file_output(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as tf:
            path = tf.name
        try:
            log = rt.StructuredLogger(output_path=path, scene_id="t")
            log.info("x", phase="e")
            log.error("y", phase="ex", exc=ValueError("b"))
            log.close()
            with open(path) as f:
                lines = f.read().strip().split("\n")
            self.assertEqual(len(lines), 2)
            for line in lines:
                obj = json.loads(line)
                self.assertIn("timestamp_iso", obj)
                self.assertIn("level", obj)
                self.assertIn("event", obj)
            err = json.loads(lines[1])
            self.assertEqual(err["level"], "ERROR")
            self.assertEqual(err["exc_type"], "ValueError")
        finally:
            os.unlink(path)


class TestConfigLoader(unittest.TestCase):
    def test_defaults(self):
        cfg = rt.ConfigLoader()
        self.assertEqual(cfg.get("max_reflection_rounds"), 3)
        self.assertIsNone(cfg.get("total_budget_seconds"))

    def test_override_dict(self):
        cfg = rt.ConfigLoader(override_dict={"scene_id": "custom"})
        self.assertEqual(cfg.get("scene_id"), "custom")

    def test_env_override(self):
        os.environ["B05_RT_TOTAL_BUDGET_SECONDS"] = "15.0"
        try:
            cfg = rt.ConfigLoader()
            self.assertEqual(cfg.get("total_budget_seconds"), 15.0)
        finally:
            del os.environ["B05_RT_TOTAL_BUDGET_SECONDS"]


class TestRunContext(unittest.TestCase):
    def test_components_exist(self):
        ctx = rt.RunContext(config={"scene_id": "t"})
        self.assertIsInstance(ctx.sw, rt.Stopwatch)
        self.assertIsInstance(ctx.budget, rt.TimeBudget)
        self.assertIsInstance(ctx.log, rt.StructuredLogger)
        self.assertIsInstance(ctx.config, rt.ConfigLoader)
        ctx.close()

    def test_snapshot(self):
        ctx = rt.RunContext()
        ctx.sw.start()
        snap = ctx.snapshot()
        self.assertIn("elapsed_ms", snap)
        self.assertIn("budget", snap)
        self.assertIn("laps", snap)
        self.assertIn("config", snap)
        ctx.sw.stop()
        ctx.close()


class TestTraceProcess(unittest.TestCase):
    def test_passthrough(self):
        @rt.trace_process
        def f(x): return x + 1
        self.assertEqual(f(5), 6)

    def test_with_ctx(self):
        @rt.trace_process
        def g(x, ctx): return x * 2
        ctx = rt.RunContext()
        try:
            self.assertEqual(g(5, ctx=ctx), 10)
            self.assertFalse(ctx.sw.is_running)
        finally:
            ctx.close()

    def test_exception_propagation(self):
        @rt.trace_process
        def bad(ctx): raise ValueError("boom")
        ctx = rt.RunContext()
        try:
            with self.assertRaises(ValueError):
                bad(ctx=ctx)
            self.assertFalse(ctx.sw.is_running)
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
