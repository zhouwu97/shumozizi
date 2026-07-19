"""复验执行记录、输入输出哈希与运行目录边界。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "schemas"
RUNNER_VERSION = "1.0"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class RuntimeContractError(ValueError):
    """表示执行协议、路径边界或证据文件不合法。"""


def load_json_object(path: Path) -> dict[str, Any]:
    """读取根节点为对象的 UTF-8 JSON。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeContractError(f"缺少文件: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeContractError(f"JSON 格式错误 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeContractError(f"JSON 根节点必须是对象: {path}")
    return value


def validate_document(document: dict[str, Any], schema_name: str) -> list[str]:
    """使用 Draft 2020-12 Schema 返回全部结构错误。"""
    schema = load_json_object(SCHEMA_ROOT / schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for violation in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in violation.absolute_path) or "<root>"
        errors.append(f"{schema_name} [{location}]: {violation.message}")
    return errors


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 JSON，避免中断产生半文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    """以分块方式计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_run_path(
    run_dir: Path,
    relative_path: str,
    *,
    purpose: str,
    must_exist: bool = False,
) -> Path:
    """解析运行目录内路径并拒绝绝对路径及目录穿越。"""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise RuntimeContractError(f"{purpose} 路径不能为空")
    candidate_input = Path(relative_path)
    if candidate_input.is_absolute():
        raise RuntimeContractError(f"{purpose} 不允许绝对路径: {relative_path}")
    run_root = run_dir.resolve()
    candidate = (run_root / candidate_input).resolve()
    if candidate != run_root and run_root not in candidate.parents:
        raise RuntimeContractError(f"{purpose} 越过运行目录边界: {relative_path}")
    if must_exist and not candidate.is_file():
        raise RuntimeContractError(f"{purpose} 文件不存在: {relative_path}")
    return candidate


def relative_run_path(run_dir: Path, path: Path) -> str:
    """把已确认在运行目录内的路径转换为 POSIX 相对路径。"""
    return path.resolve().relative_to(run_dir.resolve()).as_posix()


def execution_record_path(run_dir: Path, execution_id: str) -> Path:
    """返回指定执行 ID 的固定记录路径。"""
    if not SAFE_ID.fullmatch(execution_id):
        raise RuntimeContractError(f"execution_id 不合法: {execution_id}")
    return run_dir.resolve() / "executions" / execution_id / "execution_record.json"


def file_evidence(run_dir: Path, relative_path: str, purpose: str) -> dict[str, Any]:
    """生成运行目录内文件的哈希和大小证据。"""
    path = resolve_run_path(run_dir, relative_path, purpose=purpose, must_exist=True)
    return {
        "path": relative_run_path(run_dir, path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def verify_execution_record(run_dir: Path, execution_id: str) -> dict[str, Any]:
    """复验一次执行的完整证据链，返回机器可读报告。"""
    run_root = run_dir.resolve()
    errors: list[str] = []
    try:
        record_path = execution_record_path(run_root, execution_id)
        record = load_json_object(record_path)
    except RuntimeContractError as exc:
        return {"valid": False, "execution_id": execution_id, "errors": [str(exc)]}

    try:
        errors.extend(validate_document(record, "execution_record.schema.json"))
    except RuntimeContractError as exc:
        errors.append(str(exc))

    if record.get("execution_id") != execution_id:
        errors.append("execution_record.execution_id 与目录不一致")
    if record.get("runner_version") != RUNNER_VERSION:
        errors.append("不支持的 runner_version")
    if record.get("exit_code") != 0:
        errors.append(f"执行退出码不是 0: {record.get('exit_code')}")
    if record.get("timed_out") is not False:
        errors.append("执行发生超时")

    manifest: dict[str, Any] = {}
    try:
        manifest_path = resolve_run_path(
            run_root,
            record.get("manifest_path", ""),
            purpose="执行清单",
            must_exist=True,
        )
        if record.get("manifest_sha256") != sha256_file(manifest_path):
            errors.append("执行清单哈希与记录不一致")
        manifest = load_json_object(manifest_path)
        errors.extend(validate_document(manifest, "execution_manifest.schema.json"))
    except RuntimeContractError as exc:
        errors.append(str(exc))

    if manifest:
        for field in (
            "execution_id",
            "program",
            "args",
            "cwd",
            "timeout_seconds",
            "random_seed",
            "expected_outputs",
        ):
            if record.get(field) != manifest.get(field):
                errors.append(f"执行记录字段与清单不一致: {field}")

        declared_inputs: set[str] = set()
        for relative_path in manifest.get("input_files", []):
            try:
                declared_inputs.add(
                    relative_run_path(
                        run_root,
                        resolve_run_path(
                            run_root,
                            relative_path,
                            purpose="input_file",
                            must_exist=True,
                        ),
                    )
                )
            except RuntimeContractError as exc:
                errors.append(str(exc))
        recorded_inputs = {
            item.get("path")
            for item in record.get("input_files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        if recorded_inputs != declared_inputs:
            errors.append("执行记录的输入文件集合与清单不一致")

    for log_field in ("stdout_path", "stderr_path"):
        try:
            resolve_run_path(
                run_root,
                record.get(log_field, ""),
                purpose=log_field,
                must_exist=True,
            )
        except RuntimeContractError as exc:
            errors.append(str(exc))

    for collection_name in ("input_files", "output_files"):
        records = record.get(collection_name, [])
        if not isinstance(records, list):
            continue
        for item in records:
            if not isinstance(item, dict):
                continue
            try:
                path = resolve_run_path(
                    run_root,
                    item.get("path", ""),
                    purpose=collection_name,
                    must_exist=True,
                )
                if item.get("sha256") != sha256_file(path):
                    errors.append(f"{collection_name} 哈希不一致: {item.get('path')}")
                if item.get("size_bytes") != path.stat().st_size:
                    errors.append(f"{collection_name} 大小不一致: {item.get('path')}")
            except RuntimeContractError as exc:
                errors.append(str(exc))

    output_paths = {
        item.get("path")
        for item in record.get("output_files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    for expected in record.get("expected_outputs", []):
        try:
            normalized = relative_run_path(
                run_root,
                resolve_run_path(run_root, expected, purpose="expected_output", must_exist=True),
            )
            if normalized not in output_paths:
                errors.append(f"预期输出缺少执行证据: {expected}")
        except RuntimeContractError as exc:
            errors.append(str(exc))

    return {
        "valid": not errors,
        "execution_id": execution_id,
        "record_path": str(record_path),
        "record_sha256": sha256_file(record_path) if record_path.is_file() else None,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    """解析复验命令行参数。"""
    parser = argparse.ArgumentParser(description="复验实验执行记录")
    parser.add_argument("run_dir", help="runs/<run_id> 目录")
    parser.add_argument("execution_id", help="执行记录 ID")
    return parser.parse_args()


def main() -> int:
    """执行复验并输出 JSON。"""
    args = parse_args()
    report = verify_execution_record(Path(args.run_dir), args.execution_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
