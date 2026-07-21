"""提供轻量科学存活检查与审核补充证据冻结。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shumozizi.core.io import (
    ContractError,
    relative_inside,
    resolve_inside,
    sha256_file,
)

VIABILITY_VERDICTS = {
    "PENDING",
    "VIABLE",
    "WEAK_BUT_REPAIRABLE",
    "ROUTE_AT_RISK",
    "ROUTE_FAILED",
}
FAILURE_ORIGINS = {
    "route",
    "implementation",
    "objective_mismatch",
    "data_limited",
    "budget_limited",
}
ACTION_STATUSES = {"pending", "completed", "accepted_risk"}
MINIMUM_SCIENTIFIC_CONTRACT_FIELDS = (
    "required_outputs",
    "core_objective",
    "hard_constraints",
    "baseline",
    "primary_model_family",
    "data_split",
    "primary_metrics",
    "positive_control",
    "route_failure_criterion",
    "fallback_trigger",
    "experiment_budget",
)
REVIEW_STAGES = {
    "R1_MODELING",
    "R2_EXPERIMENT",
    "R3_PAPER_LOGIC",
    "R4_FORMAT_VISUAL",
    "R5_COMPREHENSIVE",
}
SUPPLEMENTAL_ROLE_PREFIX = "supplemental_evidence:"

SUBSTANTIVE_R5_CHANGES = {
    "core_model",
    "core_data",
    "core_numeric_results",
    "core_conclusion",
    "major_figure",
    "p0_p1_reopened",
}
SCOPED_R5_CHANGES = {
    "typography",
    "typo",
    "pagination",
    "non_core_caption",
    "local_format",
}

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REQUIRED_HEADINGS = (
    "# Scientific Viability Check",
    "## Current Highest Risk",
    "## Falsifying Counterexample",
    "## Minimum Falsification Experiment",
    "## Actual Result",
    "## Baseline And Fallback Comparison",
    "## Decision And Reason",
    "## Remaining Budget And Investment Limit",
    "## Scientific Dimensions Synthesis",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _front_matter_text(metadata: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{header}\n---\n\n{body.rstrip()}\n"


def _read_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContractError(f"缺少文件: {path}") from exc
    if not text.startswith("---\n"):
        raise ContractError(f"Markdown 缺少 YAML front matter: {path}")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ContractError(f"Markdown front matter 未闭合: {path}")
    try:
        metadata = yaml.safe_load(text[4:marker])
    except yaml.YAMLError as exc:
        raise ContractError(f"Markdown front matter 格式错误: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ContractError("Markdown front matter 根节点必须是对象")
    return metadata, text[marker + 5 :]


def _source_records(run_dir: Path, source_paths: list[Path]) -> list[dict[str, str]]:
    records = []
    seen: set[str] = set()
    for source in source_paths:
        resolved = source.resolve()
        relative = relative_inside(run_dir, resolved).as_posix()
        if relative in seen:
            raise ContractError(f"科学存活检查包含重复来源: {relative}")
        if not resolved.is_file():
            raise ContractError(f"科学存活检查来源不存在: {relative}")
        seen.add(relative)
        records.append({"path": relative, "sha256": sha256_file(resolved)})
    return records


def _filled(value: Any) -> bool:
    text = str(value).strip()
    return len(text) >= 3 and not text.startswith(("待", "REPLACE"))


def create_minimum_scientific_contract(
    run_dir: Path,
    *,
    source_paths: list[Path] | None = None,
    values: dict[str, Any] | None = None,
    output_path: Path | None = None,
) -> Path:
    """创建正式实验前必须冻结的最低科学合同 Markdown。"""
    target = output_path or run_dir / "analysis/MINIMUM_SCIENTIFIC_CONTRACT.md"
    relative_inside(run_dir, target)
    if target.exists():
        raise ContractError("MINIMUM_SCIENTIFIC_CONTRACT.md 已存在，禁止覆盖冻结合同")
    defaults: dict[str, Any] = {
        "required_outputs": ["待冻结"],
        "core_objective": "待冻结",
        "hard_constraints": ["待冻结"],
        "baseline": "待冻结",
        "primary_model_family": "待冻结",
        "data_split": "待冻结",
        "primary_metrics": ["待冻结"],
        "positive_control": "待冻结",
        "route_failure_criterion": "待冻结",
        "fallback_trigger": "待冻结",
        "experiment_budget": "待冻结",
    }
    supplied = values or {}
    unknown = sorted(set(supplied) - set(MINIMUM_SCIENTIFIC_CONTRACT_FIELDS))
    if unknown:
        raise ContractError("最低科学合同包含未知字段: " + ", ".join(unknown))
    defaults.update(supplied)
    metadata = {
        "schema_name": "minimum_scientific_contract",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "frozen_at": _utc_now() if values else None,
        **defaults,
        "sources": _source_records(run_dir, source_paths or []),
    }
    body = """# Minimum Scientific Contract

本合同在正式实验前冻结 required outputs、目标、约束、比较口径、正控制、失败判据、fallback
触发条件和预算。普通参数、求解器、初始化、数值精度和同模型族局部修复不改变本合同；核心字段
变化必须重新判断路线并生成新的冻结版本，不能覆盖旧文件。
"""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_front_matter_text(metadata, body), encoding="utf-8", newline="\n")
    return target


def verify_minimum_scientific_contract(
    run_dir: Path,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    """复验最低科学合同字段、来源哈希和冻结时间。"""
    path = contract_path or run_dir / "analysis/MINIMUM_SCIENTIFIC_CONTRACT.md"
    errors: list[str] = []
    try:
        relative_inside(run_dir, path)
        metadata, body = _read_front_matter(path)
        required = {
            "schema_name",
            "schema_version",
            "run_id",
            "frozen_at",
            *MINIMUM_SCIENTIFIC_CONTRACT_FIELDS,
            "sources",
        }
        if set(metadata) != required:
            raise ContractError("最低科学合同字段不完整或包含未声明字段")
        if metadata["schema_name"] != "minimum_scientific_contract" or metadata[
            "schema_version"
        ] != "1.0":
            raise ContractError("最低科学合同版本不受支持")
        if metadata["run_id"] != run_dir.name or not metadata["frozen_at"]:
            raise ContractError("最低科学合同未绑定当前 run 或尚未冻结")
        for key in MINIMUM_SCIENTIFIC_CONTRACT_FIELDS:
            value = metadata[key]
            if isinstance(value, list):
                if not value or any(not _filled(item) for item in value):
                    raise ContractError(f"最低科学合同字段未冻结: {key}")
            elif not _filled(value):
                raise ContractError(f"最低科学合同字段未冻结: {key}")
        sources = metadata["sources"]
        if not isinstance(sources, list) or not sources:
            raise ContractError("最低科学合同必须绑定当前路线或模型规格来源")
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
                raise ContractError("最低科学合同来源格式错误")
            source_path = resolve_inside(run_dir, source["path"], must_exist=True)
            if sha256_file(source_path) != source["sha256"]:
                raise ContractError(f"最低科学合同来源哈希已变化: {source['path']}")
        if "# Minimum Scientific Contract" not in body:
            raise ContractError("最低科学合同 Markdown 缺少标题")
    except (ContractError, OSError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "contract_path": str(path)}


def create_scientific_viability(
    run_dir: Path,
    *,
    question_scope: list[str],
    source_paths: list[Path] | None = None,
    output_path: Path | None = None,
) -> Path:
    """创建可编辑的 Markdown 科学存活检查，不修改工作流状态。"""
    if not question_scope or any(not item.strip() for item in question_scope):
        raise ContractError("科学存活检查必须声明非空 question_scope")
    target = output_path or run_dir / "analysis/SCIENTIFIC_VIABILITY.md"
    relative_inside(run_dir, target)
    if target.exists():
        raise ContractError("SCIENTIFIC_VIABILITY.md 已存在，禁止覆盖已有判断")
    metadata = {
        "schema_name": "scientific_viability",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "question_scope": list(dict.fromkeys(question_scope)),
        "verdict": "PENDING",
        "failure_origin": None,
        "evaluated_at": None,
        "threshold_basis": "待根据题目误差、工程尺度、决策边界、baseline 或搜索域说明",
        "highest_risk": "待评估",
        "counterexample": "待设计",
        "falsification_experiment": "待执行",
        "experiment_result": "待记录真实结果",
        "baseline_fallback_comparison": "待比较",
        "decision_reason": "待评估",
        "next_action": "待根据实验结果决定",
        "action_status": "pending",
        "remaining_time_minutes": None,
        "investment_limit_minutes": None,
        "sources": _source_records(run_dir, source_paths or []),
    }
    body = """# Scientific Viability Check

## Current Highest Risk

只写当前最可能使路线失败的一个核心原因，不平均铺开检查项。

## Falsifying Counterexample

写出能够推翻当前路线的具体反例或正例条件。

## Minimum Falsification Experiment

描述成本最低且结果会改变路线决策的实验。

## Actual Result

只引用真实执行结果及冻结来源，不使用计划值替代。

## Baseline And Fallback Comparison

直接比较 primary、baseline 与可用 fallback；未完成的比较必须明确写为未完成。

## Decision And Reason

只选择 VIABLE、WEAK_BUT_REPAIRABLE、ROUTE_AT_RISK 或 ROUTE_FAILED，并说明为何改变行动。

## Remaining Budget And Investment Limit

记录判断时真实剩余分钟数，以及下一步允许投入的分钟上限。

## Scientific Dimensions Synthesis

用连续论证综合 Direct Answer、Information Value、Positive-Control Capability 和 Repairability，
不得写成四项 pass/fail 打勾表。
"""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_front_matter_text(metadata, body), encoding="utf-8", newline="\n")
    return target


def verify_scientific_viability(
    run_dir: Path,
    viability_path: Path | None = None,
    *,
    require_decision: bool = True,
    require_paper_eligibility: bool = False,
) -> dict[str, Any]:
    """复验 Markdown 判断、证据哈希和结论一致性。"""
    path = viability_path or run_dir / "analysis/SCIENTIFIC_VIABILITY.md"
    errors: list[str] = []
    verdict = "UNKNOWN"
    try:
        relative_inside(run_dir, path)
        metadata, body = _read_front_matter(path)
        required = {
            "schema_name",
            "schema_version",
            "run_id",
            "question_scope",
            "verdict",
            "failure_origin",
            "evaluated_at",
            "threshold_basis",
            "highest_risk",
            "counterexample",
            "falsification_experiment",
            "experiment_result",
            "baseline_fallback_comparison",
            "decision_reason",
            "next_action",
            "action_status",
            "remaining_time_minutes",
            "investment_limit_minutes",
            "sources",
        }
        if set(metadata) != required:
            raise ContractError("科学存活检查字段不完整或包含 v2 打勾字段")
        if metadata["schema_name"] != "scientific_viability" or metadata[
            "schema_version"
        ] != "2.0":
            raise ContractError("科学存活检查版本不受支持")
        if metadata["run_id"] != run_dir.name:
            raise ContractError("科学存活检查 run_id 与运行目录不一致")
        if not isinstance(metadata["question_scope"], list) or not metadata[
            "question_scope"
        ]:
            raise ContractError("科学存活检查 question_scope 不能为空")
        verdict = str(metadata["verdict"])
        if verdict not in VIABILITY_VERDICTS:
            raise ContractError(f"未知科学存活结论: {verdict}")
        if require_decision and verdict == "PENDING":
            raise ContractError("科学存活检查尚未形成结论")
        failure_origin = metadata["failure_origin"]
        if verdict == "ROUTE_FAILED" and failure_origin not in FAILURE_ORIGINS:
            raise ContractError("ROUTE_FAILED 必须声明合法 failure_origin")
        if verdict != "ROUTE_FAILED" and failure_origin is not None:
            raise ContractError("只有 ROUTE_FAILED 可以声明 failure_origin")
        if metadata["action_status"] not in ACTION_STATUSES:
            raise ContractError("科学存活检查 action_status 非法")
        sources = metadata["sources"]
        if not isinstance(sources, list):
            raise ContractError("科学存活 sources 必须为数组")
        if require_decision and not sources:
            raise ContractError("已决策的科学存活检查必须绑定至少一份来源")
        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
                raise ContractError("科学存活来源格式错误")
            relative = source["path"]
            if relative in seen:
                raise ContractError(f"科学存活来源重复: {relative}")
            seen.add(relative)
            source_path = resolve_inside(run_dir, relative, must_exist=True)
            if sha256_file(source_path) != source["sha256"]:
                raise ContractError(f"科学存活来源哈希已变化: {relative}")
        if require_decision:
            narrative_fields = (
                "threshold_basis",
                "highest_risk",
                "counterexample",
                "falsification_experiment",
                "experiment_result",
                "baseline_fallback_comparison",
                "decision_reason",
                "next_action",
            )
            for key in narrative_fields:
                if not _filled(metadata[key]):
                    raise ContractError(f"科学存活检查仍含待填写字段: {key}")
            for key in ("remaining_time_minutes", "investment_limit_minutes"):
                value = metadata[key]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ContractError(f"科学存活预算字段必须为非负整数分钟: {key}")
            if metadata["investment_limit_minutes"] > metadata["remaining_time_minutes"]:
                raise ContractError("下一步投入上限不能超过真实剩余时间")
            if not metadata["evaluated_at"]:
                raise ContractError("已决策的科学存活检查缺少 evaluated_at")
        missing_headings = [heading for heading in _REQUIRED_HEADINGS if heading not in body]
        if missing_headings:
            raise ContractError("科学存活 Markdown 缺少章节: " + ", ".join(missing_headings))
        paper_eligible = verdict == "VIABLE" or (
            verdict == "WEAK_BUT_REPAIRABLE"
            and metadata["action_status"] in {"completed", "accepted_risk"}
        )
        if require_paper_eligibility and not paper_eligible:
            raise ContractError(f"{verdict} 尚未满足正式全文组装条件")
    except (ContractError, OSError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    action = {
        "VIABLE": "continue_primary",
        "WEAK_BUT_REPAIRABLE": "targeted_repair",
        "ROUTE_AT_RISK": "parallel_fallback",
        "ROUTE_FAILED": "stop_and_reopen_route",
    }.get(verdict, "complete_assessment")
    paper_eligible = verdict == "VIABLE" or (
        verdict == "WEAK_BUT_REPAIRABLE"
        and metadata.get("action_status") in {"completed", "accepted_risk"}
    ) if "metadata" in locals() else False
    return {
        "valid": not errors,
        "errors": errors,
        "verdict": verdict,
        "action": action,
        "paper_eligible": paper_eligible,
    }


def freeze_supplemental_evidence(
    run_dir: Path,
    *,
    bundle_id: str,
    stage: str,
    issue: str,
    materials: dict[str, Path],
    question_id: str | None = None,
    source_version: str | None = None,
) -> Path:
    """冻结 Reviewer 针对当前问题请求的少量补充材料。"""
    if not _SLUG.fullmatch(bundle_id):
        raise ContractError("补充证据 bundle_id 只能包含字母、数字、点、下划线和连字符")
    if stage not in REVIEW_STAGES:
        raise ContractError(f"补充证据不支持审核阶段: {stage}")
    if len(issue.strip()) < 3 or not materials:
        raise ContractError("补充证据必须声明具体问题和至少一份材料")
    records = []
    seen_roles: set[str] = set()
    for evidence_id, source in materials.items():
        if not _SLUG.fullmatch(evidence_id):
            raise ContractError(f"补充证据 ID 不合法: {evidence_id}")
        role = f"{SUPPLEMENTAL_ROLE_PREFIX}{evidence_id}"
        if role in seen_roles:
            raise ContractError(f"补充证据 role 重复: {role}")
        resolved = source.resolve()
        relative = relative_inside(run_dir, resolved).as_posix()
        if not resolved.is_file():
            raise ContractError(f"补充证据文件不存在: {relative}")
        seen_roles.add(role)
        records.append({"role": role, "path": relative, "sha256": sha256_file(resolved)})
    metadata = {
        "schema_name": "supplemental_evidence_bundle",
        "schema_version": "1.0",
        "bundle_id": bundle_id,
        "run_id": run_dir.name,
        "stage": stage,
        "question_id": question_id,
        "issue": issue.strip(),
        "source_version": source_version or "current-run-snapshot",
        "materials": records,
        "generated_at": _utc_now(),
    }
    body = """# Supplemental Evidence Bundle

本文件仅回答 front matter 中声明的当前审核问题。材料仍位于运行目录内，审核请求必须同时绑定
本清单和每份材料；任一哈希变化都会使请求失效。本清单不得用于读取历史审核结论或作者辩解。
"""
    target = run_dir / "review" / "supplemental" / bundle_id / "SUPPLEMENTAL_EVIDENCE.md"
    if target.exists():
        raise ContractError("补充证据 bundle_id 已存在，禁止覆盖")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_front_matter_text(metadata, body), encoding="utf-8", newline="\n")
    return target


def verify_supplemental_evidence(
    run_dir: Path,
    bundle_path: Path,
    *,
    stage: str | None = None,
    question_id: str | None = None,
) -> dict[str, Any]:
    """复验补充证据范围、路径和哈希。"""
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    try:
        relative_inside(run_dir, bundle_path)
        metadata, _ = _read_front_matter(bundle_path)
        required = {
            "schema_name",
            "schema_version",
            "bundle_id",
            "run_id",
            "stage",
            "question_id",
            "issue",
            "source_version",
            "materials",
            "generated_at",
        }
        if set(metadata) != required:
            raise ContractError("补充证据清单字段不完整或包含未声明字段")
        if metadata["schema_name"] != "supplemental_evidence_bundle" or metadata[
            "schema_version"
        ] != "1.0":
            raise ContractError("补充证据清单版本不受支持")
        if metadata["run_id"] != run_dir.name:
            raise ContractError("补充证据 run_id 与运行目录不一致")
        if stage is not None and metadata["stage"] != stage:
            raise ContractError("补充证据审核阶段与请求不一致")
        if question_id is not None and metadata["question_id"] != question_id:
            raise ContractError("补充证据 question_id 与请求不一致")
        if len(str(metadata["issue"]).strip()) < 3 or not metadata["materials"]:
            raise ContractError("补充证据缺少当前问题或材料")
        roles: set[str] = set()
        for material in metadata["materials"]:
            if not isinstance(material, dict) or set(material) != {"role", "path", "sha256"}:
                raise ContractError("补充证据 material 格式错误")
            role = material["role"]
            if not str(role).startswith(SUPPLEMENTAL_ROLE_PREFIX) or role in roles:
                raise ContractError(f"补充证据 role 非法或重复: {role}")
            roles.add(role)
            path = resolve_inside(run_dir, material["path"], must_exist=True)
            if sha256_file(path) != material["sha256"]:
                raise ContractError(f"补充证据哈希已变化: {material['path']}")
    except (ContractError, OSError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "metadata": metadata}


def verify_supplemental_bindings(
    run_dir: Path,
    *,
    stage: str,
    question_id: str | None,
    bindings: dict[str, Path],
) -> None:
    """要求动态补充材料与同一冻结清单精确对应。"""
    supplemental = {
        role: path
        for role, path in bindings.items()
        if role.startswith(SUPPLEMENTAL_ROLE_PREFIX)
    }
    manifest = bindings.get("supplemental_evidence_manifest")
    if not supplemental and manifest is None:
        return
    if not supplemental or manifest is None:
        raise ContractError("补充证据必须同时绑定 manifest 和至少一份 supplemental_evidence 材料")
    report = verify_supplemental_evidence(
        run_dir,
        manifest,
        stage=stage,
        question_id=question_id,
    )
    if not report["valid"]:
        raise ContractError("补充证据清单复验失败: " + "; ".join(report["errors"]))
    expected = {
        item["role"]: (item["path"], item["sha256"])
        for item in report["metadata"]["materials"]
    }
    actual = {
        role: (relative_inside(run_dir, path).as_posix(), sha256_file(path))
        for role, path in supplemental.items()
    }
    if actual != expected:
        raise ContractError("审核请求的补充证据与冻结 bundle 不一致")


def r5_review_mode_for_changes(changes: list[str]) -> str:
    """按实质变化判断 R5 是否需要完整重审。"""
    normalized = {item.strip() for item in changes if item.strip()}
    unknown = sorted(normalized - SUBSTANTIVE_R5_CHANGES - SCOPED_R5_CHANGES)
    if unknown:
        raise ContractError("未知 R5 变化类别: " + ", ".join(unknown))
    if normalized & SUBSTANTIVE_R5_CHANGES:
        return "full_scientific"
    if normalized:
        return "scoped_recheck"
    return "none"
