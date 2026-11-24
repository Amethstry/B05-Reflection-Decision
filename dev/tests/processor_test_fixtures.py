#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""processor_test_fixtures.py —— 测试夹具：加载官方自测场景。"""

from __future__ import annotations
import json, os, sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parent.parent
_B05_DEV_SRC = _WORKSPACE / "B05-Reflection-Decision" / "dev" / "src"
_SELFTEST_DIR = _WORKSPACE / "extracted" / "selftest"

try:
    sys.path.insert(0, str(_B05_DEV_SRC))
    import scene_io as _scene_io
    _SCENE_IO_AVAILABLE = True
except ImportError:
    _SCENE_IO_AVAILABLE = False


def list_scene_files(scene_dir=None):
    d = scene_dir or _SELFTEST_DIR
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix == ".json" and p.name.startswith("scene"))


def load_scene_dict(name_or_path, scene_dir=None):
    p = Path(name_or_path)
    if not p.is_file():
        d = scene_dir or _SELFTEST_DIR
        if not str(p).endswith(".json"):
            p = d / f"{p}.json"
        else:
            p = d / p.name
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_scene_dicts(scene_dir=None):
    return [load_scene_dict(p.name, scene_dir) for p in list_scene_files(scene_dir)]


def load_scene_object(name_or_path, scene_dir=None):
    if not _SCENE_IO_AVAILABLE:
        raise ImportError("scene_io 模块不可用")
    p = Path(name_or_path)
    if not p.is_file():
        d = scene_dir or _SELFTEST_DIR
        if not str(p).endswith(".json"):
            p = d / f"{p}.json"
        else:
            p = d / p.name
    return _scene_io.load_scene(p)


def load_all_scene_objects(scene_dir=None):
    if not _SCENE_IO_AVAILABLE:
        raise ImportError("scene_io 模块不可用")
    d = scene_dir or _SELFTEST_DIR
    return _scene_io.load_scenes(d)


def scene_shape(scene_dict):
    P = scene_dict["P"]
    return len(P), len(P[0]) if P else 0


def describe_scene(scene_dict):
    rows, cols = scene_shape(scene_dict)
    v = scene_dict["v"]
    return {"rows": rows, "cols": cols, "total_value": sum(v)}
