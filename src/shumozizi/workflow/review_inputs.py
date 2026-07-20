"""审核材料清单的生成与复验。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.schema import require_valid
from shumozizi.workflow.review_policy import get_review_stage_policy


def _canonical_relative(run_dir: Path, declared_path: str, *, must_exist: bool = True) -> str:
    """把材料路径归一化，并拒绝 ``..``、反斜杠和路径别名。"""
    resolved = resolve_inside(run_dir, declared_path, must_exist=must_exist)
    canonical = relative_inside(run_dir, resolved).as_posix()
    if declared_path != canonical:
        raise ContractError(f"审核材料必须使用规范相对路径: {declared_path} -> {canonical}")
    return canonical


def _matches_forbidden(path: str, pattern: str) -> bool:
    """在路径归一化后匹配禁止目录、文件名或明确相对路径。"""
    normalized_path = path.casefold()
    normalized_pattern = pattern.replace("\\", "/").lstrip("./").casefold()
    if normalized_pattern.endswith("/"):
        return normalized_path.startswith(normalized_pattern)
    if "/" in normalized_pattern:
        return normalized_path == normalized_pattern or normalized_path.startswith(
            normalized_pattern
        )
    return PurePosixPath(normalized_path).name == normalized_pattern


def create_review_input_manifest(
    run_dir: Path,
    *,
    request_id: str,
    stage: str,
    review_round_id: str,
    state_revision: int,
    bindings: dict[str, str],
    binding_paths: dict[str, str],
    output_path: Path,
) -> Path:
    """冻结阶段材料及其哈希，作为审核请求的唯一输入权威清单。"""
    policy = get_review_stage_policy(stage, run_dir)
    mandatory = set(policy["mandatory_inputs"])
    materials = []
    for role in sorted(bindings):
        materials.append(
            {
                "role": role,
                "path": _canonical_relative(run_dir, binding_paths[role]),
                "sha256": bindings[role],
                "required": role in mandatory,
                "visibility": "reviewer",
            }
        )
    manifest = {
        "schema_name": "review_input_manifest",
        "schema_version": "2.0",
        "request_id": request_id,
        "run_id": run_dir.name,
        "stage": stage,
        "review_round_id": review_round_id,
        "state_revision": state_revision,
        "materials": materials,
        "forbidden_patterns": policy["forbidden_inputs"],
        "generated_at": _utc_now(),
    }
    require_valid(manifest, "review_input_manifest")
    atomic_json(output_path, manifest)
    return output_path


def verify_review_input_manifest(
    run_dir: Path,
    manifest_path: Path,
    *,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """复验材料角色、规范路径、禁止项和逐文件哈希。"""
    errors: list[str] = []
    try:
        manifest = load_json(manifest_path)
        require_valid(manifest, "review_input_manifest")
        policy = get_review_stage_policy(manifest["stage"], run_dir)
        materials = manifest["materials"]
        roles = [item["role"] for item in materials]
        if len(roles) != len(set(roles)):
            raise ContractError("审核材料清单包含重复 role")
        mandatory = set(policy["mandatory_inputs"])
        allowed = mandatory | set(policy["optional_inputs"])
        if not mandatory.issubset(roles):
            raise ContractError(
                "审核材料清单缺少强制 role: " + ", ".join(sorted(mandatory - set(roles)))
            )
        if not set(roles).issubset(allowed):
            raise ContractError(
                "审核材料清单包含策略外 role: " + ", ".join(sorted(set(roles) - allowed))
            )
        if manifest["forbidden_patterns"] != policy["forbidden_inputs"]:
            raise ContractError("审核材料清单的禁止路径策略已被修改")
        for item in materials:
            path = _canonical_relative(run_dir, item["path"])
            if any(_matches_forbidden(path, pattern) for pattern in policy["forbidden_inputs"]):
                raise ContractError(f"审核材料命中禁止路径: {path}")
            if sha256_file(resolve_inside(run_dir, path, must_exist=True)) != item["sha256"]:
                raise ContractError(f"审核材料哈希已变化: {item['role']}")
            if item["required"] != (item["role"] in mandatory):
                raise ContractError(f"审核材料 required 标记错误: {item['role']}")
        if request is not None:
            identity = (
                "request_id",
                "run_id",
                "stage",
                "review_round_id",
                "state_revision",
            )
            if any(manifest[key] != request[key] for key in identity):
                raise ContractError("审核材料清单与请求身份不一致")
            manifest_roles = {item["role"]: item for item in materials}
            if set(manifest_roles) != set(request["bindings"]):
                raise ContractError("审核材料清单与请求 bindings 角色不一致")
            for role, expected in request["bindings"].items():
                if manifest_roles[role]["sha256"] != expected:
                    raise ContractError(f"审核材料清单与请求哈希不一致: {role}")
                if manifest_roles[role]["path"] != request["binding_paths"][role]:
                    raise ContractError(f"审核材料清单与请求路径不一致: {role}")
            material_paths = {item["path"] for item in materials}
            read_paths = set(request["read_paths"])
            if not read_paths.issubset(material_paths):
                raise ContractError("审核 read_paths 只能引用材料清单中的文件")
            required_paths = {
                item["path"] for item in materials if item["role"] in mandatory
            }
            if not required_paths.issubset(read_paths):
                raise ContractError("审核 read_paths 未覆盖全部强制材料")
    except (ContractError, OSError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "manifest_path": str(manifest_path)}


def _utc_now() -> str:
    """返回 RFC 3339 UTC 时间，延迟导入以保持模块依赖单向。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
