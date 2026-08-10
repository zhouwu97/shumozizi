"""对冻结论文 PDF 执行不受既有清单约束的开放式视觉缺口审查。"""

from __future__ import annotations

from pathlib import Path
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
from shumozizi.simple.state import read_simple_state, utc_now

VISUAL_DISCOVERY_PATH = Path("review/VISUAL_DISCOVERY.json")
_VISUAL_REQUIREMENTS_PATH = Path("paper/generated/VISUAL_REQUIREMENTS.json")
_DIMENSIONS = (
    "model_object_visibility",
    "decisive_evidence_visibility",
    "mechanism_visibility",
    "boundary_uncertainty_visibility",
    "paper_size_legibility",
    "whole_paper_visual_rhythm",
)
_FIGURE_ACTIONS = frozenset({"ADD_FIGURE", "REVISE_FIGURE", "REPLACE_FIGURE"})
_ACTIONS = _FIGURE_ACTIONS | {"RELAYOUT"}
_SEVERITIES = frozenset({"P0", "P1", "P2"})


def _paper_pdf(root: Path, pdf_path: str | Path | None) -> Path:
    """解析运行目录内待审 PDF，并禁止把非 PDF 文件伪装成审查输入。"""
    if pdf_path is not None:
        raw = str(pdf_path)
        if Path(raw).is_absolute():
            try:
                candidate = Path(raw).resolve()
                candidate.relative_to(root)
            except ValueError as exc:
                raise ContractError("视觉发现 PDF 必须位于当前运行目录内") from exc
            if not candidate.is_file():
                raise ContractError(f"视觉发现 PDF 不存在: {candidate}")
        else:
            candidate = resolve_inside(root, raw, must_exist=True)
        if candidate.suffix.casefold() != ".pdf":
            raise ContractError("视觉发现输入必须是 PDF")
        return candidate
    for relative in (
        "paper/final.pdf",
        "paper/longform-draft.pdf",
        "paper/draft-1.pdf",
        "paper/reviewable-draft.pdf",
        "paper/external-author/draft.pdf",
    ):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    raise ContractError("缺少可供开放式视觉审查的冻结论文 PDF")


def _discovery_enabled(root: Path) -> bool:
    """仅对声明 1.2 开放式审查政策的新视觉需求启用候选硬门。"""
    path = root / _VISUAL_REQUIREMENTS_PATH
    if not path.is_file():
        return False
    try:
        payload = load_json(path)
    except ContractError:
        return False
    policy = payload.get("review_policy", {})
    return (
        payload.get("schema_version") == "1.2"
        and isinstance(policy, dict)
        and policy.get("mode")
        == "open_world_discovery_then_requirement_reconciliation"
    )


def build_visual_discovery_prompt(
    run_dir: Path, pdf_path: str | Path | None = None
) -> str:
    """生成只允许读取冻结 PDF 的开放式视觉审查提示词。

    Args:
        run_dir: 当前数学建模运行目录。
        pdf_path: 可选的运行目录内 PDF 路径；默认选择当前正式稿。

    Returns:
        可交给全新独立审核上下文的中文提示词。
    """
    root = run_dir.resolve()
    pdf = _paper_pdf(root, pdf_path)
    return f"""你是独立的数学建模论文视觉审稿人。只读取冻结 PDF：
{pdf}

不得查看作者的图表清单、机会池、源码、历史审核或解释。请从零判断整篇论文是否缺少关键图，
而不是核对作者已经列出的项目。逐项审查：数学对象是否可见、决定性证据是否可见、机制路径
是否可见、约束/边界/不确定性是否可见、缩到论文实际尺寸后是否可读、整篇视觉节奏是否合理。

最多保留 5 个最高价值 finding。action 只能为 ADD_FIGURE、REVISE_FIGURE、
REPLACE_FIGURE 或 RELAYOUT；severity 使用 P0、P1、P2。没有 finding 时，六个维度仍须分别
给出 sufficient 和实质理由。输出一个 JSON 对象，仅含 dimensions 与 findings。"""


def _normalized_assessment(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """校验审核者给出的六维判断和最高价值 findings。"""
    if not isinstance(payload, dict):
        raise ContractError("开放式视觉审查结果必须是对象")
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(_DIMENSIONS):
        raise ContractError("开放式视觉审查必须且只能覆盖规定的六个维度")
    normalized_dimensions: dict[str, Any] = {}
    gap_count = 0
    for key in _DIMENSIONS:
        item = dimensions.get(key)
        if not isinstance(item, dict):
            raise ContractError(f"视觉审查维度 {key} 必须是对象")
        status = item.get("status")
        rationale = item.get("rationale")
        if status not in {"sufficient", "gap"}:
            raise ContractError(f"视觉审查维度 {key}.status 必须为 sufficient 或 gap")
        if not isinstance(rationale, str) or len(rationale.strip()) < 8:
            raise ContractError(f"视觉审查维度 {key} 缺少实质理由")
        gap_count += int(status == "gap")
        normalized_dimensions[key] = {
            "status": status,
            "rationale": rationale.strip(),
        }
    findings = payload.get("findings", [])
    if not isinstance(findings, list) or len(findings) > 5:
        raise ContractError("开放式视觉审查 findings 必须是最多 5 项的数组")
    normalized_findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in findings:
        if not isinstance(raw, dict):
            raise ContractError("开放式视觉 finding 必须是对象")
        finding_id = str(raw.get("finding_id", "")).strip()
        severity = raw.get("severity")
        action = raw.get("action")
        if not finding_id or finding_id in seen:
            raise ContractError("开放式视觉 finding_id 不能为空或重复")
        if severity not in _SEVERITIES or action not in _ACTIONS:
            raise ContractError("视觉 finding 的 severity 或 action 无效")
        normalized = {
            "finding_id": finding_id,
            "severity": severity,
            "action": action,
            "title": str(raw.get("title", "")).strip(),
            "evidence": str(raw.get("evidence", "")).strip(),
            "required_change": str(raw.get("required_change", "")).strip(),
            "question_id": (
                str(raw["question_id"]).strip()
                if raw.get("question_id") is not None
                else None
            ),
            "target_figure_ids": sorted(
                {str(item).strip() for item in raw.get("target_figure_ids", []) if str(item).strip()}
            ),
        }
        if any(len(normalized[key]) < 4 for key in ("title", "evidence", "required_change")):
            raise ContractError(f"视觉 finding {finding_id} 缺少实质标题、证据或修改动作")
        seen.add(finding_id)
        normalized_findings.append(normalized)
    if gap_count and not normalized_findings:
        raise ContractError("六维审查存在 gap 时必须给出至少一个 finding")
    if normalized_findings and not gap_count:
        raise ContractError("存在 finding 时至少一个六维结论必须标记为 gap")
    return normalized_dimensions, normalized_findings


def _opportunity_id(finding_id: str) -> str:
    """为开放式 finding 生成稳定且与旧需求隔离的视觉机会 ID。"""
    safe = "".join(char if char.isalnum() or char in "-_." else "-" for char in finding_id)
    return f"visual-discovery-{safe}"


def _sync_discovery_opportunities(
    root: Path,
    findings: list[dict[str, Any]],
    *,
    reviewer_context_id: str,
    pdf_sha256: str,
) -> None:
    """把当前高影响缺图同步到机会池，并移除已被新 PDF 审查消除的旧项。"""
    from shumozizi.simple.visual_opportunities import (
        add_visual_opportunity,
        build_visual_opportunity_pool,
        read_visual_opportunity_pool,
        write_visual_opportunity_pool,
    )

    try:
        pool = read_visual_opportunity_pool(root)
    except (ContractError, OSError, TypeError, ValueError):
        pool = build_visual_opportunity_pool(root, opportunities=[], write=False)
    active = {
        _opportunity_id(item["finding_id"])
        for item in findings
        if item["severity"] in {"P0", "P1"} and item["action"] in _FIGURE_ACTIONS
    }
    pool["opportunities"] = [
        item
        for item in pool.get("opportunities", [])
        if not (
            isinstance(item, dict)
            and item.get("origin") == "visual_discovery"
            and item.get("opportunity_id") not in active
        )
    ]
    pool["status"] = "current" if pool["opportunities"] else "draft"
    write_visual_opportunity_pool(root, pool)
    known = {
        str(item.get("opportunity_id"))
        for item in pool.get("opportunities", [])
        if isinstance(item, dict)
    }
    for item in findings:
        opportunity_id = _opportunity_id(item["finding_id"])
        if (
            item["severity"] not in {"P0", "P1"}
            or item["action"] not in _FIGURE_ACTIONS
            or opportunity_id in known
        ):
            continue
        add_visual_opportunity(
            root,
            opportunity_id=opportunity_id,
            question_id=item["question_id"],
            visual_question=item["required_change"],
            atomic_claim=item["evidence"],
            candidate_archetypes=["model-native evidence figure"],
            origin="visual_discovery",
            provenance={
                "discovery_finding_id": item["finding_id"],
                "discovery_severity": item["severity"],
                "discovery_action": item["action"],
                "discovery_pdf_sha256": pdf_sha256,
                "reviewer_context_id": reviewer_context_id,
            },
        )


def record_visual_discovery(
    run_dir: Path,
    payload: dict[str, Any],
    *,
    reviewer_context_id: str,
    pdf_path: str | Path | None = None,
) -> dict[str, Any]:
    """记录一次开放式视觉审查，并把高影响缺图路由到 Visual Sandbox。

    Args:
        run_dir: 当前数学建模运行目录。
        payload: 独立审核者返回的 ``dimensions`` 与 ``findings``。
        reviewer_context_id: 全新独立审核上下文标识。
        pdf_path: 可选的运行目录内冻结 PDF。

    Returns:
        已绑定 PDF、论证修订号并原子保存的审查文档。
    """
    if not isinstance(reviewer_context_id, str) or not reviewer_context_id.strip():
        raise ContractError("开放式视觉审查必须绑定独立 reviewer_context_id")
    root = run_dir.resolve()
    pdf = _paper_pdf(root, pdf_path)
    dimensions, findings = _normalized_assessment(payload)
    state = read_simple_state(root)
    document = {
        "schema_name": "visual_discovery_audit",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "reviewer_context_id": reviewer_context_id.strip(),
        "blind_to_requirements": True,
        "input_scope": "frozen_pdf_only",
        "inputs": {
            "pdf_path": relative_inside(root, pdf).as_posix(),
            "pdf_sha256": sha256_file(pdf),
            "argument_revision": int(state.get("argument_revision", 0)),
        },
        "dimensions": dimensions,
        "findings": findings,
        "recorded_at": utc_now(),
    }
    require_valid(document, "visual_discovery_audit")
    atomic_json(root / VISUAL_DISCOVERY_PATH, document)
    _sync_discovery_opportunities(
        root,
        findings,
        reviewer_context_id=reviewer_context_id.strip(),
        pdf_sha256=document["inputs"]["pdf_sha256"],
    )
    return document


def _current_figure_resolves(root: Path, finding_id: str) -> bool:
    """确认高影响 finding 已由 current 正式图实际承接。"""
    path = root / "figures/index.json"
    if not path.is_file():
        return False
    try:
        figures = load_json(path).get("figures", [])
    except ContractError:
        return False
    expected_opportunity = _opportunity_id(finding_id)
    return any(
        isinstance(item, dict)
        and item.get("status") == "current"
        and item.get("paper_allowed") is not False
        and (
            item.get("visual_opportunity_id") == expected_opportunity
            or finding_id in item.get("visual_discovery_finding_ids", [])
        )
        for item in figures
    )


def validate_visual_discovery_closure(run_dir: Path) -> list[str]:
    """复验开放式审查的新鲜度及 P0/P1 finding 的真实关闭状态。"""
    root = run_dir.resolve()
    if not _discovery_enabled(root):
        return []
    path = root / VISUAL_DISCOVERY_PATH
    if not path.is_file():
        return [
            "VISUAL_DISCOVERY_REQUIRED：缺少只读冻结 PDF 的开放式视觉缺口审查；"
            "逐条处置既有视觉需求不能替代整篇发现。"
        ]
    try:
        document = load_json(path)
        require_valid(document, "visual_discovery_audit")
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return [f"VISUAL_DISCOVERY_INVALID：开放式视觉审查无法读取或验证：{exc}"]
    errors: list[str] = []
    state = read_simple_state(root)
    if document.get("run_id") != state.get("run_id"):
        errors.append("VISUAL_DISCOVERY_STALE：审查 run_id 与当前运行不一致")
    if document.get("blind_to_requirements") is not True or document.get("input_scope") != "frozen_pdf_only":
        errors.append("VISUAL_DISCOVERY_INVALID：审查未保持 frozen_pdf_only 的清单盲态")
    inputs = document.get("inputs", {})
    try:
        pdf = resolve_inside(root, str(inputs.get("pdf_path", "")), must_exist=True)
        if sha256_file(pdf) != inputs.get("pdf_sha256"):
            errors.append("VISUAL_DISCOVERY_STALE：冻结 PDF 已变化，必须重新开放式审查")
    except (ContractError, OSError) as exc:
        errors.append(f"VISUAL_DISCOVERY_STALE：冻结 PDF 绑定无效：{exc}")
    if inputs.get("argument_revision") != int(state.get("argument_revision", 0)):
        errors.append("VISUAL_DISCOVERY_STALE：argument_revision 已变化，必须重新开放式审查")
    for finding in document.get("findings", []):
        if not isinstance(finding, dict) or finding.get("severity") not in {"P0", "P1"}:
            continue
        finding_id = str(finding.get("finding_id", "<unknown>"))
        if finding.get("action") in _FIGURE_ACTIONS and _current_figure_resolves(root, finding_id):
            continue
        if finding.get("action") == "RELAYOUT":
            errors.append(
                f"VISUAL_DISCOVERY_OPEN：{finding_id} ({finding.get('severity')}) 要求重新排版；"
                "必须提交修订 PDF 并重新执行开放式审查。"
            )
        else:
            errors.append(
                f"VISUAL_DISCOVERY_OPEN：{finding_id} ({finding.get('severity')}) 尚未由 current 正式图关闭；"
                "逐需求 DROP 不得覆盖开放式高影响 finding。"
            )
    return errors
