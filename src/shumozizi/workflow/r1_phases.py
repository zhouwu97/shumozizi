"""R1 两阶段隔离、Phase A 冻结与 Phase B 请求绑定。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.schema import require_valid

PHASE_A_ALLOWED_ROLES = frozenset(
    {
        "problem_source",
        "problem_attachments_manifest",
        "competition_rules",
        "problem_manifest",
        "data_dictionary",
        "data_profile",
        "unit_dictionary",
    }
)
PHASE_A_FORBIDDEN_MARKERS = (
    "route_candidates",
    "route_lock",
    "model_spec",
    "validation_plan",
    "retrieval",
    "paper_card",
    "knowledge/card",
    "knowledge\\card",
)
PHASE_A_OUTPUT_FIELDS = (
    "required_outputs",
    "decision_variables",
    "observable_variables",
    "latent_variables",
    "units",
    "hard_constraints",
    "boundary_conditions",
    "plausible_model_families",
    "identifiability_risks",
    "minimum_validation_requirements",
    "possible_failure_modes",
)


def _relative(run_dir: Path, path: Path) -> str:
    """返回运行目录内的稳定相对路径。"""
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"R1 Phase A 输入越过运行目录边界: {path}") from exc


def create_r1_phase_a(
    run_dir: Path,
    review_round_id: str,
    bindings: dict[str, Path],
    reconstruction: dict[str, list[str]],
    *,
    generated_at: str | None = None,
) -> Path:
    """只从题面侧材料生成不可覆盖的 Phase A 重构产物。"""
    roles = set(bindings)
    unknown_roles = sorted(roles - PHASE_A_ALLOWED_ROLES)
    if unknown_roles:
        raise ContractError("R1 Phase A 包含作者侧或未授权材料: " + ", ".join(unknown_roles))
    if "problem_source" not in roles:
        raise ContractError("R1 Phase A 必须绑定原始题面")
    if set(reconstruction) != set(PHASE_A_OUTPUT_FIELDS):
        raise ContractError("R1 Phase A 输出字段不完整或包含额外字段")
    input_bindings: dict[str, str] = {}
    input_paths: dict[str, str] = {}
    for role, path in bindings.items():
        relative = _relative(run_dir, path)
        lowered = relative.casefold()
        if any(marker in lowered for marker in PHASE_A_FORBIDDEN_MARKERS):
            raise ContractError(f"R1 Phase A 禁止读取作者侧路径: {relative}")
        if not path.is_file():
            raise ContractError(f"R1 Phase A 输入不存在: {path}")
        input_bindings[role] = sha256_file(path)
        input_paths[role] = relative
    document = {
        "schema_name": "r1_phase_a",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "review_round_id": review_round_id,
        "input_bindings": input_bindings,
        "input_paths": input_paths,
        **reconstruction,
        "generated_at": generated_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    require_valid(document, "r1_phase_a")
    output = run_dir / "review" / "r1_modeling_phase_a" / review_round_id / "PHASE_A.json"
    if output.exists():
        raise ContractError("R1 Phase A 已冻结，禁止覆盖")
    atomic_json(output, document)
    return output


def verify_r1_phase_a(
    run_dir: Path, phase_a_path: Path, *, expected_sha256: str | None = None
) -> dict[str, Any]:
    """复验 Phase A 文件哈希及全部只读输入绑定。"""
    if expected_sha256 is not None and sha256_file(phase_a_path) != expected_sha256:
        raise ContractError("R1 Phase A 冻结哈希不一致")
    document = load_json(phase_a_path)
    require_valid(document, "r1_phase_a")
    if document["run_id"] != run_dir.name:
        raise ContractError("R1 Phase A run_id 与运行目录不一致")
    if set(document["input_bindings"]) - PHASE_A_ALLOWED_ROLES:
        raise ContractError("R1 Phase A 记录了未授权材料角色")
    if set(document["input_bindings"]) != set(document["input_paths"]):
        raise ContractError("R1 Phase A 输入角色与路径映射不一致")
    for role, relative in document["input_paths"].items():
        source = resolve_inside(run_dir, relative, must_exist=True)
        if sha256_file(source) != document["input_bindings"][role]:
            raise ContractError(f"R1 Phase A 输入冻结后发生变化: {role}")
    return document


def create_r1_phase_b_request(
    run_dir: Path,
    phase_a_path: Path,
    bindings: dict[str, Path],
    **request_options: Any,
) -> Path:
    """Phase A 复验通过后，创建可读取作者材料的正式 R1 请求。"""
    from shumozizi.workflow.reviews import create_review_request

    verify_r1_phase_a(run_dir, phase_a_path)
    if "phase_a" in bindings:
        raise ContractError("phase_a 绑定只能由 Phase B 工厂注入")
    return create_review_request(
        run_dir,
        "R1_MODELING",
        {**bindings, "phase_a": phase_a_path},
        **request_options,
    )
