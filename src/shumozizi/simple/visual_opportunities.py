"""从研究素材生成视觉机会池，并记录逐图新鲜评阅者的动作。

视觉机会先回答“图要让评委看懂什么”，再选择图形原型；因此它不再假设每个
问题必须有一张 hero 图，也允许一个机会拆成互补图或被明确放弃。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
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
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.materials import material_pool_digest, read_material_pool
from shumozizi.paper.policy import policy_fingerprint
from shumozizi.simple.state import read_simple_state, utc_now

VISUAL_OPPORTUNITY_POOL_PATH = Path("figures/visual-opportunities.json")
VISUAL_REVIEW_ROOT = Path("figures/reviews")
VISUAL_VERDICTS = frozenset({"PROMOTE", "REVISE", "SPLIT", "DROP"})
_STATUS_BY_VERDICT = {"PROMOTE": "promote", "REVISE": "revise", "SPLIT": "split", "DROP": "drop"}


def _atomic_text(path: Path, value: str) -> None:
    """在同目录原子替换视觉批评 Markdown。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _repo_root_for_run(run_dir: Path) -> Path:
    """返回包含政策文件的代码仓库根，测试运行目录不影响指纹。"""
    del run_dir
    return resolve_repo_root(Path(__file__))


def _storyboard_digest(run_dir: Path) -> str | None:
    """返回当前故事板文件摘要，缺失时保持显式空值。"""
    path = run_dir.resolve() / "paper/generated/research_storyboard.json"
    return sha256_file(path) if path.is_file() else None


def _knowledge_check(run_dir: Path) -> dict[str, Any]:
    """在绘图机会阶段检查知识库，保持 advisory 且不自动采用模式。"""
    report_path = run_dir / "figures/generated/learned-pattern-suggestions.json"
    try:
        # 延迟导入避免知识使用模块反向加载视觉机会池造成循环依赖。
        from shumozizi.knowledge.usage import build_visual_pattern_suggestions

        report = build_visual_pattern_suggestions(run_dir)
        return {
            "status": str(report.get("status", "unavailable")),
            "advisory_only": True,
            "recommendation_count": len(report.get("recommendations", [])),
            "rejection_count": len(report.get("rejections", [])),
            "usable_pattern_ids": sorted(
                {
                    str(item.get("learned_pattern_id"))
                    for item in report.get("recommendations", [])
                    if isinstance(item, dict) and item.get("learned_pattern_id")
                }
            ),
            "report_path": report_path.relative_to(run_dir).as_posix(),
            "report_sha256": sha256_file(report_path) if report_path.is_file() else None,
            "reason": report.get("reason"),
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {
            "status": "unavailable",
            "advisory_only": True,
            "recommendation_count": 0,
            "rejection_count": 0,
            "usable_pattern_ids": [],
            "report_path": report_path.relative_to(run_dir).as_posix(),
            "report_sha256": None,
            "reason": str(exc),
        }


def _opportunity(
    *,
    opportunity_id: str,
    question_id: str | None,
    visual_question: str,
    atomic_claim: str,
    source_result_ids: Iterable[str] = (),
    source_figure_ids: Iterable[str] = (),
    candidate_archetypes: Iterable[str] = ("undecided",),
    paper_location: str | None = None,
) -> dict[str, Any]:
    """构造一条不绑定具体渲染脚本的视觉机会。"""
    if not opportunity_id.strip() or not visual_question.strip() or not atomic_claim.strip():
        raise ContractError("视觉机会 ID、视觉问题和原子主张不能为空")
    archetypes = sorted({str(item) for item in candidate_archetypes if str(item).strip()})
    if not archetypes:
        raise ContractError("视觉机会至少需要一个候选图形原型")
    return {
        "opportunity_id": opportunity_id,
        "question_id": question_id,
        "visual_question": visual_question.strip(),
        "atomic_claim": atomic_claim.strip(),
        "source_result_ids": sorted({str(item) for item in source_result_ids}),
        "source_figure_ids": sorted({str(item) for item in source_figure_ids}),
        "candidate_archetypes": archetypes,
        "selected_archetype": None,
        "paper_location": paper_location,
        "status": "candidate",
        "critic_verdict": None,
        "critic_path": None,
    }


def _from_materials(run_dir: Path) -> list[dict[str, Any]]:
    """把素材池中适合视觉化的内容转换为候选机会。"""
    try:
        pool = read_material_pool(run_dir)
    except ContractError:
        return []
    opportunities: list[dict[str, Any]] = []
    for item in pool.get("items", []):
        category = item.get("category")
        if category not in {"Structural Observation", "Mechanism", "Boundary/Robustness", "Visual Opportunity"}:
            continue
        question_id = item.get("question_id")
        question = str(question_id) if isinstance(question_id, str) else None
        archetypes = item.get("media_candidates") or ("undecided",)
        opportunities.append(
            _opportunity(
                opportunity_id=f"visual-{item['material_id']}",
                question_id=question,
                visual_question=f"如何让评委直接看到：{item['title']}？",
                atomic_claim=item["content"],
                source_result_ids=item.get("source_result_ids", []),
                source_figure_ids=item.get("source_figure_ids", []),
                candidate_archetypes=archetypes,
            )
        )
    return opportunities


def build_visual_opportunity_pool(
    run_dir: Path,
    *,
    opportunities: Iterable[dict[str, Any]] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """生成视觉机会池；显式机会优先于自动候选。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    raw_items = list(opportunities) if opportunities is not None else _from_materials(root)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ContractError("视觉机会必须是对象")
        item = _opportunity(
            opportunity_id=str(raw.get("opportunity_id", "")),
            question_id=raw.get("question_id") if isinstance(raw.get("question_id"), str) else None,
            visual_question=str(raw.get("visual_question", "")),
            atomic_claim=str(raw.get("atomic_claim", "")),
            source_result_ids=raw.get("source_result_ids", []),
            source_figure_ids=raw.get("source_figure_ids", []),
            candidate_archetypes=raw.get("candidate_archetypes") or ["undecided"],
            paper_location=raw.get("paper_location") if isinstance(raw.get("paper_location"), str) else None,
        )
        for field in ("selected_archetype", "status", "critic_verdict", "critic_path", "decision_note"):
            if field in raw:
                item[field] = raw[field]
        if item["opportunity_id"] in seen:
            raise ContractError(f"视觉机会 ID 重复: {item['opportunity_id']}")
        seen.add(item["opportunity_id"])
        normalized.append(item)
    payload: dict[str, Any] = {
        "schema_name": "visual_opportunity_pool",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "policy_fingerprint": policy_fingerprint(_repo_root_for_run(root), "visual"),
        "material_pool_digest": material_pool_digest(root),
        "storyboard_digest": _storyboard_digest(root),
        "generated_at": utc_now(),
        "status": "current" if opportunities is not None and normalized else "draft",
        "knowledge_check": _knowledge_check(root),
        "opportunities": normalized,
    }
    require_valid(payload, "visual_opportunity_pool")
    if write:
        write_visual_opportunity_pool(root, payload)
    return payload


def write_visual_opportunity_pool(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """校验并原子保存视觉机会池。"""
    root = run_dir.resolve()
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        raise ContractError("视觉机会池 run_id 与运行不一致")
    require_valid(payload, "visual_opportunity_pool")
    atomic_json(root / VISUAL_OPPORTUNITY_POOL_PATH, payload)
    return payload


def read_visual_opportunity_pool(run_dir: Path) -> dict[str, Any]:
    """读取并验证视觉机会池。"""
    payload = load_json(run_dir.resolve() / VISUAL_OPPORTUNITY_POOL_PATH)
    require_valid(payload, "visual_opportunity_pool")
    return payload


def _review_markdown(opportunity: dict[str, Any], review: dict[str, Any], verdict: str) -> str:
    """把批评意见渲染成作者可读的评阅记录。"""
    lines = [
        f"# Visual critic: {opportunity['opportunity_id']}",
        "",
        f"结论：**{verdict}**",
        "",
        f"视觉问题：{opportunity['visual_question']}",
        f"原子主张：{opportunity['atomic_claim']}",
        "",
    ]
    for key, label in (
        ("observed", "图上实际看到什么"),
        ("mechanism", "机制是否可解释"),
        ("boundary", "边界是否诚实"),
        ("action", "下一步动作"),
    ):
        lines.extend([f"## {label}", "", str(review.get(key, "待填写。")), ""])
    return "\n".join(lines)


def record_visual_critic(
    run_dir: Path,
    opportunity_id: str,
    *,
    verdict: str,
    review: dict[str, Any],
    reviewer_context_id: str,
    fresh: bool = True,
    candidate_png: str | None = None,
    candidate_pdf: str | None = None,
    design_contract_path: str | None = None,
) -> dict[str, Any]:
    """记录一次新鲜视觉批评并把 PROMOTE/REVISE/SPLIT/DROP 写回机会池。"""
    if verdict not in VISUAL_VERDICTS:
        raise ContractError("visual critic verdict 必须为 PROMOTE、REVISE、SPLIT 或 DROP")
    if fresh and (not isinstance(reviewer_context_id, str) or not reviewer_context_id.strip()):
        raise ContractError("新鲜视觉批评必须绑定独立 reviewer_context_id")
    if not isinstance(review, dict):
        raise ContractError("视觉批评 review 必须是对象")
    required = ("observed", "mechanism", "boundary", "action")
    missing = [key for key in required if not isinstance(review.get(key), str) or not review[key].strip()]
    if missing:
        raise ContractError("视觉批评缺少实质字段: " + "、".join(missing))
    root = run_dir.resolve()
    payload = read_visual_opportunity_pool(root)
    target = next(
        (item for item in payload["opportunities"] if item.get("opportunity_id") == opportunity_id),
        None,
    )
    if target is None:
        raise ContractError(f"找不到视觉机会: {opportunity_id}")
    version = str(review.get("candidate_version", "v1"))
    candidate_png = candidate_png or (
        str(review.get("candidate_png_path")) if review.get("candidate_png_path") else None
    )
    candidate_pdf = candidate_pdf or (
        str(review.get("candidate_pdf_path")) if review.get("candidate_pdf_path") else None
    )
    design_contract_path = design_contract_path or (
        str(review.get("design_contract_path")) if review.get("design_contract_path") else None
    )
    artifact_binding: dict[str, Any] = {
        "candidate_png_path": None,
        "candidate_png_sha256": None,
        "candidate_pdf_path": None,
        "candidate_pdf_sha256": None,
        "design_contract_path": None,
        "design_contract_sha256": None,
        "visual_policy_fingerprint": policy_fingerprint(_repo_root_for_run(root), "visual"),
        "artifact_binding_complete": False,
    }
    if candidate_png or candidate_pdf or design_contract_path:
        if not all((candidate_png, candidate_pdf, design_contract_path)):
            raise ContractError("视觉批评的候选绑定必须同时提供 PNG、PDF 和 design-contract.json")
        png_path = resolve_inside(root, str(candidate_png), must_exist=True)
        pdf_path = resolve_inside(root, str(candidate_pdf), must_exist=True)
        contract_path = resolve_inside(root, str(design_contract_path), must_exist=True)
        if png_path.suffix.casefold() != ".png" or pdf_path.suffix.casefold() != ".pdf":
            raise ContractError("视觉批评候选绑定必须是 PNG 与 PDF")
        if png_path.parent.resolve() != pdf_path.parent.resolve() or png_path.parent.resolve() != contract_path.parent.resolve():
            raise ContractError("视觉批评的 PNG、PDF 和设计合同必须来自同一候选版本目录")
        artifact_binding.update(
            {
                "candidate_png_path": relative_inside(root, png_path).as_posix(),
                "candidate_png_sha256": sha256_file(png_path),
                "candidate_pdf_path": relative_inside(root, pdf_path).as_posix(),
                "candidate_pdf_sha256": sha256_file(pdf_path),
                "design_contract_path": relative_inside(root, contract_path).as_posix(),
                "design_contract_sha256": sha256_file(contract_path),
                "artifact_binding_complete": True,
            }
        )
    review_dir = root / VISUAL_REVIEW_ROOT / opportunity_id
    review_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "1.0",
        "run_id": payload["run_id"],
        "opportunity_id": opportunity_id,
        "candidate_version": version,
        "verdict": verdict,
        "reviewer_context_id": reviewer_context_id,
        "fresh": fresh,
        "review": review,
        **artifact_binding,
        "recorded_at": utc_now(),
    }
    json_path = review_dir / f"{version}.json"
    atomic_json(json_path, record)
    md_path = review_dir / f"{version}.md"
    _atomic_text(md_path, _review_markdown(target, review, verdict))
    target["status"] = _STATUS_BY_VERDICT[verdict]
    target["critic_verdict"] = verdict
    target["critic_path"] = md_path.relative_to(root).as_posix()
    target["critic_context_id"] = reviewer_context_id
    write_visual_opportunity_pool(root, payload)
    return record


def add_companion_figure_opportunity(
    run_dir: Path,
    *,
    opportunity_id: str,
    question_id: str | None,
    visual_question: str,
    atomic_claim: str,
    candidate_archetypes: Iterable[str],
    reviewer_context_id: str,
    finding_id: str,
) -> dict[str, Any]:
    """把论文冷读提出的 ADD_COMPANION_FIGURE 写入 living opportunity pool。"""
    if not reviewer_context_id.strip() or not finding_id.strip():
        raise ContractError("伴随图机会必须绑定 reviewer_context_id 和 finding_id")
    root = run_dir.resolve()
    payload = read_visual_opportunity_pool(root)
    if any(item.get("opportunity_id") == opportunity_id for item in payload["opportunities"]):
        raise ContractError(f"视觉机会已存在: {opportunity_id}")
    item = _opportunity(
        opportunity_id=opportunity_id,
        question_id=question_id,
        visual_question=visual_question,
        atomic_claim=atomic_claim,
        candidate_archetypes=candidate_archetypes,
    )
    item["origin"] = "paper_cold_reader"
    item["finding_id"] = finding_id
    item["reviewer_context_id"] = reviewer_context_id
    payload["opportunities"].append(item)
    write_visual_opportunity_pool(root, payload)
    return item


def validate_visual_critic_record(
    run_dir: Path,
    opportunity_id: str,
    version: str,
    *,
    require_artifact_binding: bool = False,
) -> dict[str, Any]:
    """复验指定视觉批评记录，并可执行候选产物硬门。"""
    root = run_dir.resolve()
    path = root / VISUAL_REVIEW_ROOT / opportunity_id / f"{version}.json"
    payload = load_json(path)
    pool = read_visual_opportunity_pool(root)
    if payload.get("run_id") != pool.get("run_id") or payload.get("opportunity_id") != opportunity_id:
        raise ContractError("视觉批评回执与当前机会池不一致")
    if payload.get("verdict") not in VISUAL_VERDICTS:
        raise ContractError("视觉批评回执 verdict 无效")
    if require_artifact_binding:
        if payload.get("fresh") is not True or not str(payload.get("reviewer_context_id", "")).strip():
            raise ContractError("视觉批评硬门要求 fresh=true 且有 reviewer_context_id")
        if payload.get("candidate_version") != version:
            raise ContractError("视觉批评候选版本与待晋级版本不一致")
        if payload.get("artifact_binding_complete") is not True:
            raise ContractError("视觉批评没有绑定完整 PNG、PDF 和 design-contract 产物")
        expected_policy = policy_fingerprint(_repo_root_for_run(root), "visual")
        if payload.get("visual_policy_fingerprint") != expected_policy:
            raise ContractError("视觉批评未绑定当前视觉政策")
        candidate_paths = []
        for key, suffix in (("candidate_png_path", ".png"), ("candidate_pdf_path", ".pdf")):
            relative = payload.get(key)
            if not isinstance(relative, str) or not relative.strip():
                raise ContractError(f"视觉批评缺少 {key}")
            candidate = resolve_inside(root, relative, must_exist=True)
            if candidate.suffix.casefold() != suffix:
                raise ContractError(f"视觉批评 {key} 后缀不正确")
            expected_hash = payload.get(key.replace("_path", "_sha256"))
            if expected_hash != sha256_file(candidate):
                raise ContractError(f"视觉批评绑定的 {key} 已变化")
            candidate_paths.append(candidate)
        contract_relative = payload.get("design_contract_path")
        if not isinstance(contract_relative, str) or not contract_relative.strip():
            raise ContractError("视觉批评缺少 design_contract_path")
        contract_path = resolve_inside(root, contract_relative, must_exist=True)
        if contract_path.name != "design-contract.json":
            raise ContractError("视觉批评设计合同文件名必须为 design-contract.json")
        if payload.get("design_contract_sha256") != sha256_file(contract_path):
            raise ContractError("视觉批评绑定的 design-contract.json 已变化")
        if any(candidate.parent.resolve() != contract_path.parent.resolve() for candidate in candidate_paths):
            raise ContractError("视觉批评的候选图与设计合同必须来自同一版本目录")
        from shumozizi.simple.figure_design import (
            figure_design_contract_freshness,
            read_figure_design_contract,
        )

        contract = read_figure_design_contract(root, opportunity_id, version)
        if contract_path.resolve() != (
            root / "figures/work" / opportunity_id / version / "design-contract.json"
        ).resolve():
            raise ContractError("视觉批评设计合同路径与机会/版本不一致")
        freshness = figure_design_contract_freshness(root, contract)
        if not freshness["current"]:
            raise ContractError("视觉设计合同已失效: " + "、".join(freshness["stale_fields"]))
        if payload.get("visual_policy_fingerprint") != contract.get("policy_fingerprint"):
            raise ContractError("视觉批评和设计合同的视觉政策指纹不一致")
        pool_freshness = visual_opportunity_pool_freshness(root)
        if not pool_freshness["current"]:
            raise ContractError("视觉机会池已失效: " + "、".join(pool_freshness["stale_fields"]))
    return payload


def visual_opportunity_pool_freshness(run_dir: Path) -> dict[str, Any]:
    """判断机会池是否仍绑定视觉政策、素材池和故事板。"""
    root = run_dir.resolve()
    payload = read_visual_opportunity_pool(root)
    current = policy_fingerprint(_repo_root_for_run(root), "visual")
    knowledge_check = payload.get("knowledge_check")
    knowledge_report = root / "figures/generated/learned-pattern-suggestions.json"
    knowledge_stale = (
        isinstance(knowledge_check, dict)
        and knowledge_check.get("report_sha256") is not None
        and (
            not knowledge_report.is_file()
            or sha256_file(knowledge_report) != knowledge_check.get("report_sha256")
        )
    )
    material_stale = payload.get("material_pool_digest") != material_pool_digest(root)
    storyboard_stale = payload.get("storyboard_digest") != _storyboard_digest(root)
    return {
        "current": payload.get("policy_fingerprint") == current
        and not knowledge_stale
        and not material_stale
        and not storyboard_stale,
        "stale_fields": [
            *([] if payload.get("policy_fingerprint") == current else ["policy_fingerprint"]),
            *(["knowledge_check"] if knowledge_stale else []),
            *(["material_pool_digest"] if material_stale else []),
            *(["storyboard_digest"] if storyboard_stale else []),
        ],
        "run_id": payload["run_id"],
    }
