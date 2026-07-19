"""把仓库级算法模板实例化到运行目录并记录来源回执。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_file,
    sha256_tree,
)
from shumozizi.core.schema import require_valid

GENERATOR_ID = "instantiate-template"
GENERATOR_VERSION = "1.0.0"


def _generated_tree_sha256(instance_dir: Path, relative_paths: set[str]) -> str:
    """按 ``sha256_tree`` 同一规则计算不含回执的实例摘要。"""
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = resolve_inside(instance_dir, relative, must_exist=True)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def instantiate_template(
    repo_root: Path,
    run_dir: Path,
    template_id: str,
    question_id: str,
    instance_id: str,
    parameters: dict[str, Any],
) -> Path:
    """复制模板、应用受控文本参数并生成不可变来源回执。"""
    runs_root = (repo_root.resolve() / "runs").resolve()
    resolved_run = run_dir.resolve()
    if runs_root not in resolved_run.parents:
        raise ContractError("模板只能实例化到当前仓库 runs/<run_id>/ 目录")
    for label, value in (("question_id", question_id), ("instance_id", instance_id)):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ContractError(f"{label} 不合法: {value}")
    template_dir = repo_root / "templates" / "algorithms" / template_id
    metadata_path = template_dir / "template.json"
    if not metadata_path.is_file():
        raise ContractError(f"模板元数据不存在: {metadata_path}")
    metadata = load_json(metadata_path)
    if metadata.get("template_id") != template_id:
        raise ContractError("模板目录名与 template.json 中的 template_id 不一致")
    registry = load_json(repo_root / "knowledge" / "SOURCE_REGISTRY.json")
    require_valid(registry, "external_source_registry")
    source = next(
        (
            item
            for item in registry["sources"]
            if item["repository"] == metadata.get("source_repository")
        ),
        None,
    )
    if source is None or source["commit"] != metadata.get("source_commit"):
        raise ContractError("模板来源仓库或提交未被 SOURCE_REGISTRY 锁定")
    if "selected-template-provenance" not in source["allowed_assets"]:
        raise ContractError("来源合同未允许模板来源语境")
    for name, value in parameters.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ContractError(f"模板参数名不合法: {name}")
        if not isinstance(value, (str, int, float, bool)):
            raise ContractError(f"模板参数必须是标量: {name}")
    destination = run_dir / "code" / question_id / instance_id
    if destination.exists():
        raise ContractError(f"模板实例已存在，拒绝覆盖: {destination}")
    destination.mkdir(parents=True)
    generated: list[dict[str, Any]] = []
    for source in sorted(path for path in template_dir.rglob("*") if path.is_file()):
        if source == metadata_path:
            continue
        relative = source.relative_to(template_dir)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in {".py", ".json", ".toml", ".md", ".txt"}:
            text = source.read_text(encoding="utf-8")
            for name, value in parameters.items():
                placeholder = "{{" + name + "}}"
                text = text.replace(placeholder, str(value))
            if re.search(r"\{\{[A-Za-z_][A-Za-z0-9_]*\}\}", text):
                raise ContractError(f"模板仍有未替换参数: {relative.as_posix()}")
            target.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(source, target)
        generated.append({"path": relative.as_posix(), "sha256": sha256_file(target)})
    canonical_parameters = json.dumps(
        parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    receipt = {
        "schema_name": "template_receipt",
        "schema_version": "2.0",
        "template_id": template_id,
        "template_version": metadata["template_version"],
        "source_repository": metadata["source_repository"],
        "source_commit": metadata["source_commit"],
        "source_template_sha256": sha256_tree(template_dir),
        "local_adapter_sha256": _generated_tree_sha256(
            destination, {item["path"] for item in generated}
        ),
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": sha256_file(Path(__file__)),
        "parameters_sha256": hashlib.sha256(canonical_parameters).hexdigest(),
        "generated_files": generated,
    }
    require_valid(receipt, "template_receipt")
    atomic_json(destination / "template_receipt.json", receipt)
    return destination


def verify_template_receipt(instance_dir: Path) -> dict[str, Any]:
    """复验模板实例的来源、生成器与全部生成文件哈希。"""
    receipt = load_json(instance_dir / "template_receipt.json")
    require_valid(receipt, "template_receipt")
    errors: list[str] = []
    for item in receipt["generated_files"]:
        try:
            path = resolve_inside(instance_dir, item["path"], must_exist=True)
            if sha256_file(path) != item["sha256"]:
                errors.append(f"生成文件哈希不一致: {item['path']}")
        except ContractError as exc:
            errors.append(str(exc))
    actual_paths = {
        path.relative_to(instance_dir).as_posix()
        for path in instance_dir.rglob("*")
        if path.is_file() and path.name != "template_receipt.json"
    }
    declared_paths = {item["path"] for item in receipt["generated_files"]}
    if actual_paths != declared_paths:
        errors.append("模板实例文件集合与回执不一致")
    elif _generated_tree_sha256(instance_dir, actual_paths) != receipt["local_adapter_sha256"]:
        errors.append("模板实例整体哈希与回执不一致")
    return {"valid": not errors, "receipt": receipt, "errors": errors}
