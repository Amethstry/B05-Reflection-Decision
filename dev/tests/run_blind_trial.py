"""Run a matched blind support-ticket trial using an existing Docker image."""

import argparse
import hashlib
import json
import math
import os
import shlex
import subprocess
import uuid
from pathlib import Path

from src import reflection, scene_io, score_benchmark

ENVIRONMENT = (
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_USE_JSON_SCHEMA",
    "LLM_TIMEOUT_SECONDS", "NO_PROXY", "no_proxy",
)
RESULT_NAME = "benchmark_results.json"


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def mount(source: Path, destination: str, readonly: bool) -> list[str]:
    option = ",readonly" if readonly else ""
    return ["--mount", f"type=bind,src={source},dst={destination}{option}"]


def run_stage(args, work: Path, name: str, inputs: Path, flags: list[str],
              extra_mounts: list[str] | None = None) -> Path:
    output = work / name
    output.mkdir()
    container = f"b05-blind-{uuid.uuid4().hex[:12]}"
    command = [
        "docker", "run", "--pull=never", "--rm", "--name", container, "--user", f"{os.getuid()}:{os.getgid()}",
    ]
    if args.network is not None:
        command.extend(["--network", args.network])
    for key in ENVIRONMENT:
        if key in os.environ:
            command.extend(["--env", key])
    command.extend(mount(inputs, "/input", readonly=True))
    command.extend(mount(output, "/output", readonly=False))
    command.extend(extra_mounts or [])
    command.extend([
        args.image_id, "--task", reflection.TASK, "--test", "--out-dir", "/output",
        "--time-budget", str(args.time_budget), *flags,
    ])
    if args.simulated_gateway:
        command.append("--simulated-gateway")

    log_path = work / f"{name}.log"
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"$ {shlex.join(command)}\n")
        log.flush()
        try:
            proc = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, timeout=args.time_budget + 30,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "rm", "--force", container], stdout=log, stderr=subprocess.STDOUT,
                timeout=10, check=False,
            )
            raise RuntimeError(f"{name} exceeded its time budget. See {log_path}.") from None
        log.write(f"exit={proc.returncode}\n")
    if proc.returncode:
        raise RuntimeError(f"{name} failed (exit {proc.returncode}). See {log_path}.")
    return output


def run(args) -> Path:
    if not 1 <= args.review_rounds <= 5:
        raise ValueError("--review-rounds must be between 1 and 5.")
    if not math.isfinite(args.time_budget) or args.time_budget <= 0:
        raise ValueError("--time-budget must be positive and finite.")

    domain, labels, cases = reflection.load_benchmark(args.benchmark)
    answers = reflection.load_answers(args.answers, labels)
    case_ids = {case["id"] for case in cases}
    seed_ids = set(args.seed_id)
    if not seed_ids < case_ids:
        raise ValueError("Seed IDs must name benchmark cases and leave at least one evaluation case.")
    if case_ids - answers.keys():
        raise ValueError("Reference labels are required for seed and evaluation cases.")
    # Validate the injected values without making a request or writing files.
    reflection.ModelClient.from_env()
    image = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", args.image],
        capture_output=True, text=True, timeout=15,
    )
    if image.returncode or not image.stdout.strip().startswith("sha256:"):
        raise ValueError(f"Build or load the local trial image first: {args.image}")
    args.image_id = image.stdout.strip()

    work = args.out_dir.resolve()
    scene_io.check_output_dir(args.benchmark.parent, work)
    work.mkdir(parents=True, exist_ok=True)
    seed_inputs, heldout_inputs, state = (work / name for name in ("seed_input", "heldout_input", "state"))
    for path in (seed_inputs, heldout_inputs, state):
        path.mkdir()

    shared = {"domain": domain, "labels": labels}
    seed_cases = [case for case in cases if case["id"] in seed_ids]
    heldout_cases = [case for case in cases if case["id"] not in seed_ids]
    reference = {case["id"]: answers[case["id"]] for case in heldout_cases}
    write_json(seed_inputs / "benchmark.json", shared | {"cases": seed_cases})
    write_json(seed_inputs / "answers.json", {case["id"]: answers[case["id"]] for case in seed_cases})
    write_json(heldout_inputs / "benchmark.json", shared | {"cases": heldout_cases})
    write_json(work / "heldout_answers.json", reference)

    rounds = ["--review-rounds", str(args.review_rounds)]
    run_stage(args, work, "seed", seed_inputs, [*rounds, "--knowledge-db", "/state/knowledge.sqlite3"],
              mount(state, "/state", readonly=False))
    seed = state / "knowledge.sqlite3"
    seed_hash = hashlib.sha256(seed.read_bytes()).hexdigest()

    baseline = run_stage(args, work, "initial", heldout_inputs, ["--blind", "--review-rounds", "0"])
    initial = baseline / "norethink" / RESULT_NAME
    review = ["--blind", "--initial-results", "/initial.json", *rounds]
    initial_mount = mount(initial, "/initial.json", readonly=True)
    cold = run_stage(args, work, "without_history", heldout_inputs, [*review, "--no-history"], initial_mount)
    knowledge_mounts = initial_mount + mount(seed, "/knowledge.sqlite3", readonly=True)
    history_review = [*review, "--knowledge-db", "/knowledge.sqlite3"]
    warm = run_stage(args, work, "with_history", heldout_inputs, history_review, knowledge_mounts)
    guarded = None
    if args.include_guarded:
        folder = run_stage(args, work, "with_guard", heldout_inputs,
                           [*history_review, "--guard-review"], knowledge_mounts)
        guarded = score_benchmark.read_arm(folder / "rethink" / RESULT_NAME, "rethink")
    if hashlib.sha256(seed.read_bytes()).hexdigest() != seed_hash:
        raise ValueError("Knowledge seed changed during the trial.")

    # Held-out answers are read here, after all inference containers have exited.
    scored = score_benchmark.score(
        score_benchmark.read_arm(initial, "norethink"),
        score_benchmark.read_arm(cold / "rethink" / RESULT_NAME, "rethink"),
        score_benchmark.read_arm(warm / "rethink" / RESULT_NAME, "rethink"),
        scene_io.read_json(work / "heldout_answers.json"),
        guarded=guarded,
    )
    scored["trial"] = {
        "image": args.image,
        "image_id": args.image_id,
        "seed_cases": [case["id"] for case in seed_cases],
        "knowledge_seed_sha256": seed_hash,
        "reference_fingerprint": reflection.fingerprint(reference),
    }
    path = work / "offline_score.json"
    write_json(path, scored)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=Path("../data/support_tickets/benchmark.json"))
    parser.add_argument("--answers", type=Path, default=Path("../data/support_tickets/answers.json"))
    parser.add_argument("--seed-id", action="append", required=True, help="seed case ID, repeat for more cases")
    parser.add_argument("--image", required=True, help="already-built image with the B05 run.sh")
    parser.add_argument("--network", help="Docker network with the authorized or simulated gateway")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--review-rounds", type=int, default=2)
    parser.add_argument("--time-budget", type=float, default=180.0, help="model-call budget per container")
    parser.add_argument("--simulated-gateway", action="store_true")
    parser.add_argument("--include-guarded", action="store_true", help="add the verified-history guard as a fourth arm")
    args = parser.parse_args()
    try:
        print(run(args))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
