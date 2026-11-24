# PROCESSOR_SUPPORT_REPORT v0.2 — 处理器运行支撑接口约定

> 版本 v0.2（接口契约已锁定，来自 scene_io.py + main.py 硬证据）
> 模块：dev/src/processor_runtime.py
> 负责人：邓咏慷
> 更新：2026-11-24

## 0. 接口契约速查表（已锁定）

| 项 | 值 | 证据 |
|---|---|---|
| process 签名 | Callable[[scene_io.Scene, str], list[int]] | main.py: Processor |
| scene 类型 | scene_io.Scene frozen dataclass | scene_io.py |
| Scene 字段 | name / rows / columns / data | scene_io.py |
| Scene.data | 恒为 {"P": List[List[float]], "v": List[float]} | scene_io.py |
| mode 枚举 | "norethink" 和 "rethink" | scene_io.RESULT_DIRS |
| 输出长度 | scene.rows（红方兵力数） | main.py fixture_result |
| 输出值域 | 全部 int（严格 type is int） | scene_io.check_result |
| 输出外层 | {"results": list[int]} | scene_io.check_result |
| processor.py 位置 | dev/src/processor.py | main.py |
| 加载方式 | import_module("processor") → getattr("process") | main.py |
| RunContext 位置 | processor.py 内部自己创建（不在签名里） | main.py 签名只有 2 参数 |

## 1. 模块定位

processor_runtime.py 提供四件与红蓝对抗完全无关的通用能力：
- Stopwatch：高精度计时 + named lap
- TimeBudget：预算状态（checkpoint 只读不中断）
- StructuredLogger：每行一条 JSON（固定 5 字段）
- ConfigLoader：env > file > override > default

全部用 Python 标准库，不引第三方依赖。

## 2. RunContext 协作约定（方案 B 已由 main.py 锁定）

main.py 签名只有 process(scene, mode) 两个参数，RunContext 由 processor.py 内部创建：

```python
def process(scene: scene_io.Scene, mode: str) -> list[int]:
    ctx = RunContext(config={"scene_id": scene.name})
    ctx.sw.start()
    ctx.log.info("process_start", phase="entry", mode=mode, scene=scene.name,
                 rows=scene.rows, cols=scene.columns)
    # ... 反思循环 ...
    ctx.log.info("process_done", phase="exit", elapsed_ms=ctx.sw.elapsed_ms())
    ctx.sw.stop()
    ctx.close()
    return result
```

Scene 是 frozen dataclass，只读：
```python
scene.name       # "scene1_0_50_20.json"
scene.rows       # 50（红方兵力数）
scene.columns    # 20（蓝方目标数）
scene.data["P"]   # list[list[float]] shape [rows × columns]
scene.data["v"]   # list[float] shape [columns]
```

## 3. 日志规范

固定 5 字段：timestamp_iso / level / event / phase / scene_id
禁止：一条日志跨多行、塞整个 P 矩阵、混用 print。

## 4. 待王浩然/舒超确认

| # | 问题 | 谁答 |
|---|---|---|
| C5 | max_reflection_rounds 默认值 3？ | 王浩然 |
| C6 | 正式评测 total_budget_seconds 会由官方注入 env？ | 舒超/官方 |

## 5. 本次交付清单（v0.2）

✅ processor_runtime.py
✅ PROCESSOR_SUPPORT_REPORT.md v0.2
✅ processor_test_fixtures.py
✅ test_processor_runtime.py — 24 tests OK
✅ test_processor_contract.py — 17 tests OK

## 6. 下一步

王浩然现在可以写 processor.py：
签名 def process(scene: scene_io.Scene, mode: str) -> list[int]
processor.py 必须放在 dev/src/ 下，与 main.py 同目录。

本地自测：
  py -3 -m unittest dev/tests/test_processor_runtime.py -v
  py -3 -m unittest dev/tests/test_processor_contract.py -v
两者全部通过 = 你的 output 符合契约。
