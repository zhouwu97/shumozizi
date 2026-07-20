"""按文档自声明的名称与版本执行 JSON Schema 校验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, load_json
from shumozizi.core.repo_root import resolve_repo_root


def schema_root() -> Path:
    """返回仓库内 Schema 目录。"""
    return resolve_repo_root(Path(__file__)) / "schemas"


def validate_document(document: dict[str, Any], expected_name: str | None = None) -> list[str]:
    """依据显式 ``schema_name`` 与 ``schema_version`` 校验文档。"""
    name = document.get("schema_name")
    version = document.get("schema_version")
    if not isinstance(name, str) or not isinstance(version, str):
        return ["文档必须显式包含 schema_name 与 schema_version"]
    if expected_name is not None and name != expected_name:
        return [f"schema_name 应为 {expected_name}，实际为 {name}"]
    supported_non_v2 = {
        ("review_receipt", "3.0"),
        ("review_report", "3.0"),
        ("r1_phase_a", "1.0"),
        ("scientific_reviewer_cases", "1.0"),
        ("scientific_reviewer_oracle", "1.0"),
        ("scientific_reviewer_observations", "1.0"),
        ("scientific_reviewer_benchmark_status", "1.0"),
    }
    if version != "2.0" and (name, version) not in supported_non_v2:
        return [f"Schema 校验器拒绝版本 {version}"]
    path = schema_root() / f"{name}.schema.json"
    try:
        schema = load_json(path)
    except ContractError as exc:
        return [str(exc)]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for violation in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in violation.absolute_path) or "<root>"
        errors.append(f"{path.name} [{location}]: {violation.message}")
    return errors


def require_valid(document: dict[str, Any], expected_name: str) -> None:
    """校验文档，并把全部错误合并为协议异常。"""
    errors = validate_document(document, expected_name)
    if errors:
        raise ContractError("; ".join(errors))
