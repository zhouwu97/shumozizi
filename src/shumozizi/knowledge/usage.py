"""验证论文卡知识在当前运行中的类型化采用与证据绑定。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.schema import require_valid
from shumozizi.simple.results import read_result_index

USAGE_REPORT_PATH = Path("paper/generated/knowledge_usage.json")
PAPER_CONTEXT_PATH = Path("paper/generated/knowledge_context.json")
VISUAL_SUGGESTIONS_PATH = Path("figures/generated/learned-pattern-suggestions.json")
_TYPED_LAYERS = {"analysis_route", "validation_design", "visual_design", "paper_structure"}
_EVIDENCE_STATUSES = {"validated", "revised", "rejected_by_evidence"}
_KNOWLEDGE_AS_EVIDENCE = re.compile(
    r"(?:论文卡|知识卡|获奖论文|knowledge/cards).{0,16}(?:证明|证据|支持当前|得出)",
    re.IGNORECASE,
)


def _retrieval(run_dir: Path) -> dict[str, Any] | None:
    """读取分析检索记录；缺失时由上层阶段门报告。"""
    path = run_dir / "knowledge/analysis-retrieval.json"
    if not path.is_file():
        return None
    return load_json(path)


def _model_units(run_dir: Path) -> dict[str, dict[str, Any]]:
    """按单元 ID 和问题 ID 返回建模单元，供知识绑定复验。"""
    path = run_dir / "analysis/MODELING_UNITS.json"
    if not path.is_file():
        return {}
    try:
        document = load_json(path)
    except (OSError, ValueError):
        return {}
    targets: dict[str, dict[str, Any]] = {}
    for unit in document.get("units", []):
        if isinstance(unit, dict):
            for key in ("unit_id", "question_id"):
                if isinstance(unit.get(key), str) and unit[key].strip():
                    targets.setdefault(unit[key], unit)
    return targets


def _model_targets(run_dir: Path) -> set[str]:
    """返回建模单元和问题 ID，供路线/验证知识绑定。"""
    return set(_model_units(run_dir))


def _figure_targets(run_dir: Path) -> set[str]:
    """返回当前图计划中的图 ID。"""
    path = run_dir / "figures/FIGURE_PLAN.json"
    if not path.is_file():
        return set()
    try:
        document = load_json(path)
    except (OSError, ValueError):
        return set()
    return {
        str(item["figure_id"])
        for item in document.get("figures", [])
        if isinstance(item, dict) and isinstance(item.get("figure_id"), str)
    }


def _visual_pattern_ids(retrieval: dict[str, Any]) -> set[str]:
    """返回检索结果中所有结构化视觉模式 ID。"""
    return {
        str(pattern["pattern_id"])
        for card in retrieval.get("matched_cards", [])
        if isinstance(card, dict)
        for pattern in card.get("visual_patterns", [])
        if isinstance(pattern, dict) and isinstance(pattern.get("pattern_id"), str)
    }


def _current_result_ids(run_dir: Path) -> set[str]:
    """读取当前 production 结果 ID；索引尚未生成时返回空集。"""
    try:
        return {
            str(item["result_id"])
            for item in read_result_index(run_dir)["results"]
            if isinstance(item, dict)
            and item.get("status") == "current"
            and item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError):
        return set()


def _paper_adopted_pattern_ids(run_dir: Path) -> set[str]:
    """从兼容写作交接中识别明确声明采用的模式。"""
    path = run_dir / "paper/KNOWLEDGE_APPLICATION.md"
    if not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return set()
    adopted: set[str] = set()
    for chunk in text.split("## ")[1:]:
        heading, _, body = chunk.partition("\n")
        pattern_id = heading.strip().strip("`")
        if "- 写作决定：采用" in body or "- 写作决定: 采用" in body:
            adopted.add(pattern_id)
    return adopted


def _typed_pattern_errors(
    run_dir: Path,
    item: dict[str, Any],
    *,
    model_targets: set[str],
    figure_targets: set[str],
    visual_pattern_ids: set[str],
    current_result_ids: set[str],
    stage: str,
) -> list[str]:
    """校验一个已采用模式的类型化应用合同。"""
    pattern_id = str(item.get("pattern_id", "<unknown>"))
    layer = item.get("application_layer")
    if layer not in _TYPED_LAYERS:
        return [f"知识模式 {pattern_id} 的 application_layer 无效"]
    errors: list[str] = []
    targets = item.get("target_ids")
    if not isinstance(targets, list) or not targets:
        errors.append(f"知识模式 {pattern_id} 缺少非空 target_ids")
    else:
        allowed = figure_targets if layer == "visual_design" else model_targets
        unknown = sorted(set(str(value) for value in targets) - allowed)
        should_check_targets = layer != "visual_design" or stage == "paper" or bool(figure_targets)
        if unknown and layer != "paper_structure" and should_check_targets:
            errors.append(f"知识模式 {pattern_id} 的 target_ids 不存在: {', '.join(unknown)}")
    for field in ("current_problem_basis", "adaptation", "expected_effect", "falsification_condition"):
        value = item.get(field)
        if not value or (isinstance(value, str) and len(value.strip()) < 8):
            errors.append(f"知识模式 {pattern_id} 缺少实质 {field}")
        fragments = value if isinstance(value, list) else [value]
        if any(
            isinstance(fragment, str) and _KNOWLEDGE_AS_EVIDENCE.search(fragment)
            for fragment in fragments
        ):
            errors.append(f"知识模式 {pattern_id} 把论文卡或知识卡当成当前题证据")
    status = item.get("status")
    if status not in {"planned", "validated", "revised", "rejected_by_evidence", "not_executed"}:
        errors.append(f"知识模式 {pattern_id} 的 status 无效")
    if status in _EVIDENCE_STATUSES:
        result_ids = item.get("evidence_result_ids")
        if not isinstance(result_ids, list) or not result_ids:
            errors.append(f"知识模式 {pattern_id} 的 {status} 缺少 evidence_result_ids")
        else:
            stale = sorted(set(str(value) for value in result_ids) - current_result_ids)
            if stale:
                errors.append(f"知识模式 {pattern_id} 绑定了非 current production 结果: {', '.join(stale)}")
        for field in ("observed_effect", "conclusion"):
            if not isinstance(item.get(field), str) or len(item[field].strip()) < 8:
                errors.append(f"知识模式 {pattern_id} 的 {status} 缺少 {field}")
    if layer == "visual_design":
        visual_ids = item.get("visual_pattern_ids")
        if not isinstance(visual_ids, list) or not visual_ids:
            errors.append(f"知识模式 {pattern_id} 的 visual_design 缺少 visual_pattern_ids")
        else:
            unknown_visual = sorted(set(str(value) for value in visual_ids) - visual_pattern_ids)
            if unknown_visual:
                errors.append(f"知识模式 {pattern_id} 引用了不存在的视觉模式: {', '.join(unknown_visual)}")
        figure_ids = item.get("figure_ids")
        if not isinstance(figure_ids, list) or not figure_ids:
            errors.append(f"知识模式 {pattern_id} 的 visual_design 缺少 figure_ids")
        elif isinstance(targets, list) and set(map(str, figure_ids)) != set(map(str, targets)):
            errors.append(f"知识模式 {pattern_id} 的 figure_ids 必须与 target_ids 一致")
    if layer == "validation_design":
        errors.extend(_validation_binding_errors(run_dir, item, pattern_id=pattern_id))
    if layer == "paper_structure":
        bindings = item.get("paper_bindings")
        if not isinstance(bindings, list) or not bindings:
            errors.append(f"知识模式 {pattern_id} 的 paper_structure 缺少 paper_bindings")
        else:
            anchors = {
                str(binding.get("blueprint_anchor"))
                for binding in bindings
                if isinstance(binding, dict) and binding.get("blueprint_anchor")
            }
            if isinstance(targets, list) and set(map(str, targets)) != anchors:
                errors.append(f"知识模式 {pattern_id} 的 target_ids 必须与蓝图锚点一致")
        if stage == "paper":
            errors.extend(_paper_binding_errors(run_dir, item, pattern_id=pattern_id))
    return errors


def _validation_binding_errors(
    run_dir: Path, item: dict[str, Any], *, pattern_id: str
) -> list[str]:
    """核对验证知识确实落到当前建模单元的验证合同。"""
    bindings = item.get("validation_bindings")
    if not isinstance(bindings, list) or not bindings:
        return [f"知识模式 {pattern_id} 的 validation_design 缺少 validation_bindings"]
    units = _model_units(run_dir)
    errors: list[str] = []
    binding_targets = {
        str(binding.get("target_id"))
        for binding in bindings
        if isinstance(binding, dict) and binding.get("target_id")
    }
    declared_targets = {
        str(target) for target in item.get("target_ids", []) if isinstance(target, str)
    }
    if binding_targets != declared_targets:
        errors.append(f"知识模式 {pattern_id} 的 target_ids 必须与验证绑定目标一致")
    for binding in bindings:
        if not isinstance(binding, dict):
            errors.append(f"知识模式 {pattern_id} 的 validation_bindings 含非对象项")
            continue
        target_id = str(binding.get("target_id", ""))
        unit = units.get(target_id)
        if unit is None:
            errors.append(f"知识模式 {pattern_id} 的验证目标不存在: {target_id}")
            continue
        kind = binding.get("validation_kind")
        validation = unit.get("validation", {})
        if kind in {"oracle", "sensitivity", "robustness"}:
            enabled = isinstance(validation, dict) and isinstance(validation.get(kind), dict) and validation[kind].get("required") is True
        elif kind == "natural_comparison":
            enabled = isinstance(unit.get("natural_comparison"), str) and bool(unit["natural_comparison"].strip())
        elif kind in {"data_split", "diagnostic"}:
            field = "split_or_validation" if kind == "data_split" else "diagnostic_plan"
            contract = unit.get("data_contract", {})
            enabled = isinstance(contract, dict) and isinstance(contract.get(field), str) and bool(contract[field].strip())
        else:
            contract = unit.get("simulation_contract", {})
            enabled = isinstance(contract, dict) and isinstance(contract.get(kind), str) and bool(contract[kind].strip())
        if not enabled:
            errors.append(
                f"知识模式 {pattern_id} 声明验证 {target_id}:{kind}，但 MODELING_UNITS 未启用对应合同"
            )
        for field in ("metric", "pass_criterion"):
            value = binding.get(field)
            if not isinstance(value, str) or len(value.strip()) < (3 if field == "metric" else 8):
                errors.append(f"知识模式 {pattern_id} 的验证绑定缺少实质 {field}")
    return errors


def _normalized(value: str) -> str:
    """压缩空白和常见标记，供蓝图与正文锚点匹配。"""
    return re.sub(r"[\s`*_#{}\\]+", "", value).casefold()


def _paper_binding_errors(
    run_dir: Path, item: dict[str, Any], *, pattern_id: str
) -> list[str]:
    """核对论文结构知识在蓝图和实际稿件中的双重落点。"""
    bindings = item.get("paper_bindings")
    if not isinstance(bindings, list) or not bindings:
        return [f"知识模式 {pattern_id} 的 paper_structure 缺少 paper_bindings"]
    blueprint_path = run_dir / "paper/PAPER_BLUEPRINT.md"
    try:
        blueprint = blueprint_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [f"知识模式 {pattern_id} 无法复验 PAPER_BLUEPRINT.md"]
    try:
        from shumozizi.knowledge.retrieval import _manuscript_source_closure

        source_closure = _manuscript_source_closure(run_dir)
    except ContractError as exc:
        return [f"知识模式 {pattern_id} 无法复验正文编译包含链: {exc}"]
    errors: list[str] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            errors.append(f"知识模式 {pattern_id} 的 paper_bindings 含非对象项")
            continue
        blueprint_anchor = str(binding.get("blueprint_anchor", ""))
        if not blueprint_anchor or _normalized(blueprint_anchor) not in _normalized(blueprint):
            errors.append(f"知识模式 {pattern_id} 的蓝图锚点不存在: {blueprint_anchor}")
        source_path = str(binding.get("source_path", ""))
        try:
            from shumozizi.core.io import resolve_inside

            source = resolve_inside(run_dir, source_path, must_exist=True)
            relative = source.relative_to(run_dir.resolve()).as_posix()
            if not relative.startswith("paper/") or source.suffix.casefold() not in {".tex", ".typ"}:
                raise ContractError("正文源码必须位于 paper/ 且为 tex/typ")
            if relative not in source_closure:
                raise ContractError("正文源码未进入 main.tex/main.typ 编译包含链")
            source_text = source.read_text(encoding="utf-8")
        except (ContractError, OSError, UnicodeError, ValueError) as exc:
            errors.append(f"知识模式 {pattern_id} 的正文源码无效 {source_path}: {exc}")
            continue
        realization_anchor = str(binding.get("realization_anchor", ""))
        if not realization_anchor or _normalized(realization_anchor) not in _normalized(source_text):
            errors.append(f"知识模式 {pattern_id} 的正文兑现锚点不存在: {realization_anchor}")
    return errors


def build_knowledge_usage_report(run_dir: Path, *, stage: str = "paper") -> dict[str, Any]:
    """生成当前运行的知识使用报告。

    Args:
        run_dir: 当前运行目录。
        stage: ``analysis`` 或 ``paper``，决定是否要求结果已兑现。

    Returns:
        已写入 ``paper/generated/knowledge_usage.json`` 的结构化报告。
    """
    retrieval = _retrieval(run_dir)
    if retrieval is None:
        report = {"schema_version": "1.0", "run_id": run_dir.name, "stage": stage, "status": "missing", "errors": [], "warnings": ["缺少 knowledge/analysis-retrieval.json"]}
        atomic_json(run_dir / USAGE_REPORT_PATH, report)
        return report
    model_targets = _model_targets(run_dir)
    figure_targets = _figure_targets(run_dir)
    visual_pattern_ids = _visual_pattern_ids(retrieval)
    current_result_ids = _current_result_ids(run_dir)
    paper_adopted_ids = _paper_adopted_pattern_ids(run_dir) if stage == "paper" else set()
    errors: list[str] = []
    warnings: list[str] = []
    adopted = retrieval.get("accepted_patterns", [])
    for item in adopted:
        if not isinstance(item, dict):
            errors.append("accepted_patterns 含非对象项")
            continue
        if "application_layer" in item:
            errors.extend(
                _typed_pattern_errors(
                    run_dir,
                    item,
                    model_targets=model_targets,
                    figure_targets=figure_targets,
                    visual_pattern_ids=visual_pattern_ids,
                    current_result_ids=current_result_ids,
                    stage=stage,
                )
            )
            if (
                stage == "paper"
                and item.get("pattern_id") in paper_adopted_ids
                and item.get("status") not in {"validated", "revised"}
            ):
                errors.append(
                    f"论文不能把知识模式 {item.get('pattern_id')} 以 {item.get('status')} 状态写成方法依据"
                )
            elif stage == "paper" and item.get("status") not in {"validated", "revised"}:
                warnings.append(
                    f"知识模式 {item.get('pattern_id')} 当前为 {item.get('status')}，已从过滤后的写作上下文排除"
                )
        else:
            warnings.append(f"知识模式 {item.get('pattern_id', '<unknown>')} 使用旧版未类型化采用记录")
    rejected_ids = {
        str(item.get("pattern_id"))
        for item in retrieval.get("rejected_patterns", [])
        if isinstance(item, dict) and item.get("pattern_id")
    }
    modeling_path = run_dir / "analysis/MODELING_UNITS.json"
    try:
        modeling_text = modeling_path.read_text(encoding="utf-8") if modeling_path.is_file() else ""
    except (OSError, UnicodeError):
        modeling_text = ""
    leaked_rejections = sorted(pattern_id for pattern_id in rejected_ids if pattern_id in modeling_text)
    if leaked_rejections:
        errors.append("分析阶段已拒绝知识模式仍出现在建模合同: " + ", ".join(leaked_rejections))
    report = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "stage": stage,
        "status": retrieval.get("status"),
        "adopted_pattern_ids": [str(item.get("pattern_id")) for item in adopted if isinstance(item, dict)],
        "rejected_pattern_ids": sorted(rejected_ids),
        "visual_pattern_ids": sorted(visual_pattern_ids),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }
    atomic_json(run_dir / USAGE_REPORT_PATH, report)
    return report


def knowledge_usage_errors(report: dict[str, Any]) -> list[str]:
    """返回知识使用报告的硬错误。"""
    return [str(item) for item in report.get("errors", []) if isinstance(item, str)]


def knowledge_usage_warnings(report: dict[str, Any]) -> list[str]:
    """返回知识使用报告的兼容性和质量警告。"""
    return [str(item) for item in report.get("warnings", []) if isinstance(item, str)]


def record_knowledge_usage_outcomes(
    run_dir: Path, outcomes: list[dict[str, Any]]
) -> Path:
    """用当前实验结果回填已采用知识的兑现状态。

    Args:
        run_dir: 当前运行目录。
        outcomes: 按 ``pattern_id`` 给出的状态、结果、观察和结论。

    Returns:
        原子更新后的 ``analysis-retrieval.json`` 路径。

    Raises:
        ContractError: 模式未知、状态倒退或证据字段不完整。
    """
    path = run_dir / "knowledge/analysis-retrieval.json"
    document = load_json(path)
    accepted = {
        str(item.get("pattern_id")): item
        for item in document.get("accepted_patterns", [])
        if isinstance(item, dict) and item.get("pattern_id")
    }
    seen: set[str] = set()
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise ContractError("知识使用 outcomes 只能包含对象")
        pattern_id = str(outcome.get("pattern_id", ""))
        if pattern_id not in accepted:
            raise ContractError(f"知识使用 outcome 引用了未知 adopted pattern: {pattern_id}")
        if pattern_id in seen:
            raise ContractError(f"知识使用 outcome 重复: {pattern_id}")
        seen.add(pattern_id)
        status = outcome.get("status")
        if status not in _EVIDENCE_STATUSES | {"not_executed"}:
            raise ContractError(f"知识模式 {pattern_id} 的 outcome status 无效")
        target = accepted[pattern_id]
        target["status"] = status
        for field in ("evidence_result_ids", "observed_effect", "conclusion"):
            target.pop(field, None)
            if field in outcome:
                target[field] = outcome[field]
        if status in _EVIDENCE_STATUSES:
            if not target.get("evidence_result_ids"):
                raise ContractError(f"知识模式 {pattern_id} 的 {status} 缺少 evidence_result_ids")
            for field in ("observed_effect", "conclusion"):
                if not isinstance(target.get(field), str) or len(target[field].strip()) < 8:
                    raise ContractError(f"知识模式 {pattern_id} 的 {status} 缺少 {field}")
    require_valid(document, "knowledge_retrieval")
    candidate_errors: list[str] = []
    model_targets = _model_targets(run_dir)
    figure_targets = _figure_targets(run_dir)
    visual_pattern_ids = _visual_pattern_ids(document)
    current_result_ids = _current_result_ids(run_dir)
    for item in accepted.values():
        if "application_layer" not in item:
            continue
        candidate_errors.extend(
            _typed_pattern_errors(
                run_dir,
                item,
                model_targets=model_targets,
                figure_targets=figure_targets,
                visual_pattern_ids=visual_pattern_ids,
                current_result_ids=current_result_ids,
                stage="analysis",
            )
        )
    if candidate_errors:
        raise ContractError(
            "知识使用 outcome 无法由当前运行证据支持: "
            + "；".join(sorted(set(candidate_errors)))
        )
    atomic_json(path, document)
    build_knowledge_usage_report(run_dir, stage="analysis")
    return path


def build_paper_knowledge_context(run_dir: Path) -> dict[str, Any]:
    """生成只含已兑现模式和当前题证据的写作上下文。"""
    report = build_knowledge_usage_report(run_dir, stage="paper")
    errors = knowledge_usage_errors(report)
    if errors:
        raise ContractError("论文知识上下文仍含未兑现模式: " + "；".join(errors))
    retrieval = _retrieval(run_dir) or {}
    patterns = []
    for item in retrieval.get("accepted_patterns", []):
        if not isinstance(item, dict) or item.get("status") not in {"validated", "revised"}:
            continue
        patterns.append(
            {
                "pattern_id": item["pattern_id"],
                "application_layer": item["application_layer"],
                "target_ids": list(item["target_ids"]),
                "adaptation": item["adaptation"],
                "current_problem_basis": list(item["current_problem_basis"]),
                "evidence_result_ids": list(item["evidence_result_ids"]),
                "observed_effect": item["observed_effect"],
                "allowed_claim": item["conclusion"],
                "cannot_claim": [
                    "知识卡本身证明当前题结论",
                    "来源论文的参数、公式、代码或数值可直接迁移",
                    item["falsification_condition"],
                ],
                "visual_pattern_ids": list(item.get("visual_pattern_ids", [])),
                "figure_ids": list(item.get("figure_ids", [])),
                "validation_bindings": list(item.get("validation_bindings", [])),
                "paper_bindings": list(item.get("paper_bindings", [])),
            }
        )
    context = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "evidence_priority": [
            "current_problem",
            "current_data",
            "current_production_results",
            "independent_validation",
            "knowledge_patterns",
        ],
        "patterns": patterns,
        "forbidden_transfer": list(retrieval.get("forbidden_transfer", [])),
    }
    atomic_json(run_dir / PAPER_CONTEXT_PATH, context)
    return context


def build_visual_pattern_suggestions(run_dir: Path) -> dict[str, Any]:
    """按当前题视觉义务与真实输出合同推荐候选或已采用视觉模式。

    推荐报告不修改 ``FIGURE_PLAN``，也不要求作者必须采用任何模式。只有
    ``required_data_fields`` 已由当前建模单元的 ``visual_outputs`` 预留时，
    模式才会标为 eligible；候选模式仍须显式采用后才能进入图计划，从而避免
    为了模仿来源论文补造不存在的数据结构。

    Args:
        run_dir: 当前 Competition-First 运行目录。

    Returns:
        已原子写入 ``figures/generated/learned-pattern-suggestions.json`` 的报告。
    """
    retrieval = _retrieval(run_dir)
    if retrieval is None:
        report = {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "status": "unavailable",
            "recommendations": [],
            "rejections": [],
            "reason": "缺少 knowledge/analysis-retrieval.json",
        }
        atomic_json(run_dir / VISUAL_SUGGESTIONS_PATH, report)
        return report

    patterns = {
        str(pattern["pattern_id"]): pattern
        for card in retrieval.get("matched_cards", [])
        if isinstance(card, dict)
        for pattern in card.get("visual_patterns", [])
        if isinstance(pattern, dict) and isinstance(pattern.get("pattern_id"), str)
    }
    adopted_visual_ids = {
        str(visual_id)
        for item in retrieval.get("accepted_patterns", [])
        if isinstance(item, dict) and item.get("application_layer") == "visual_design"
        for visual_id in item.get("visual_pattern_ids", [])
        if isinstance(visual_id, str)
    }
    modeling_path = run_dir / "analysis/MODELING_UNITS.json"
    try:
        modeling = load_json(modeling_path)
    except (OSError, ValueError):
        modeling = {"units": []}

    from shumozizi.paper.readiness import derive_required_visual_obligations

    recommendations: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for unit in modeling.get("units", []):
        if not isinstance(unit, dict) or not isinstance(unit.get("question_id"), str):
            continue
        question_id = unit["question_id"]
        obligations = derive_required_visual_obligations(unit)
        outputs = [item for item in unit.get("visual_outputs", []) if isinstance(item, dict)]
        available_fields = {
            str(field)
            for output in outputs
            for field in output.get("required_data", [])
            if isinstance(field, str)
        }
        argument_unit_ids = [
            str(output["argument_unit_id"])
            for output in outputs
            if isinstance(output.get("argument_unit_id"), str)
        ]
        source_files = [
            str(output["output_path"])
            for output in outputs
            if isinstance(output.get("output_path"), str)
        ]
        for visual_id in sorted(patterns):
            pattern = patterns.get(visual_id)
            if pattern is None:
                continue
            roles = {str(value) for value in pattern.get("argument_roles", [])}
            comparable = set(obligations)
            if "mechanism" in comparable:
                comparable.update({"comparison", "decision"})
            matched = sorted(roles & comparable)
            missing_data = sorted(
                set(map(str, pattern.get("required_data_fields", []))) - available_fields
            )
            record = {
                "question_id": question_id,
                "unit_id": str(unit.get("unit_id", question_id)),
                "learned_pattern_id": visual_id,
                "adoption_status": (
                    "adopted" if visual_id in adopted_visual_ids else "candidate"
                ),
                "recommended_archetype": pattern.get("visual_archetype"),
                "matched_obligations": matched,
                "argument_unit_ids": argument_unit_ids,
                "source_files": source_files,
                "required_data_fields": list(pattern.get("required_data_fields", [])),
                "missing_data_fields": missing_data,
                "forbidden_transfer": [
                    "source_data",
                    "source_labels",
                    "source_numeric_values",
                    "source_code",
                    "source_caption",
                ],
            }
            if matched and not missing_data:
                record["score"] = round(len(matched) / max(len(roles), 1), 4)
                recommendations.append(record)
            else:
                record["reason"] = (
                    "当前视觉义务不匹配"
                    if not matched
                    else "当前 visual_outputs 未提供模式所需结构数据"
                )
                rejections.append(record)
    recommendations.sort(
        key=lambda item: (-float(item["score"]), item["question_id"], item["learned_pattern_id"])
    )
    report = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "status": "ready",
        "recommendations": recommendations,
        "rejections": rejections,
        "selection_policy": (
            "advisory_only_candidates_require_explicit_adoption_before_figure_plan"
        ),
        "evidence_priority": [
            "current_problem",
            "current_visual_outputs",
            "current_production_results",
            "learned_visual_pattern",
        ],
    }
    atomic_json(run_dir / VISUAL_SUGGESTIONS_PATH, report)
    return report
