"""Check submission artifacts and output layout without running the submitted code."""

import argparse
import stat
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from src import scene_io

REQUIRED_CODE = {"Dockerfile", "run.sh", "requirements.txt"}
FORBIDDEN_ROOTS = {"tests", "tmp", "baselines", "reference"}


def archive_files(path: Path) -> dict[str, object]:
    with ZipFile(path) as archive:
        files = {}
        seen = set()
        for item in archive.infolist():
            name = item.filename
            parts = name.rstrip("/").split("/")
            mode = stat.S_IFMT(item.external_attr >> 16)
            if (
                name.startswith("/") or "\\" in name or ":" in parts[0]
                or any(part in {"", ".", ".."} for part in parts)
                or mode not in {0, stat.S_IFREG, stat.S_IFDIR}
                or tuple(parts) in seen
            ):
                raise ValueError(f"{path.name}: unsafe or duplicate archive member {name!r}.")
            seen.add(tuple(parts))
            if not item.is_dir():
                files[name] = item
        return files


def check_code(path: Path) -> list[str]:
    files = archive_files(path)
    issues = [
        f"代码包缺少根目录文件 {name}。" for name in sorted(REQUIRED_CODE - files.keys())
    ]
    if not any(name.startswith("src/") for name in files):
        issues.append("代码包缺少 src/ 下的源码。")
    included = {
        name for name in files
        if PurePosixPath(name).parts[0] in FORBIDDEN_ROOTS
        or PurePosixPath(name).parts[:2] == ("data", "selftest")
        or PurePosixPath(name).name == ".env"
        or PurePosixPath(name).name.startswith(".env.")
    }
    if included:
        issues.append(f"代码包带有开发资料或环境文件，共 {len(included)} 项。")
    if "src/main.py" in files and "src/processor.py" not in files:
        with ZipFile(path) as archive, archive.open(files["src/main.py"]) as stream:
            entrypoint = stream.read(256_000)
        if b"load_formal_processor" in entrypoint and b"processor.py" in entrypoint:
            issues.append("当前正式入口要求 src/processor.py，代码包缺少该文件。")
    return issues


def check_materials(path: Path) -> list[str]:
    files = list(map(PurePosixPath, archive_files(path)))
    issues = []
    if not any(part.endswith("_Scene") or part == "Scene" for path in files
               if path.suffix == ".json" for part in path.parts[:-1]):
        issues.append("方案包缺少 Scene 目录中的配套 JSON。")
    for label in ("红蓝对抗场景描述", "反思式决策解决方案"):
        if not any(item.suffix.lower() == ".pdf" and label in item.stem for item in files):
            issues.append(f"方案包缺少 {label} PDF。")
    return issues


def check_outputs(inputs: Path, outputs: Path) -> tuple[list[str], int]:
    scenes = scene_io.load_scenes(inputs)
    expected = {scene.name: scene.rows for scene in scenes}
    issues = []
    checked = 0
    for mode in scene_io.RESULT_DIRS:
        directory = outputs / mode
        if not directory.is_dir():
            issues.append(f"结果根目录缺少 {mode}/。")
            continue
        files = {path.name: path for path in directory.iterdir()}
        missing = expected.keys() - files.keys()
        extra = files.keys() - expected.keys()
        if missing:
            issues.append(f"{mode}/ 缺少同名 JSON {', '.join(sorted(missing))}。")
        if extra:
            issues.append(f"{mode}/ 出现未对应输入的文件 {', '.join(sorted(extra))}。")
        for name in sorted(expected.keys() & files.keys()):
            try:
                scene_io.check_result(scene_io.read_json(files[name]), expected[name])
            except (OSError, ValueError) as exc:
                issues.append(f"{mode}/{name} 结构无效，{exc}")
            else:
                checked += 1
    return issues, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", type=Path, help="candidate code ZIP")
    parser.add_argument("--materials", type=Path, help="candidate proposal ZIP")
    parser.add_argument("--intro", type=Path, help="initial-round project introduction")
    parser.add_argument("--inputs", type=Path, help="optional input directory for output checking")
    parser.add_argument("--outputs", type=Path, help="optional output directory for format checking")
    args = parser.parse_args()
    if bool(args.inputs) != bool(args.outputs):
        parser.error("--inputs and --outputs must be supplied together")
    if not any((args.code, args.materials, args.intro, args.inputs)):
        parser.error("supply a submission artifact or a pair of data directories")

    issues = []
    for label, path, operation in (
        ("代码包", args.code, check_code), ("方案包", args.materials, check_materials),
    ):
        try:
            issues.extend(operation(path) if path else [f"待提供{label}。"])
        except (OSError, ValueError, BadZipFile) as exc:
            issues.append(f"{label}无法检查，{exc}")
    if args.intro is None or not args.intro.is_file() or args.intro.stat().st_size == 0:
        issues.append("待提供初赛成果简介。")

    if args.inputs:
        try:
            errors, checked = check_outputs(args.inputs, args.outputs)
        except (OSError, ValueError) as exc:
            issues.append(f"输入输出无法检查，{exc}")
        else:
            print(f"结果格式检查通过 {checked} 个文件。")
            issues.extend(errors)
    for issue in issues:
        print(f"- {issue}")
    if not issues:
        print("所给文件通过离线结构检查。")
    print("答辩稿、命名及上传栏目以官方平台为准。程序实跑和评分需另行验收。")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
