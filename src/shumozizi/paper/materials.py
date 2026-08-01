"""把正式结果整理为可供作者使用的研究素材池。

素材池只保存结论、推导、机制、边界和图示机会等“作者输入”，不把日志、任务
回执、源码哈希和调试路径暴露给写作模板；来源绑定仍保留在结构化字段中用于
失效判断和审计。
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.policy import (
    formal_result_digest,
    policy_fingerprint,
    source_digest,
)
from shumozizi.simple.state import read_simple_state, utc_now

MATERIAL_POOL_MD_PATH = Path("paper/PAPER_MATERIAL_POOL.md")
MATERIAL_POOL_JSON_PATH = Path("paper/generated/material_pool.json")
MATERIAL_CATEGORIES = (
    "Direct Answer",
    "Mathematical Derivation",
    "Structural Observation",
    "Mechanism",
    "Intermediate Result",
    "Baseline/Contrast",
    "Boundary/Robustness",
    "Illustrative Case",
    "Visual Opportunity",
    "Negative Finding",
)
_PLACEHOLDER_MARKERS = ("待填写", "待补", "todo", "tbd", "placeholder")
_CONTROL_KEYS = frozenset(
    {
        "command",
        "commands",
        "stdout",
        "stderr",
        "stdout_path",
        "stderr_path",
        "log",
        "logs",
        "hash",
        "sha",
        "sha256",
        "input_hashes",
        "output_hashes",
        "source_hashes",
        "created_at",
        "started_at",
        "finished_at",
        "duration_seconds",
        "exit_code",
        "status",
        "run_id",
    }
)
_ANALYSIS_INPUTS = (
    "analysis/MODELING_UNITS.json",
    "analysis/method_facts.json",
    "analysis/critical_claims.json",
    "analysis/evidence_consequences.json",
    "review/stronger-alternative.json",
    "review/SCIENTIFIC_CHALLENGE.md",
    "actual/refinement/first-feasible-checkpoint.json",
    "actual/refinement/findings.json",
)


def _text(value: Any) -> str:
    """把结果字段安全地转成一条作者可读的短文本。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "；".join(item for item in (_text(part) for part in value) if item)
    if isinstance(value, dict):
        return "；".join(
            f"{key}：{_text(item)}" for key, item in value.items() if _text(item)
        )
    return ""


def _author_text(value: Any, *, key: str = "", depth: int = 0) -> str:
    """只把科学解释字段压成作者可读文本，过滤控制面日志和哈希。

    WHY: 自动素材池的输入可以很宽，但写作上下文不能被命令、回执和哈希
    污染。这里采用字段名黑名单，而不是把未知 JSON 原样倾倒给作者。
    """
    if depth > 3 or key.casefold() in _CONTROL_KEYS:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_author_text(item, depth=depth + 1) for item in value]
        return "；".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = []
        for child_key, child_value in value.items():
            rendered = _author_text(child_value, key=str(child_key), depth=depth + 1)
            if rendered:
                parts.append(f"{child_key}：{rendered}")
        return "；".join(parts)
    return ""


def _selected_text(record: dict[str, Any], fields: Iterable[str]) -> str:
    """按白名单提取模型/验证语义，避免把结构化控制字段写入正文输入。"""
    parts = []
    for field in fields:
        value = _author_text(record.get(field), key=field)
        if value:
            parts.append(f"{field}：{value}")
    return "；".join(parts)


def _analysis_inputs_digest(run_dir: Path) -> str:
    """计算自动素材池所读取的科学分析输入摘要。"""
    root = run_dir.resolve()
    digest = hashlib.sha256()
    for relative in _ANALYSIS_INPUTS:
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(bytes.fromhex(sha256_file(path)))
        else:
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest()


def _load_optional_json(run_dir: Path, relative: str) -> dict[str, Any] | None:
    """读取可选分析文件；坏的可选文件不应伪造素材。"""
    path = run_dir / relative
    if not path.is_file():
        return None
    try:
        payload = load_json(path)
    except (ContractError, OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_text(path: Path, value: str) -> None:
    """在同目录原子替换作者可读文本，避免半写入文件被编辑器读取。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _base_item(
    *,
    material_id: str,
    category: str,
    title: str,
    content: str,
    question_id: str | None,
    result_ids: Iterable[str] = (),
    figure_ids: Iterable[str] = (),
    inclusion: str = "candidate",
    evidence_grade: str | None = None,
    media_candidates: Iterable[str] = (),
    source_paths: Iterable[str] = (),
    figure_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造单个素材条目并统一默认字段。"""
    if category not in MATERIAL_CATEGORIES:
        raise ContractError(f"未知素材类别: {category}")
    if not title.strip() or not content.strip():
        raise ContractError("素材标题和内容不能为空")
    if inclusion not in {"body", "appendix", "candidate"}:
        raise ContractError("素材 inclusion 必须为 body、appendix 或 candidate")
    item = {
        "material_id": material_id,
        "category": category,
        "title": title.strip(),
        "content": content.strip(),
        "question_id": question_id,
        "source_result_ids": sorted({str(item) for item in result_ids}),
        "source_figure_ids": sorted({str(item) for item in figure_ids}),
        "source_paths": sorted({str(item) for item in source_paths}),
        "inclusion": inclusion,
        "evidence_grade": evidence_grade,
        "media_candidates": sorted({str(item) for item in media_candidates}),
        "status": "current",
    }
    if source_paths:
        item["source_paths"] = sorted({str(item) for item in source_paths})
    if figure_bindings:
        item["source_figure_bindings"] = figure_bindings
    return item


def _current_results(run_dir: Path) -> list[dict[str, Any]]:
    """只读取当前且执行有效的生产结果，拒绝旧结果污染素材池。"""
    path = run_dir / "results/index.json"
    if not path.is_file():
        return []
    payload = load_json(path)
    return [
        item
        for item in payload.get("results", [])
        if isinstance(item, dict)
        and item.get("status") == "current"
        and item.get("execution_valid") is True
        and item.get("execution_mode", "production") == "production"
    ]


def _result_materials(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从结果显式字段提取作者素材；不把未知结构猜成科学结论。"""
    rid = str(result.get("result_id", ""))
    question_id = result.get("question_id")
    question = str(question_id) if isinstance(question_id, str) else None
    materials: list[dict[str, Any]] = []
    metrics = _text(result.get("metrics"))
    if metrics:
        # 指标是正式结果中的真实中间证据，但它没有自动携带题意解释，
        # 因此只进入 Intermediate Result，不冒充 Direct Answer 或 Mechanism。
        materials.append(
            _base_item(
                material_id=f"intermediate-{rid}",
                category="Intermediate Result",
                title=f"{question or '共享'}正式结果指标",
                content=metrics,
                question_id=question,
                result_ids=[rid],
                inclusion="candidate",
                evidence_grade="formal_result",
            )
        )
    conclusion = _text(result.get("conclusion") or result.get("answer"))
    if conclusion:
        materials.append(
            _base_item(
                material_id=f"answer-{rid}",
                category="Direct Answer",
                title=f"{question or '共享'}直接答案",
                content=conclusion,
                question_id=question,
                result_ids=[rid],
                inclusion="body",
                evidence_grade=_text(result.get("evidence_grade")) or None,
            )
        )
    for index, field in enumerate(("derivation", "key_derivation", "formula_explanation"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"derivation-{rid}-{index}",
                    category="Mathematical Derivation",
                    title=f"{question or '共享'}关键推导",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
            break
    for index, field in enumerate(("structural_observation", "insight", "insights"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"structure-{rid}-{index}",
                    category="Structural Observation",
                    title=f"{question or '共享'}结构观察",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    for index, field in enumerate(("mechanism", "mechanism_explanation", "tradeoff"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"mechanism-{rid}-{index}",
                    category="Mechanism",
                    title=f"{question or '共享'}机制解释",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    for index, field in enumerate(("baseline", "contrast", "comparison"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"contrast-{rid}-{index}",
                    category="Baseline/Contrast",
                    title=f"{question or '共享'}基线对照",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    for index, field in enumerate(("boundary", "robustness", "sensitivity", "limitations"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"boundary-{rid}-{index}",
                    category="Boundary/Robustness",
                    title=f"{question or '共享'}适用边界",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    for index, field in enumerate(
        ("counterexample", "validated_counterexample", "negative_finding", "refinement_finding"),
        1,
    ):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"negative-{rid}-{index}",
                    category="Negative Finding",
                    title=f"{question or '共享'}反例或负面发现",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                    evidence_grade="validated_negative_finding",
                )
            )
    for index, field in enumerate(("illustrative_case", "critical_case", "representative_case"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"case-{rid}-{index}",
                    category="Illustrative Case",
                    title=f"{question or '共享'}典型案例",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                    evidence_grade="formal_result_case",
                )
            )
    return materials


def _analysis_materials(run_dir: Path) -> list[dict[str, Any]]:
    """把分析层的科学合同转成可写素材，不复制控制台账。"""
    materials: list[dict[str, Any]] = []
    modeling = _load_optional_json(run_dir, "analysis/MODELING_UNITS.json") or {}
    units = modeling.get("units", [])
    if isinstance(units, list):
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                continue
            question_id = unit.get("question_id") if isinstance(unit.get("question_id"), str) else None
            unit_id = str(unit.get("unit_id") or question_id or f"unit-{index + 1}")
            derivation = _selected_text(
                unit,
                (
                    "mathematical_object",
                    "decision_variables",
                    "success_event",
                    "objective",
                    "endpoint",
                    "estimand",
                    "modeling_basis",
                    "constraints",
                    "aggregation",
                    "question_delta",
                ),
            )
            if derivation:
                materials.append(
                    _base_item(
                        material_id=f"model-contract-{unit_id}",
                        category="Mathematical Derivation",
                        title=f"{question_id or '共享'}数学对象与判据",
                        content=derivation,
                        question_id=question_id,
                        inclusion="body",
                        evidence_grade="model_contract",
                        source_paths=["analysis/MODELING_UNITS.json"],
                    )
                )
            delta = _selected_text(unit, ("question_delta", "inherits_from", "added_resources", "changed_constraints"))
            if delta:
                materials.append(
                    _base_item(
                        material_id=f"question-delta-{unit_id}",
                        category="Structural Observation",
                        title=f"{question_id or '共享'}问题继承与新增困难",
                        content=delta,
                        question_id=question_id,
                        inclusion="body",
                        evidence_grade="question_contract",
                        source_paths=["analysis/MODELING_UNITS.json"],
                    )
                )
            boundary = _selected_text(
                unit,
                ("validation", "robustness", "sensitivity", "boundary", "limitations"),
            )
            if boundary:
                materials.append(
                    _base_item(
                        material_id=f"validation-contract-{unit_id}",
                        category="Boundary/Robustness",
                        title=f"{question_id or '共享'}验证与适用边界",
                        content=boundary,
                        question_id=question_id,
                        inclusion="body",
                        evidence_grade="validation_contract",
                        source_paths=["analysis/MODELING_UNITS.json"],
                    )
                )
            visual_outputs = unit.get("visual_outputs")
            if isinstance(visual_outputs, list):
                for visual_index, visual in enumerate(visual_outputs, 1):
                    if not isinstance(visual, dict):
                        continue
                    visual_text = _selected_text(
                        visual,
                        (
                            "argument_unit_id",
                            "visual_question",
                            "takeaway",
                            "required_data",
                            "required_data_fields",
                            "visual_archetype",
                            "information_structure",
                        ),
                    )
                    if visual_text:
                        candidates = []
                        for key in ("visual_archetype", "archetype", "template_id"):
                            if isinstance(visual.get(key), str) and visual[key].strip():
                                candidates.append(visual[key].strip())
                        materials.append(
                            _base_item(
                                material_id=f"visual-contract-{unit_id}-{visual_index}",
                                category="Visual Opportunity",
                                title=f"{question_id or '共享'}结构可视化机会",
                                content=visual_text,
                                question_id=question_id,
                                inclusion="candidate",
                                evidence_grade="visual_contract",
                                media_candidates=candidates,
                                source_paths=["analysis/MODELING_UNITS.json"],
                            )
                        )

    claims = _load_optional_json(run_dir, "analysis/critical_claims.json") or {}
    raw_claims = claims.get("claims", [])
    if isinstance(raw_claims, list):
        category_by_type = {
            "objective_semantics": "Direct Answer",
            "result_correctness": "Direct Answer",
            "global_optimality": "Baseline/Contrast",
            "comparative_superiority": "Baseline/Contrast",
            "mechanism_explanation": "Mechanism",
            "robustness": "Boundary/Robustness",
            "parameter_insensitivity": "Boundary/Robustness",
            "generalization": "Boundary/Robustness",
        }
        for claim in raw_claims:
            if not isinstance(claim, dict):
                continue
            statement = _author_text(claim.get("statement"), key="statement")
            if not statement:
                continue
            claim_type = str(claim.get("claim_type", "other"))
            category = category_by_type.get(claim_type, "Structural Observation")
            question_id = claim.get("question_id") if isinstance(claim.get("question_id"), str) else None
            materials.append(
                _base_item(
                    material_id=f"claim-{claim.get('claim_id', len(materials) + 1)}",
                    category=category,
                    title=f"{question_id or '共享'}关键主张",
                    content=statement
                    + (f"；所需证据：{_author_text(claim.get('evidence_needed'), key='evidence_needed')}" if claim.get("evidence_needed") else ""),
                    question_id=question_id,
                    result_ids=claim.get("result_ids", []),
                    inclusion="body" if claim.get("importance") == "primary" else "candidate",
                    evidence_grade="critical_claim",
                    source_paths=["analysis/critical_claims.json"],
                )
            )

    method_facts = _load_optional_json(run_dir, "analysis/method_facts.json") or {}
    method_text = _selected_text(
        method_facts,
        ("primary_model", "baseline", "challenger", "optimizer", "independent_oracle", "validation", "method"),
    )
    if method_text:
        materials.append(
            _base_item(
                material_id="method-facts",
                category="Mathematical Derivation",
                title="主模型、基线与独立验证路线",
                content=method_text,
                question_id=None,
                inclusion="body",
                evidence_grade="method_fact",
                source_paths=["analysis/method_facts.json"],
            )
        )

    stronger = _load_optional_json(run_dir, "review/stronger-alternative.json") or {}
    stronger_text = _selected_text(stronger, ("found", "alternative", "reason", "decision", "result_ids"))
    if stronger_text:
        materials.append(
            _base_item(
                material_id="stronger-alternative",
                category="Negative Finding" if stronger.get("found") is True else "Baseline/Contrast",
                title="独立科学挑战与更强替代路线",
                content=stronger_text,
                question_id=None,
                inclusion="body",
                evidence_grade="scientific_challenge",
                source_paths=["review/stronger-alternative.json"],
            )
        )

    challenge_path = run_dir / "review/SCIENTIFIC_CHALLENGE.md"
    if challenge_path.is_file():
        challenge = challenge_path.read_text(encoding="utf-8", errors="replace").strip()
        if challenge:
            materials.append(
                _base_item(
                    material_id="scientific-challenge-findings",
                    category="Negative Finding",
                    title="科学挑战中的风险、反例与边界",
                    content=challenge[:6000],
                    question_id=None,
                    inclusion="appendix",
                    evidence_grade="scientific_challenge",
                    source_paths=["review/SCIENTIFIC_CHALLENGE.md"],
                )
            )

    for relative in ("actual/refinement/first-feasible-checkpoint.json", "actual/refinement/findings.json"):
        payload = _load_optional_json(run_dir, relative)
        if not payload:
            continue
        finding = _selected_text(payload, ("conclusion", "finding", "decision", "followup", "boundary", "mechanism"))
        if finding:
            materials.append(
                _base_item(
                    material_id=f"refinement-{Path(relative).stem}",
                    category="Mechanism",
                    title="搜索深化与首个可行解后的研究发现",
                    content=finding,
                    question_id=None,
                    inclusion="body",
                    evidence_grade="refinement_finding",
                    source_paths=[relative],
                )
            )
    return materials


def _current_figure_materials(run_dir: Path) -> list[dict[str, Any]]:
    """把当前真实图作为局部视觉素材，并只绑定其自身输出哈希。"""
    payload = _load_optional_json(run_dir, "figures/index.json") or {}
    materials: list[dict[str, Any]] = []
    for figure in payload.get("figures", []):
        if not isinstance(figure, dict) or figure.get("status") != "current":
            continue
        figure_id = str(figure.get("figure_id", ""))
        if not figure_id or figure.get("paper_allowed") is False:
            continue
        outputs = figure.get("outputs", [])
        source_paths: list[str] = []
        output_bindings: list[dict[str, str]] = []
        for output in outputs if isinstance(outputs, list) else []:
            if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                continue
            relative = output["path"]
            path = run_dir / relative
            if not path.is_file():
                continue
            source_paths.append(relative)
            output_bindings.append({"path": relative, "sha256": sha256_file(path)})
        if not output_bindings:
            continue
        question_id = figure.get("question_id") if isinstance(figure.get("question_id"), str) else None
        takeaway = _text(figure.get("takeaway") or figure.get("expected_takeaway"))
        question = _text(figure.get("question") or figure.get("scientific_question"))
        limitations = _text(figure.get("limitations") or figure.get("cannot_prove"))
        content_parts = [part for part in (question, takeaway, f"边界：{limitations}" if limitations else "") if part]
        if not content_parts:
            content_parts = [f"当前图 {figure_id} 的真实输出已由图索引登记。"]
        item = _base_item(
            material_id=f"figure-{figure_id}",
            category="Visual Opportunity",
            title=f"{question_id or '共享'}当前视觉证据：{figure_id}",
            content="；".join(content_parts),
            question_id=question_id,
            figure_ids=[figure_id],
            inclusion="appendix" if figure.get("placement") == "appendix" else "body",
            evidence_grade="current_figure",
            media_candidates=[str(figure.get("template_id"))] if figure.get("template_id") else [],
            source_paths=source_paths,
            figure_bindings={figure_id: {"outputs": output_bindings}},
        )
        materials.append(item)
    return materials


def build_material_pool(
    run_dir: Path,
    *,
    materials: list[dict[str, Any]] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """构建研究素材池，并可同步生成作者可读 Markdown。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    items = materials if materials is not None else [
        item for result in _current_results(root) for item in _result_materials(result)
    ]
    if materials is None:
        # 论文层需要的是经过筛选的科学素材，而不是把一份结果索引当作正文。
        # 因此自动路径还会接收分析合同和已生成的真实图，但不读取日志/命令。
        items.extend(_analysis_materials(root))
        items.extend(_current_figure_materials(root))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ContractError("素材条目必须是对象")
        item = _base_item(
            material_id=str(raw.get("material_id", "")),
            category=str(raw.get("category", "")),
            title=str(raw.get("title", "")),
            content=str(raw.get("content", "")),
            question_id=raw.get("question_id") if isinstance(raw.get("question_id"), str) else None,
            result_ids=raw.get("source_result_ids", []),
            figure_ids=raw.get("source_figure_ids", []),
            inclusion=str(raw.get("inclusion", "candidate")),
            evidence_grade=raw.get("evidence_grade") if isinstance(raw.get("evidence_grade"), str) else None,
            media_candidates=raw.get("media_candidates", []),
        )
        for field in (
            "source_paths",
            "source_figure_bindings",
            "editor_note",
            "claim_function",
            "status",
        ):
            if field in raw:
                item[field] = raw[field]
        if item["material_id"] in seen:
            raise ContractError(f"素材 ID 重复: {item['material_id']}")
        seen.add(item["material_id"])
        normalized.append(item)
    payload: dict[str, Any] = {
        "schema_name": "paper_material_pool",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "policy_fingerprint": policy_fingerprint(resolve_repo_root(Path(__file__)), "paper"),
        "generated_at": utc_now(),
        "status": "current" if materials is not None or normalized else "draft",
        "source_bindings": {
            "production_results_digest": formal_result_digest(root),
            "modeling_units_digest": source_digest(root, "analysis/MODELING_UNITS.json"),
            "analysis_inputs_digest": _analysis_inputs_digest(root),
        },
        "items": normalized,
    }
    require_valid(payload, "paper_material_pool")
    if write:
        write_material_pool(root, payload)
    return payload


def _markdown(payload: dict[str, Any]) -> str:
    """渲染去除控制字段的作者素材文档。"""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload.get("items", []):
        groups[str(item.get("category"))].append(item)
    lines = [
        "# PAPER_MATERIAL_POOL",
        "",
        "这是论文作者的研究素材池。它保留结论、推导、结构观察、机制、边界和视觉机会；"
        "运行日志、任务回执、源码哈希与调试路径不属于写作输入。",
        "",
        f"素材状态：`{payload.get('status', 'draft')}`。素材变化后应重新生成故事板与相关图表。",
        "",
    ]
    for category in MATERIAL_CATEGORIES:
        lines.extend([f"## {category}", ""])
        entries = groups.get(category, [])
        if not entries:
            lines.extend(["暂无可用素材。", ""])
            continue
        for item in entries:
            question = item.get("question_id") or "共享"
            lines.extend(
                [
                    f"### {item['title']}（{question}）",
                    "",
                    item["content"],
                    "",
                    f"- 写作位置建议：`{item.get('inclusion', 'candidate')}`",
                ]
            )
            if item.get("claim_function"):
                lines.append(f"- 证据功能：{item['claim_function']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_material_pool(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """校验并原子写入素材池 JSON 与 Markdown。"""
    root = run_dir.resolve()
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        raise ContractError("素材池 run_id 与运行不一致")
    require_valid(payload, "paper_material_pool")
    atomic_json(root / MATERIAL_POOL_JSON_PATH, payload)
    target = root / MATERIAL_POOL_MD_PATH
    _atomic_text(target, _markdown(payload))
    return payload


def read_material_pool(run_dir: Path) -> dict[str, Any]:
    """读取并验证素材池。"""
    payload = load_json(run_dir.resolve() / MATERIAL_POOL_JSON_PATH)
    require_valid(payload, "paper_material_pool")
    return payload


def material_pool_digest(run_dir: Path) -> str | None:
    """返回素材池 JSON 摘要，缺失时返回空值。"""
    path = run_dir.resolve() / MATERIAL_POOL_JSON_PATH
    return sha256_file(path) if path.is_file() else None


def validate_material_pool_freshness(run_dir: Path) -> dict[str, Any]:
    """判断素材池是否仍绑定科学输入和其局部视觉来源。"""
    root = run_dir.resolve()
    payload = read_material_pool(root)
    repo_root = resolve_repo_root(Path(__file__))
    current = {
        "production_results_digest": formal_result_digest(root),
        "modeling_units_digest": source_digest(root, "analysis/MODELING_UNITS.json"),
        "analysis_inputs_digest": _analysis_inputs_digest(root),
        "policy_fingerprint": policy_fingerprint(repo_root, "paper"),
    }
    stored = {**payload.get("source_bindings", {}), "policy_fingerprint": payload.get("policy_fingerprint")}
    stale_fields = [key for key, value in current.items() if stored.get(key) != value]
    figure_index: dict[str, Any] = {}
    index_payload = _load_optional_json(root, "figures/index.json") or {}
    for figure in index_payload.get("figures", []):
        if isinstance(figure, dict) and figure.get("status") == "current":
            figure_index[str(figure.get("figure_id", ""))] = figure
    for item in payload.get("items", []):
        bindings = item.get("source_figure_bindings")
        if not isinstance(bindings, dict):
            continue
        for figure_id, binding in bindings.items():
            current_figure = figure_index.get(str(figure_id))
            expected_outputs = binding.get("outputs", []) if isinstance(binding, dict) else []
            current_outputs = current_figure.get("outputs", []) if isinstance(current_figure, dict) else []
            expected_map = {
                str(output.get("path")): output.get("sha256")
                for output in expected_outputs
                if isinstance(output, dict)
            }
            current_map = {}
            for output in current_outputs if isinstance(current_outputs, list) else []:
                if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                    continue
                path = root / output["path"]
                if path.is_file():
                    current_map[output["path"]] = sha256_file(path)
            if expected_map != current_map:
                stale_fields.append(f"figure:{item.get('material_id', figure_id)}")
    return {"current": not stale_fields, "stale_fields": stale_fields, "run_id": payload["run_id"]}


def material_pool_quality_report(run_dir: Path) -> dict[str, Any]:
    """检查素材池是否足以支撑长篇科学首稿，而不把条目数当成篇幅证明。"""
    root = run_dir.resolve()
    payload = read_material_pool(root)
    items = [item for item in payload.get("items", []) if item.get("status", "current") == "current"]
    errors: list[str] = []
    if payload.get("status") != "current":
        errors.append("status 不是 current")
    if not items:
        errors.append("没有当前作者素材")
    placeholder_ids = [
        str(item.get("material_id"))
        for item in items
        if any(marker in str(item.get("content", "")).casefold() for marker in _PLACEHOLDER_MARKERS)
        or any(marker in str(item.get("title", "")).casefold() for marker in _PLACEHOLDER_MARKERS)
    ]
    if placeholder_ids:
        errors.append("存在占位素材: " + ", ".join(placeholder_ids))
    counts = {
        category: sum(1 for item in items if item.get("category") == category)
        for category in MATERIAL_CATEGORIES
    }
    required_questions = [str(item) for item in read_simple_state(root).get("required_questions", [])]
    question_coverage: dict[str, dict[str, bool]] = {}
    for question_id in required_questions:
        question_items = [item for item in items if item.get("question_id") in {question_id, None}]
        coverage = {
            "direct_answer": any(item.get("category") == "Direct Answer" for item in question_items),
            "derivation": any(item.get("category") == "Mathematical Derivation" for item in question_items),
            "mechanism": any(item.get("category") == "Mechanism" for item in question_items),
            "boundary": any(item.get("category") == "Boundary/Robustness" for item in question_items),
        }
        question_coverage[question_id] = coverage
        for role, present in coverage.items():
            if not present:
                errors.append(f"{question_id} 缺少 {role} 素材")
    return {
        "substantive": not errors,
        "errors": errors,
        "item_count": len(items),
        "category_counts": counts,
        "question_coverage": question_coverage,
        "placeholder_material_ids": placeholder_ids,
        "run_id": payload["run_id"],
    }


def require_material_pool(
    run_dir: Path, *, fresh: bool = True, substantive: bool = False
) -> dict[str, Any]:
    """要求素材池存在并可选地执行长篇论文实质内容门。"""
    payload = read_material_pool(run_dir)
    if fresh:
        freshness = validate_material_pool_freshness(run_dir)
        if not freshness["current"]:
            raise ContractError("研究素材池已失效: " + "、".join(freshness["stale_fields"]))
    if substantive:
        quality = material_pool_quality_report(run_dir)
        if not quality["substantive"]:
            raise ContractError(
                "研究素材池不具备长篇写作所需的实质内容: "
                + "；".join(quality["errors"])
            )
    return payload
