"""管理 v3 的冻结审查包与独立审查放行边界。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    json_bytes,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import validate_document
from shumozizi.profiles.delivery import delivery_requirements_for_competition
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.objective_semantics import build_question_objective_bindings
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import (
    is_competition_first_state,
    is_competition_first_v32_state,
    read_simple_state,
    update_simple_state,
    utc_now,
)

REVIEW_ROOT = Path("review")
SUMMARY_PATH = REVIEW_ROOT / "summary.json"
OBJECTIVE_SEMANTICS_REPORT_PATH = REVIEW_ROOT / "OBJECTIVE_SEMANTICS_REVIEW.md"
OBJECTIVE_SEMANTICS_ASSESSMENT_PATH = REVIEW_ROOT / "OBJECTIVE_SEMANTICS.json"
OBJECTIVE_SEMANTICS_RECEIPT_PATH = REVIEW_ROOT / "objective-semantics.json"
AMBIGUITY_DECISIONS_PATH = Path("state/ambiguity-decisions.json")
SCIENTIFIC_REPORT_PATH = REVIEW_ROOT / "SCIENTIFIC_RED_TEAM.md"
SCIENTIFIC_CHALLENGE_REPORT_PATH = REVIEW_ROOT / "SCIENTIFIC_CHALLENGE.md"
PAPER_BLIND_REPORT_PATH = REVIEW_ROOT / "PAPER_BLIND_REVIEW.md"
# v3.2 不写 v3.1 的 review/summary.json（科学挑战不经 import_scientific_review），
# 因此盲评结论需要独立记录文件，否则 v3.2 永远无法完成 PDF 盲评。
V32_PAPER_BLIND_RECORD_PATH = REVIEW_ROOT / "paper-blind-review.json"
MANUAL_INTERVENTION_PROMPT = (
    "数学建模国赛的标准去严格审核，看看和国赛的优秀论文差在哪里，需要补什么图，"
    "这个算报告还是论文，要怎么润色，不要只是看思路建模，还要看笔法文风，排版，"
    "论证思路等等，为什么这个只有十几页，还需要怎么改进"
)
MANUAL_INTERVENTION_DIMENSIONS = (
    "cummcm_excellence_gap",
    "figure_gaps",
    "report_or_paper_verdict",
    "prose_and_academic_style",
    "layout_and_typography",
    "argument_structure",
    "page_depth_diagnosis",
    "revision_priorities",
)
MANUAL_INTERVENTION_RECORD = {
    "source": "user_fixed_prompt",
    "prompt": MANUAL_INTERVENTION_PROMPT,
    "input_scope": "frozen_pdf_only",
    "dimensions": list(MANUAL_INTERVENTION_DIMENSIONS),
}
LEGACY_PAPER_BLIND_PROMPT_PREFIX = (
    "你是一位数学建模竞赛评委，现在做冷读盲评。你只收到这份冻结 PDF，"
    "没有题面、源码、运行记录、作者解释或前序审核结论。\n\n"
    "请按以下顺序作答，不要跳过任何部分：\n\n"
    "一、第一印象与竞争力定位\n"
    "作为评委翻开这篇论文的前 30 秒印象：主线是否清楚？能记住什么？"
    "相对普通参赛论文，这篇处于什么档次（偏弱/中等/偏强/强）？"
    "最有可能提升奖项层级的一处改动是什么？\n\n"
    "二、写作风格诊断\n"
    "检查以下 AI 生成文本的典型特征，发现后逐条指出位置和示例：\n"
    "- 大量首先-其次-最后或(1)(2)(3)式无实质内容的分点列举；\n"
    "- 固定开头模式，如：针对问题X，本文采用……方法，得到……结果，表明……；\n"
    "- 空洞总结句，如：模型具有较强鲁棒性、结果表明方法有效、理论基础扎实；\n"
    "- 结论节只重复各问数字，不解释为什么结果呈现这个形态；\n"
    "- 连续多段均以本文/我们/该模型开头的同质句式。\n"
    "如果存在这些特征，说明哪些段落读起来像流水账或技术报告，而非学术论文。\n\n"
    "三、可读性与论证清晰度\n"
    "评价读者能否顺畅理解建模思路：\n"
    "- 核心建模判断是否在论文中清楚说明（为何选择这个模型而非其他）？\n"
    "- 各问是否说明与前问的继承，并完整展开问题分析、数学对象、关键推导和算法步骤？\n"
    "- 分组验证、删失、不平衡、聚合指标或代理变量是否有数据依据，而非直接给结论？\n"
    "- 数学符号和公式是否在使用前定义？\n"
    "- 图表是否真正支撑对应论点，还是仅为凑数？\n"
    "- 结果数字是否有解释（原因），还是只是列出来？\n"
    "- 每问能否明确区分主答案与 fallback，验证是否紧跟其支持的主结果？\n"
    "- 论文是否因过度压缩而省略中央推导、算法或结果机制？页数本身不作为评分依据。\n"
    "- 读完之后，读者能否说清楚这篇论文发现了什么、为什么成立？\n\n"
    "同时执行以下反工作报告检查：多问是否机械复用同一小节序列；正文是否出现 result_id、"
    "fallback、scorer、晋级、回执等内部工作流术语；“本问采用”“结果见表”等句式是否"
    "反复出现；摘要是否按 Q1—Q5 逐项报账；列表和表格是否替代连续推导；标题是否碎成"
    "检查清单；核心问题是否缺少关键推导或机制讨论；每张主图是否真正参与观察—机制—"
    "结论链。还要检查操作步骤是否被误写成数学推导、主结论与关键验证是否相隔过远，"
    "以及是否把文件数、闸门数、公式数、图表数、字数或页数当成论文质量。命中任一项时"
    "指出具体页码，并说明应重组章节、改写语言、移图还是补足论证。\n\n"
    "四、P0/P1 阻断性问题\n"
    "只列出你在本轮确认的严重问题（P0：致命缺陷；P1：重大缺陷），"
    "给出页码/位置、问题描述和影响。不要为了凑数量列 P0/P1。\n"
    "P2/P3 小问题只在第五部分汇总，不要在这里展开。\n\n"
    "五、最高价值修改建议（不超过 5 条）\n"
    "按预期收益排序，允许指出需要重写某章节、替换主图、回到实验增加机制分析。"
    "每条建议标明修复层级：paper（仅措辞、图注、组织或证据边界）、experiment"
    "（需补实验/搜索/复算）或 analysis（需改 endpoint、目标、模型或策略）。"
    "不要默认优先局部修补——只有不影响模型、结果和论证主线的问题才建议最小修改。\n\n"
    "除该 PDF 外不要读取任何文件或既有对话。论文 PDF："
)
PAPER_BLIND_PROMPT_VERSION = "3.1"
LEGACY_PAPER_BLIND_PROMPT_VERSION = "1.0"
PAPER_BLIND_PROMPT_V2_VERSION = "2.0"
PAPER_BLIND_PROMPT_V2_PREFIX = LEGACY_PAPER_BLIND_PROMPT_PREFIX.replace(
    "四、P0/P1 阻断性问题\n",
    "补充：三分钟冷读检索（必须逐项明确回答）\n"
    "- 三分钟内能否找到每个必答问题的直接答案？逐问写找到/未找到及页码。\n"
    "- 只用一句话复述全文最重要的贡献；若无法复述，说明被什么信息遮蔽。\n"
    "- 能否说明各问如何继承，以及后问为何不能与前问任意交换？\n"
    "- 能否指出各问主图及其支持的论点？没有明确主图时如实记录。\n"
    "- 哪些页面最像工作报告、实验日志或教材式模型介绍？给出页码。\n"
    "- 前五页是否建立了足以理解模型选择的数据直觉？\n"
    "这些检索结果只依据 PDF；找不到时不得依据题面或作者解释补全。\n\n"
    "四、P0/P1 阻断性问题\n",
    1,
)
PAPER_BLIND_PROMPT_PREFIX = PAPER_BLIND_PROMPT_V2_PREFIX

PAPER_BLIND_ARGUMENT_ROLES = (
    "mathematical_difficulty",
    "mathematical_object",
    "modeling_basis",
    "derivation",
    "solver",
    "main_result",
    "mechanism",
    "competing_route_or_counterexample",
    "claim_specific_validation",
    "direct_answer",
)
PAPER_BLIND_STRUCTURE_FIELDS = (
    "problem_restatement",
    "problem_analysis",
    "assumptions",
    "symbols_and_data",
    "four_questions",
    "model_evaluation",
)
PAPER_BLIND_STRUCTURED_HEADING = "## 结构化盲评结果"

FINAL_AUDIT_REPORT_PATH = REVIEW_ROOT / "FINAL_SUBMISSION_REVIEW.md"
RED_TEAM_ARTIFACTS_PATH = REVIEW_ROOT / "red_team_artifacts"
_PACKET_ROOTS = {
    "objective-semantics": ("problem",),
    "scientific": (
        "problem",
        "code",
        "results/raw",
        "results/evidence",
        "figures/evidence",
    ),
    "paper-blind": ("problem", "paper/final.pdf", "paper/submission"),
    "final-audit": ("problem", "paper/final.pdf", "paper/submission"),
}
_PACKET_DESTINATIONS = {
    "problem": "problem",
    "code": "source_snapshot",
    "results/raw": "candidate_results",
    "results/evidence": "results_evidence",
    "figures/evidence": "figures_evidence",
    "paper/final.pdf": "paper/final.pdf",
    "paper/submission": "submission",
    "results": "results",
    "figures": "figures",
    "reports": "reports",
    "qa/mechanical-qa.json": "qa/mechanical-qa.json",
}
_REQUIRED_PACKET_ROOTS = {
    "objective-semantics": frozenset(("problem",)),
    "scientific": frozenset((
        "problem", "code", "results/raw", "results/evidence", "figures/evidence",
    )),
    "paper-blind": frozenset(("problem", "paper/final.pdf", "paper/submission")),
    "final-audit": frozenset(("problem", "paper/final.pdf", "paper/submission")),
}
_SEVERITIES = {"none", "P0", "P1", "P2", "P3"}
_VERDICTS = {"pass", "fail", "needs_rework", "revoked"}
_VISUALIZATION_CODE_DIRECTORY = Path("figures")
_RED_TEAM_KINDS = {
    "independent-recompute",
    "counterexample",
    "small-enumeration",
    "alternative-formula",
    "search-challenge",
    "property-test",
    "action-activation-challenge",
    "fixed-action-utilization",
    "geometry-continuous-validation",
}
_SAFE_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_REPORT_ARTIFACT_PATH = re.compile(r"review[\\/]red_team_artifacts[\\/][A-Za-z0-9._/\\-]+")


def _competition_first_run(run_dir: Path) -> bool:
    """判断运行是否使用 Competition-First v3.1 生产主链。"""
    return is_competition_first_state(read_simple_state(run_dir))


def _required_packet_roots(run_dir: Path, kind: str) -> frozenset[str]:
    """返回当前运行版本必须冻结的审查包输入根。

    Competition-First 只要求能复核题面、源码和当前结果的最小输入集，避免旧版
    evidence/publication 双目录重新变成探索阶段的前置合同。

    Args:
        run_dir: 当前运行目录。
        kind: 审查包类别。

    Returns:
        当前工作流版本对应的必需输入根集合。
    """
    if _competition_first_run(run_dir):
        return {
            "objective-semantics": frozenset(("problem",)),
            "scientific": frozenset(("problem", "code", "results/raw")),
            "paper-blind": frozenset(("paper/final.pdf",)),
        }[kind]
    return _REQUIRED_PACKET_ROOTS[kind]

# 科学审查包文件名过滤：只排除明确的质量协议后缀文件，
# 不使用 broad 子串匹配（会误杀 q5_best_so_far.json 等科学数据）
# 匹配 .quality.xxx 和 _quality_xxx 两种分隔模式（兼容新旧命名习惯）
_PACKET_LABEL_EXCLUDE = re.compile(
    r"[._](?:quality|acceptance|quality_audit|quality_exact|quality_verified|quality_candidates)"
    r"\.json$",
    re.IGNORECASE,
)

# 科学审查包内容级去标签：从结果 JSON 中递归删除这些键
_PACKET_CONTENT_EXCLUDE_KEYS = frozenset({
    "accepted", "paper_allowed", "search_adequacy",
    "competition_strength", "qualified", "strong",
    "result_role", "quality", "verified",
    "candidate_accepted", "best_candidate",
    "promotion_allowed", "pass_allowed",
})


def _packet_should_exclude(path: Path) -> bool:
    """判断文件是否应被排除在科学审查包之外。

    检查文件名是否含质量标签。
    """
    if _PACKET_LABEL_EXCLUDE.search(path.name):
        return True
    return False


def _neutralize_value(value: Any) -> Any:
    """递归删除质量裁决字段，用于内存中的哈希计算。"""
    if isinstance(value, dict):
        return {
            key: _neutralize_value(item)
            for key, item in value.items()
            if key not in _PACKET_CONTENT_EXCLUDE_KEYS
        }
    if isinstance(value, list):
        return [_neutralize_value(item) for item in value]
    return value


def _neutralize_candidate_json(source: Path, target: Path) -> None:
    """生成中性候选结果：递归复制 JSON 并删除质量裁决字段。"""
    import json as _json

    try:
        data = _json.loads(source.read_text(encoding="utf-8"))
        neutralized = _neutralize_value(data)
    except (OSError, ValueError):
        shutil.copy2(source, target)
        return
    target.write_text(
        _json.dumps(neutralized, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def _infer_source_root(source_relative: str) -> str:
    """从文件路径推导所属源根（results/raw、code 或 problem）。"""
    if source_relative.startswith("results/raw"):
        return "results/raw"
    if source_relative.startswith("code/"):
        return "code"
    if source_relative.startswith("results/evidence"):
        return "results/evidence"
    if source_relative.startswith("figures/evidence"):
        return "figures/evidence"
    if source_relative.startswith("analysis/"):
        return source_relative
    return "problem"


def _source_is_candidate_results(source_relative: str) -> bool:
    """判断源目录是否为科学审查包的候选结果目录。"""
    return source_relative == "results/raw"


def _schema() -> dict[str, Any]:
    """读取独立审查摘要的 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "simple_review_summary.schema.json")


def _objective_schema(name: str) -> dict[str, Any]:
    """读取目标语义预审的评估或收据 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / f"{name}.schema.json")


def _validate_document(payload: dict[str, Any], schema_name: str, label: str) -> None:
    """用指定 Schema 校验目标语义文档并返回可读错误。"""
    validator = Draft202012Validator(
        _objective_schema(schema_name), format_checker=FormatChecker()
    )
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError(f"{label}不符合协议: " + "; ".join(errors))


def _require_summary(payload: dict[str, Any]) -> None:
    """确保审查摘要格式正确且语义不自相矛盾。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))
    scientific = payload["scientific_review"]
    if scientific["verdict"] == "pass" and scientific["highest_severity"] in {"P0", "P1"}:
        raise ContractError("科学审查含 P0/P1 时不能给出 pass")
    if scientific["verdict"] == "pass" and scientific["full_rerun_required"]:
        raise ContractError("要求全量重跑的科学审查不能给出 pass")
    paper = payload["paper_blind_review"]
    if (
        paper is not None
        and paper["verdict"] == "pass"
        and paper["highest_severity"] in {"P0", "P1"}
    ):
        raise ContractError("盲审含 P0/P1 时不能给出 pass")
    if payload["schema_version"] == "1.4" and paper is not None and paper["verdict"] == "pass":
        assessment = paper["assessment"]
        if (
            not assessment["argumentation_complete"]
            or not assessment["readability_passed"]
            or assessment["empty_sections"]
            or assessment["unreadable_pages"]
        ):
            raise ContractError("盲审未确认逐问论证完整和页面可读时不能给出 pass")
    final_audit = payload.get("final_audit")
    if (
        final_audit is not None
        and final_audit["verdict"] == "pass"
        and final_audit["highest_severity"] in {"P0", "P1"}
    ):
        raise ContractError("最终交付审核含 P0/P1 时不能给出 pass")


def _red_team_schema() -> dict[str, Any]:
    """读取红队可执行证据收据 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "red_team_evidence_receipt.schema.json")


def _require_red_team_receipt(payload: dict[str, Any]) -> None:
    """验证红队脚本的最小可执行证据收据。"""
    validator = Draft202012Validator(_red_team_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("红队证据收据无效: " + "; ".join(errors))


def _red_team_semantic_schema() -> dict[str, Any]:
    """读取各类红队输出的最小科学语义 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "red_team_semantic_output.schema.json")


def _require_red_team_semantic_output(kind: str, path: Path) -> dict[str, Any]:
    """验证红队输出不仅执行成功，而且包含可复验的科学比较。"""
    try:
        evidence = load_json(path)
    except (OSError, ValueError) as exc:
        raise ContractError(f"红队语义输出不是有效 JSON: {path.name}") from exc
    payload = {"kind": kind, "evidence": evidence}
    validator = Draft202012Validator(
        _red_team_semantic_schema(), format_checker=FormatChecker()
    )
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("红队语义输出无效: " + "; ".join(errors))

    if kind in {"independent-recompute", "alternative-formula"}:
        expected = abs(evidence["production_value"] - evidence["independent_value"])
        if not math.isclose(
            evidence["absolute_difference"], expected, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ContractError("红队语义输出的 absolute_difference 与复算值不一致")
    elif kind == "counterexample":
        if evidence["expected"] == evidence["production_observed"]:
            raise ContractError("红队语义输出未形成预期与生产观察之间的反例")
    elif kind == "small-enumeration":
        consistent = evidence["mismatches"] == 0
        if (evidence["verdict"] == "consistent") != consistent:
            raise ContractError("红队语义输出的枚举 mismatches 与 verdict 不一致")
    elif kind == "search-challenge":
        if evidence["independent_candidates"] > evidence["evaluation_budget"]:
            raise ContractError("红队语义输出的独立候选数超过评价预算")
        if evidence["feasible_candidates"] > evidence["independent_candidates"]:
            raise ContractError("红队语义输出的可行候选数超过独立候选数")
    elif kind == "property-test":
        passed = evidence["failures"] == 0
        if (evidence["verdict"] == "pass") != passed:
            raise ContractError("红队语义输出的 property failures 与 verdict 不一致")
    elif kind == "action-activation-challenge":
        _validate_action_activation_evidence(evidence)
    elif kind == "geometry-continuous-validation":
        _validate_geometry_continuous_evidence(evidence)
    return evidence


def _validate_geometry_continuous_evidence(evidence: dict[str, Any]) -> None:
    """拒绝用内部随机采样冒充连续几何边界证明。"""
    sampled = evidence["sampled_approximation"]
    if sampled is not None and sampled == evidence["continuous_quantity"]:
        raise ContractError("连续几何量与采样近似必须使用不同变量名")
    if evidence["verification_method"] == "explicit_discretization_error" and evidence[
        "discretization_error_bound"
    ] is None:
        raise ContractError("显式离散化验证必须给出 discretization_error_bound")
    covered = all(evidence["critical_cases"].values())
    expected = "pass" if covered else "fail"
    if evidence["verdict"] != expected:
        raise ContractError("连续几何验证 verdict 与临界边界覆盖不一致")


def _validate_action_activation_evidence(evidence: dict[str, Any]) -> None:
    """复算可变动作数量挑战的覆盖充分性与 incumbent 结论。"""
    allowed = evidence["allowed_action_count"]
    active = evidence["incumbent_active_count"]
    unused = active < allowed
    if evidence["unused_actions_exist"] != unused:
        raise ContractError("动作激活挑战的 unused_actions_exist 与动作数量不一致")
    direction = evidence["objective_direction"]
    tolerance = float(evidence["improvement_tolerance"])
    trace = [float(value) for value in evidence["best_so_far"]]
    monotone = all(
        current >= previous - tolerance
        if direction == "maximize"
        else current <= previous + tolerance
        for previous, current in zip(trace, trace[1:], strict=False)
    )
    if not monotone:
        raise ContractError("动作激活挑战的 best_so_far 未按目标方向单调更新")
    challenge_best = float(evidence["challenge_best_exact"])
    if not math.isclose(trace[-1], challenge_best, rel_tol=0.0, abs_tol=tolerance):
        raise ContractError("动作激活挑战的 best_so_far 末值与 challenge_best_exact 不一致")
    rounds = evidence["rounds"]
    if sum(item["evaluation_count"] for item in rounds) > evidence["evaluation_budget"]:
        raise ContractError("动作激活挑战轮次消耗超过冻结评价预算")
    if any(item["active_count"] > allowed for item in rounds):
        raise ContractError("动作激活挑战轮次使用了题面不允许的动作数量")
    if evidence["first_feasible_evaluation"] is not None and (
        evidence["first_feasible_evaluation"] > evidence["evaluation_budget"]
    ):
        raise ContractError("动作激活挑战首次可行位置超过评价预算")

    incumbent = float(evidence["incumbent_exact"])
    improved = (
        challenge_best > incumbent + tolerance
        if direction == "maximize"
        else challenge_best < incumbent - tolerance
    )
    method = evidence["coverage_method"]
    details = evidence["coverage_details"]
    sufficient = not unused
    if unused and method == "structural_proof":
        sufficient = bool(_SHA256.fullmatch(str(details.get("proof_sha256", ""))))
    elif unused and method == "small_complete_enumeration":
        enumerated = details.get("enumerated_configurations")
        total = details.get("total_configurations")
        sufficient = (
            isinstance(enumerated, int)
            and not isinstance(enumerated, bool)
            and isinstance(total, int)
            and not isinstance(total, bool)
            and total > 0
            and enumerated == total
        )
    elif unused and method == "insertion_local_optimization":
        required_rounds = min(2, allowed - active)
        covered = {item["active_count"] for item in rounds if item["evaluation_count"] > 0}
        required_counts = set(range(active + 1, active + required_rounds + 1))
        sufficient = (
            required_counts <= covered
            and evidence["consecutive_no_improvement_rounds"] >= required_rounds
        )
    elif unused and method == "independent_full_count_search":
        covered = set(details.get("covered_action_counts", []))
        sufficient = set(range(active + 1, allowed + 1)) <= covered

    expected_verdict = (
        "incumbent_not_competitive"
        if improved
        else "incumbent_competitive"
        if sufficient
        else "inconclusive"
    )
    if evidence["verdict"] != expected_verdict:
        raise ContractError(
            "动作激活挑战 verdict 与 exact 改善及搜索空间覆盖结论不一致"
        )


def _summarize_evidence_verdicts(
    evidence_items: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """聚合红队证据的科学结论，生成不可被人工标签覆盖的门禁。

    Args:
        evidence_items: ``(证据类型, 语义输出)`` 列表。

    Returns:
        是否允许科学通过、是否允许提升竞赛强度及对应原因。
    """
    blocking_reasons: list[str] = []
    promotion_blockers: list[str] = []
    for kind, evidence in evidence_items:
        verdict = evidence.get("verdict")
        if kind in {"independent-recompute", "alternative-formula"}:
            if verdict == "inconsistent":
                blocking_reasons.append(f"{kind}:inconsistent")
        elif kind == "counterexample":
            if verdict == "counterexample_found":
                blocking_reasons.append(f"{kind}:counterexample_found")
        elif kind == "small-enumeration":
            mismatches = evidence.get("mismatches", 0)
            if isinstance(mismatches, int) and mismatches > 0:
                blocking_reasons.append(f"{kind}:mismatches={mismatches}")
        elif kind == "property-test":
            failures = evidence.get("failures", 0)
            if verdict == "fail" or (isinstance(failures, int) and failures > 0):
                blocking_reasons.append(f"{kind}:failures={failures}")
        elif kind == "search-challenge" and verdict in {
            "incumbent_not_competitive",
            "inconclusive",
        }:
            promotion_blockers.append(f"{kind}:{verdict}")
        elif kind == "action-activation-challenge":
            if verdict == "incumbent_not_competitive":
                blocking_reasons.append(f"{kind}:{verdict}")
            elif verdict == "inconclusive":
                promotion_blockers.append(f"{kind}:{verdict}")
        elif kind == "fixed-action-utilization" and verdict in {
            "underutilized_required_action",
            "invalid",
        }:
            blocking_reasons.append(f"{kind}:{verdict}")
        elif kind == "geometry-continuous-validation" and verdict == "fail":
            blocking_reasons.append(f"{kind}:fail")
    if blocking_reasons:
        promotion_blockers.extend(blocking_reasons)
    return {
        "pass_allowed": not blocking_reasons,
        "promotion_allowed": not promotion_blockers,
        "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
        "promotion_blockers": list(dict.fromkeys(promotion_blockers)),
    }


def _red_team_root(run_dir: Path) -> Path:
    """返回当前运行中唯一允许保存红队产物的目录。"""
    return (run_dir.resolve() / RED_TEAM_ARTIFACTS_PATH).resolve()


def _file_evidence(run_dir: Path, path: Path) -> dict[str, Any]:
    """为运行内文件生成冻结路径、哈希和大小。"""
    relative = relative_inside(run_dir, path)
    return {
        "path": relative.as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _require_red_team_artifact_path(run_dir: Path, relative: str, *, must_exist: bool) -> Path:
    """限制脚本、输出和日志全部留在审查证据目录。"""
    path = resolve_inside(run_dir, relative, must_exist=must_exist)
    root = _red_team_root(run_dir)
    if path != root and root not in path.parents:
        raise ContractError("红队脚本和输出必须位于 review/red_team_artifacts/ 内")
    return path


def _red_team_engine_command(run_dir: Path, engine: str) -> str:
    """返回已实际可用的红队执行引擎。

    Competition-First 在执行时探测所需引擎，不要求为此维护独立能力路由；旧运行
    仍严格使用其冻结路由与烟雾测试记录。
    """
    if engine not in {"python", "matlab", "octave"}:
        raise ContractError("红队证据仅支持 python、matlab 或 octave")
    if _competition_first_run(run_dir):
        if engine == "python":
            return sys.executable
        command = shutil.which(engine)
        if command is None:
            raise ContractError(f"当前环境未找到可执行的红队引擎: {engine}")
        return command
    route = require_capability_route(run_dir)
    toolchain = route["toolchain"]
    selected = {toolchain["production_engine"]}
    if toolchain.get("independent_engine") is not None:
        selected.add(toolchain["independent_engine"])
    if engine not in selected:
        raise ContractError("红队引擎必须是当前能力路由选择的生产或独立引擎")
    tooling = load_json(run_dir / "state" / "tooling.json")
    for record in tooling.get("engines", []):
        if not isinstance(record, dict) or record.get("engine") != engine:
            continue
        command = record.get("command")
        probe = record.get("probe")
        if (
            record.get("available") is True
            and isinstance(command, str)
            and isinstance(probe, dict)
            and probe.get("exit_code") == 0
            and probe.get("timed_out") is False
        ):
            return command
    raise ContractError(f"红队引擎未通过当前运行的烟雾测试: {engine}")


def _safe_red_team_argument(value: str) -> str:
    """限制不经 Shell 传递给 Python 红队脚本的附加参数。"""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContractError("红队脚本参数必须是非空字符串")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ContractError("红队脚本参数包含不安全路径")
    return value


def _packet_input_files(packet_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """返回审查脚本可读取的冻结 packet 文件，而不接受任意 run 输入。"""
    files: list[Path] = []
    for item in manifest["files"]:
        packet_relative = item["packet"]
        files.append(_safe_packet_path(packet_dir, packet_relative, must_exist=True))
    return files


def _red_team_command(
    engine: str, command: str, script_name: str, arguments: list[str]
) -> list[str]:
    """构造在清洁目录执行的无 Shell 红队命令。"""
    if engine == "python":
        return [command, "-I", script_name, "packet", "outputs", *arguments]
    if "'" in script_name:
        raise ContractError("MATLAB/Octave 红队脚本名不允许单引号")
    if arguments:
        raise ContractError("MATLAB/Octave 红队脚本请通过环境变量读取 packet 与输出目录")
    expression = f"run('{script_name}')"
    if engine == "matlab":
        return [command, "-batch", expression]
    return [command, "--quiet", "--no-gui", "--eval", expression]


def run_red_team_evidence(
    run_dir: Path,
    *,
    evidence_id: str,
    kind: str,
    packet_manifest: str,
    script_path: str,
    output_paths: list[str],
    engine: str = "python",
    arguments: list[str] | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """在冻结 scientific packet 的清洁目录实际执行一项红队证据。

    审查脚本只会接收到 packet 副本和空输出目录。该边界减少了无意读取生产
    上下文的风险，但不把任意本地脚本误称为操作系统级沙箱；新对话隔离仍由
    Codex 协调层负责。

    Args:
        run_dir: 当前 v3 运行目录。
        evidence_id: 本次攻击的安全唯一标识。
        kind: 攻击产物类型。
        packet_manifest: 已冻结 scientific 审查包清单的运行内路径。
        script_path: 红队脚本的运行内相对路径。
        output_paths: 脚本在 ``outputs/`` 下新建的相对输出名。
        engine: 已由能力路由烟雾测试的 Python、MATLAB 或 Octave。
        arguments: 仅 Python 脚本使用的受控参数。
        timeout_seconds: 命令最长运行秒数。

    Returns:
        写入的红队证据收据。

    Raises:
        ContractError: packet、命令或输出不满足独立可执行证据边界。
    """
    if not _SAFE_EVIDENCE_ID.fullmatch(evidence_id):
        raise ContractError("红队 evidence_id 不合法")
    if kind not in _RED_TEAM_KINDS:
        raise ContractError("不支持的红队证据类型")
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("红队证据 timeout_seconds 必须在 1 至 3600 之间")
    root = run_dir.resolve()
    manifest_path, manifest = _read_packet_manifest(root, packet_manifest)
    if manifest["packet_kind"] != "scientific":
        raise ContractError("红队证据只能读取 scientific 冻结审查包")
    packet_status = verify_review_packet(root, packet_manifest)
    if not packet_status["success"]:
        raise ContractError("红队 scientific 审查包已失效: " + "；".join(packet_status["errors"]))
    artifact_root = _red_team_root(root)
    artifact_root.mkdir(parents=True, exist_ok=True)
    original_script = _require_red_team_artifact_path(root, script_path, must_exist=True)
    suffix = {"python": ".py", "matlab": ".m", "octave": ".m"}.get(engine)
    if suffix is None or not original_script.is_file() or original_script.suffix.casefold() != suffix:
        raise ContractError("红队脚本扩展名与执行引擎不一致")
    if original_script.stat().st_size == 0:
        raise ContractError("红队证据脚本不能为空")
    clean_names: list[str] = []
    for value in output_paths:
        candidate = Path(value)
        if not value or candidate.is_absolute() or ".." in candidate.parts:
            raise ContractError("红队输出必须是 outputs/ 下的相对文件名")
        clean_names.append(candidate.as_posix())
    if not clean_names or len(set(clean_names)) != len(clean_names):
        raise ContractError("红队证据至少需要一个不重复输出")
    execution_dir = artifact_root / "executions" / evidence_id
    if execution_dir.exists():
        raise ContractError("红队 evidence_id 已存在，拒绝覆盖既有执行")
    execution_dir.mkdir(parents=True)
    scratch = execution_dir / "scratch"
    packet_dir = manifest_path.parent
    shutil.copytree(packet_dir, scratch / "packet")
    staged_script = scratch / f"script{suffix}"
    persistent_script = execution_dir / f"script{suffix}"
    shutil.copy2(original_script, staged_script)
    shutil.copy2(original_script, persistent_script)
    outputs_dir = scratch / "outputs"
    outputs_dir.mkdir()
    outputs = [outputs_dir / name for name in clean_names]
    command_path = _red_team_engine_command(root, engine)
    safe_arguments = [_safe_red_team_argument(value) for value in (arguments or [])]
    command = _red_team_command(engine, command_path, staged_script.name, safe_arguments)
    started_at = utc_now()
    environment = dict(os.environ)
    environment["SHUMOZIZI_REVIEW_PACKET"] = "packet"
    environment["SHUMOZIZI_REVIEW_OUTPUTS"] = "outputs"
    try:
        completed = subprocess.run(
            command,
            cwd=scratch,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=environment,
        )
        exit_code, timed_out = completed.returncode, False
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code, timed_out = 124, True
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        ) + f"\n红队证据执行超过 {timeout_seconds} 秒，已终止。\n"
    stdout_path = execution_dir / "stdout.log"
    stderr_path = execution_dir / "stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(stderr, encoding="utf-8", newline="\n")
    if exit_code != 0 or timed_out:
        raise ContractError(f"红队证据命令未成功完成（exit_code={exit_code}）")
    missing = [path for path in outputs if not path.is_file() or path.stat().st_size == 0]
    if missing:
        names = ", ".join(path.relative_to(outputs_dir).as_posix() for path in missing)
        raise ContractError("红队证据缺少非空输出: " + names)
    persistent_outputs = execution_dir / "outputs"
    shutil.copytree(outputs_dir, persistent_outputs)
    semantic_output: Path | None = None
    semantic_errors: list[str] = []
    for output in outputs:
        candidate = persistent_outputs / output.relative_to(outputs_dir)
        if candidate.suffix.casefold() != ".json":
            continue
        try:
            _require_red_team_semantic_output(kind, candidate)
        except ContractError as exc:
            semantic_errors.append(f"{candidate.name}: {exc}")
            continue
        semantic_output = candidate
        break
    if semantic_output is None:
        detail = "；".join(semantic_errors) or "没有 JSON 输出"
        raise ContractError("红队证据缺少合格的语义输出: " + detail)
    staged_packet = scratch / "packet"
    staged_inputs = _packet_input_files(staged_packet, manifest)
    receipt = {
        "schema_name": "red_team_evidence",
        "schema_version": "1.2",
        "run_id": root.name,
        "evidence_id": evidence_id,
        "kind": kind,
        "engine": engine,
        "packet": {
            "manifest_file": relative_inside(root, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
            "packet_tree_sha256": _packet_tree_hash(packet_dir, exclude_visualization_scripts=False),
        },
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "script": _file_evidence(root, persistent_script),
        "inputs": [_file_evidence(root, path) for path in staged_inputs],
        "outputs": [
            _file_evidence(root, persistent_outputs / path.relative_to(outputs_dir))
            for path in outputs
        ],
        "semantic_output": _file_evidence(root, semantic_output),
        "stdout": _file_evidence(root, stdout_path),
        "stderr": _file_evidence(root, stderr_path),
        "started_at": started_at,
        "finished_at": utc_now(),
    }
    _require_red_team_receipt(receipt)
    receipt_path = execution_dir / "receipt.json"
    atomic_json(receipt_path, receipt)
    return receipt


def _verify_file_evidence(run_dir: Path, evidence: dict[str, Any], *, require_nonempty: bool) -> Path:
    """重新计算一条冻结文件证据，防止审查结果跨文件变更复用。"""
    path = resolve_inside(run_dir, evidence["path"], must_exist=True)
    if sha256_file(path) != evidence["sha256"] or path.stat().st_size != evidence["size_bytes"]:
        raise ContractError(f"红队证据文件哈希或大小已变化: {evidence['path']}")
    if require_nonempty and path.stat().st_size == 0:
        raise ContractError(f"红队证据输出为空: {evidence['path']}")
    return path


def verify_red_team_artifacts(run_dir: Path) -> dict[str, Any]:
    """复验所有已冻结红队执行，返回可供导入摘要绑定的文件清单。"""
    root = run_dir.resolve()
    errors: list[str] = []
    receipts: list[dict[str, str]] = []
    evidence_files: dict[str, dict[str, str]] = {}
    evidence_kinds: set[str] = set()
    semantic_evidence: list[tuple[str, dict[str, Any]]] = []
    evidence_records: list[dict[str, Any]] = []
    receipt_paths = sorted((_red_team_root(root) / "executions").glob("*/receipt.json"))
    if not receipt_paths:
        return {
            "valid": False,
            "errors": ["缺少 review/red_team_artifacts/ 下的实际执行证据"],
            "receipts": [],
            "files": {},
            "kinds": [],
            "semantic_evidence": [],
            "evidence_records": [],
        }
    for receipt_path in receipt_paths:
        try:
            receipt = load_json(receipt_path)
            _require_red_team_receipt(receipt)
            if receipt["schema_version"] != "1.2":
                raise ContractError("旧版红队收据缺少科学语义输出，不能作为当前生产放行依据")
            if receipt["run_id"] != root.name:
                raise ContractError("红队证据收据 run_id 不匹配")
            execution_dir = receipt_path.parent.resolve()
            packet = receipt["packet"]
            packet_status = verify_review_packet(root, packet["manifest_file"])
            if not packet_status["success"]:
                raise ContractError("红队绑定的 scientific 审查包已失效: " + "；".join(packet_status["errors"]))
            manifest_path, manifest = _read_packet_manifest(root, packet["manifest_file"])
            if manifest["packet_kind"] != "scientific":
                raise ContractError("红队证据未绑定 scientific 审查包")
            if packet["manifest_sha256"] != sha256_file(manifest_path):
                raise ContractError("红队证据审查包清单哈希已变化")
            if packet["packet_tree_sha256"] != _packet_tree_hash(
                manifest_path.parent, exclude_visualization_scripts=False
            ):
                raise ContractError("红队证据审查包快照已变化")
            relative_receipt = relative_inside(root, receipt_path).as_posix()
            receipts.append({"path": relative_receipt, "sha256": sha256_file(receipt_path)})
            script = _verify_file_evidence(root, receipt["script"], require_nonempty=True)
            if execution_dir not in script.parents:
                raise ContractError("红队证据脚本不在对应清洁执行目录")
            if script.suffix.casefold() != {"python": ".py", "matlab": ".m", "octave": ".m"}[receipt["engine"]]:
                raise ContractError("红队脚本与收据引擎不一致")
            if not any(script.name in part for part in receipt["command"]):
                raise ContractError("红队证据命令未绑定登记脚本")
            for item in receipt["inputs"]:
                input_path = _verify_file_evidence(root, item, require_nonempty=False)
                staged_packet = execution_dir / "scratch" / "packet"
                if staged_packet not in input_path.parents:
                    raise ContractError("红队证据读取了冻结 packet 以外的输入")
            for item in receipt["outputs"]:
                output = _verify_file_evidence(root, item, require_nonempty=True)
                if execution_dir / "outputs" not in output.parents:
                    raise ContractError("红队证据输出不在对应清洁执行目录")
            semantic_output = _verify_file_evidence(
                root, receipt["semantic_output"], require_nonempty=True
            )
            if execution_dir / "outputs" not in semantic_output.parents:
                raise ContractError("红队语义输出不在对应清洁执行目录")
            if not any(
                item["path"] == receipt["semantic_output"]["path"]
                for item in receipt["outputs"]
            ):
                raise ContractError("红队语义输出未列入登记输出")
            evidence = _require_red_team_semantic_output(receipt["kind"], semantic_output)
            semantic_evidence.append((receipt["kind"], evidence))
            evidence_record = {
                "evidence_id": receipt["evidence_id"],
                "kind": receipt["kind"],
                "engine": receipt["engine"],
                "receipt": {"file": relative_receipt, "sha256": sha256_file(receipt_path)},
                "semantic_output": evidence,
                "semantic_output_file": {
                    "file": receipt["semantic_output"]["path"],
                    "sha256": receipt["semantic_output"]["sha256"],
                },
            }
            if isinstance(evidence.get("question_id"), str):
                evidence_record["question_id"] = evidence["question_id"]
            if isinstance(evidence.get("claim_id"), str):
                evidence_record["claim_id"] = evidence["claim_id"]
            evidence_records.append(evidence_record)
            for item in (
                receipt["script"],
                *receipt["inputs"],
                *receipt["outputs"],
                receipt["stdout"],
                receipt["stderr"],
            ):
                path = _verify_file_evidence(root, item, require_nonempty=False)
                evidence_files[relative_inside(root, path).as_posix()] = {
                    "path": relative_inside(root, path).as_posix(),
                    "sha256": sha256_file(path),
                }
            evidence_kinds.add(receipt["kind"])
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{receipt_path.name}: {exc}")
    return {
        "valid": not errors,
        "errors": errors,
        "receipts": receipts,
        "files": evidence_files,
        "kinds": sorted(evidence_kinds),
        "semantic_evidence": semantic_evidence,
        "evidence_records": evidence_records,
    }


def _verified_evidence_assessment(run_dir: Path) -> dict[str, Any]:
    """复验执行收据并聚合其科学结论。"""
    verification = verify_red_team_artifacts(run_dir)
    if not verification["valid"]:
        raise ContractError("红队执行证据无效: " + "；".join(verification["errors"]))
    return _summarize_evidence_verdicts(verification["semantic_evidence"])


def _bind_red_team_artifacts(run_dir: Path, report: dict[str, str]) -> dict[str, Any]:
    """将报告引用与真实执行证据绑定，避免自由文本自证科学正确性。"""
    verification = verify_red_team_artifacts(run_dir)
    if not verification["valid"]:
        raise ContractError("红队执行证据无效: " + "；".join(verification["errors"]))
    report_path = _safe_run_path(run_dir, report["file"])
    content = report_path.read_text(encoding="utf-8")
    citations: list[dict[str, str]] = []
    for match in _REPORT_ARTIFACT_PATH.finditer(content):
        relative = match.group(0).replace("\\", "/").rstrip(".,;:!?")
        if relative not in verification["files"]:
            raise ContractError(f"审查报告引用了不存在或未执行的红队证据: {relative}")
        citations.append(verification["files"][relative])
    unique = {item["path"]: item for item in citations}
    if not unique:
        raise ContractError("科学审查报告必须引用至少一个 review/red_team_artifacts/ 的真实输出")
    output_paths = {
        item["path"]
        for receipt_path in verification["receipts"]
        for item in load_json(_safe_run_path(run_dir, receipt_path["path"]))["outputs"]
    }
    if not set(unique) & output_paths:
        raise ContractError("科学审查报告必须引用至少一个实际红队输出，而非只引用脚本")
    return {
        "receipts": verification["receipts"],
        "report_citations": list(unique.values()),
        "evidence_kinds": verification["kinds"],
    }


def _safe_run_path(run_dir: Path, relative: str, *, must_exist: bool = True) -> Path:
    """解析运行目录内文件，并统一返回其规范相对路径。"""
    return resolve_inside(run_dir, relative, must_exist=must_exist)


def _safe_packet_path(packet_dir: Path, relative: str, *, must_exist: bool = False) -> Path:
    """解析冻结包内路径，拒绝清单将检查目标导向包外。

    Args:
        packet_dir: 冻结审查包根目录。
        relative: 清单内的相对路径。
        must_exist: 是否要求目标已存在。

    Returns:
        位于审查包内的规范路径。

    Raises:
        ContractError: 路径为空、绝对路径、越过审查包边界或缺失。
    """
    candidate_input = Path(relative)
    if candidate_input.is_absolute() or not relative.strip():
        raise ContractError(f"审查包路径必须为非空相对路径: {relative}")
    root = packet_dir.resolve()
    candidate = (root / candidate_input).resolve()
    if candidate != root and root not in candidate.parents:
        raise ContractError(f"审查包路径越界: {relative}")
    if must_exist and not candidate.exists():
        raise ContractError(f"审查包文件不存在: {relative}")
    return candidate


def _source_root(run_dir: Path, relative: str) -> Path | None:
    """读取允许进入审查包的运行内目录或文件。"""
    candidate = (run_dir.resolve() / relative).resolve()
    if candidate != run_dir.resolve() and run_dir.resolve() not in candidate.parents:
        raise ContractError(f"审查包源路径越界: {relative}")
    return candidate if candidate.exists() else None


def _packet_files(
    source: Path,
    *,
    exclude_visualization_scripts: bool,
    exclude_quality_labels: bool = False,
) -> list[Path]:
    """返回需要冻结的文件，允许科学审查排除后续阶段的纯绘图脚本和质量标签。

    Args:
        exclude_visualization_scripts: 排除 figures/ 目录下的纯绘图脚本。
        exclude_quality_labels: 排除文件名含质量标签的文件（用于科学包去标签化）。
    """
    if source.is_file():
        if exclude_quality_labels and _packet_should_exclude(source):
            return []
        return [source]
    source_root = source.resolve()
    files: list[Path] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(source_root)
        except ValueError:
            # Windows Junction 可能把运行时依赖映射到运行目录外；审查包只能冻结本 run 内的源码。
            continue
        files.append(path)
    if exclude_quality_labels:
        files = [path for path in files if not _packet_should_exclude(path)]
    if not exclude_visualization_scripts:
        return files
    return [
        path
        for path in files
        if not path.relative_to(source).is_relative_to(_VISUALIZATION_CODE_DIRECTORY)
    ]


def _packet_tree_hash(
    source: Path,
    *,
    exclude_visualization_scripts: bool,
    exclude_quality_labels: bool = False,
) -> str:
    """计算审查快照的内容哈希，保证源树与冻结副本使用相同过滤规则。"""
    digest = hashlib.sha256()
    for item in _packet_files(
        source,
        exclude_visualization_scripts=exclude_visualization_scripts,
        exclude_quality_labels=exclude_quality_labels,
    ):
        relative = item.name if source.is_file() else item.relative_to(source).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def _packet_identifier(kind: str, state_revision: int) -> str:
    """生成不会覆盖历史审查证据的审查包标识。"""
    stamp = utc_now().replace("-", "").replace(":", "").replace("+", "").replace("Z", "Z")
    return f"{kind}-r{state_revision}-{stamp}"


def materialize_submission_package(run_dir: Path) -> dict[str, Any]:
    """物化评委实际可见的 PDF 与题定提交文件。

    ``problem/attachments`` 保存只读原始附件，其中可能包含空白结果模板；真正
    填写后的文件必须由求解阶段写入 ``artifacts/``，再由本函数复制到标准提交
    目录。这样盲审不会把空模板误当成最终答案。

    Args:
        run_dir: 当前 v3 运行目录。

    Returns:
        写入 ``paper/submission/manifest.json`` 的提交清单。

    Raises:
        ContractError: PDF 缺失、产物为空或提交目录含未登记文件。
    """
    root = run_dir.resolve()
    pdf = root / "paper" / "final.pdf"
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise ContractError("标准提交包需要非空 paper/final.pdf")
    from shumozizi.simple.competition import verify_submission_exports

    export_check = verify_submission_exports(root)
    if not export_check["success"]:
        raise ContractError(
            "标准提交包的 Excel 来源或核心数值不一致: "
            + "; ".join(export_check["errors"])
        )
    # DOCX 是否必交由竞赛交付配置决定，而非全局硬编码。缺少 pandoc 的环境仍可提交
    # 纯 PDF；只有显式声明 docx_required 的竞赛才在缺少 Word 时阻断。
    delivery = delivery_requirements_for_competition(
        read_simple_state(run_dir).get("competition", "")
    )
    docx = root / "paper" / "final.docx"
    docx_present = docx.is_file() and docx.stat().st_size > 0
    if delivery["docx_required"] and not docx_present:
        raise ContractError(
            "该竞赛交付配置要求同时提供 paper/final.docx（Word 版本）。"
            "请在 compile_paper 后确认 pandoc 已正常生成 .docx，或单独运行 compile_docx。"
        )
    submission_dir = root / "paper" / "submission"
    submission_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = submission_dir / "manifest.json"
    previous_files: set[str] = set()
    previous: dict[str, Any] | None = None
    if manifest_path.is_file():
        previous = load_json(manifest_path)
        if not isinstance(previous, dict) or previous.get("schema_version") != "1.0":
            raise ContractError("paper/submission 含未知提交清单，拒绝覆盖")
        previous_files = {
            item["submission"]
            for item in previous.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("submission"), str)
        }
    existing = {
        path.relative_to(submission_dir).as_posix()
        for path in submission_dir.rglob("*")
        if path.is_file() and path != manifest_path
    }
    unmanaged = existing - previous_files
    if unmanaged:
        raise ContractError(
            "paper/submission 含未登记文件，不能猜测其提交角色: "
            + ", ".join(sorted(unmanaged))
        )

    sources: list[tuple[Path, str, str]] = [
        (pdf, "final.pdf", "final_pdf"),
    ]
    # Word 版本仅在存在且非空时纳入提交包；缺失时通过下方 stale 清理移除历史副本。
    if docx_present:
        sources.append((docx, "final.docx", "final_docx"))
    artifacts_dir = root / "artifacts"
    attachment_names = {
        path.name.casefold()
        for path in (root / "problem" / "attachments").rglob("*")
        if path.is_file()
    }
    if artifacts_dir.is_dir():
        for source in sorted(path for path in artifacts_dir.rglob("*") if path.is_file()):
            if source.stat().st_size == 0:
                raise ContractError(
                    "标准提交包拒绝空产物: " + relative_inside(root, source).as_posix()
                )
            relative = source.relative_to(artifacts_dir).as_posix()
            role = (
                "completed_problem_attachment"
                if source.name.casefold() in attachment_names
                else "submission_attachment"
            )
            sources.append((source, f"attachments/{relative}", role))

    expected_files = [
        {
            "source": relative_inside(root, source).as_posix(),
            "submission": destination,
            "role": role,
            "sha256": sha256_file(source),
        }
        for source, destination, role in sources
    ]
    if previous is not None and previous.get("files") == expected_files:
        destinations_current = all(
            (submission_dir / item["submission"]).is_file()
            and sha256_file(submission_dir / item["submission"]) == item["sha256"]
            for item in expected_files
        )
        if destinations_current:
            return previous

    current_destinations = {destination for _, destination, _ in sources}
    for stale in previous_files - current_destinations:
        stale_path = _safe_packet_path(submission_dir, stale, must_exist=False)
        if stale_path.is_file():
            stale_path.unlink()

    files: list[dict[str, str]] = []
    for source, destination_relative, role in sources:
        destination = _safe_packet_path(
            submission_dir, destination_relative, must_exist=False
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files.append(
            {
                "source": relative_inside(root, source).as_posix(),
                "submission": destination_relative,
                "role": role,
                "sha256": sha256_file(destination),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "run_id": root.name,
        "files": files,
        "created_at": utc_now(),
    }
    atomic_json(manifest_path, manifest)
    return manifest


def _copy_packet_tree(
    run_dir: Path,
    packet_dir: Path,
    source_relative: str,
    destination_relative: str,
    *,
    exclude_quality_labels: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """复制一个审查允许的源树，并记录原始与副本的逐文件哈希。

    Args:
        exclude_quality_labels: 同时过滤文件名和哈希计算中的质量标签文件，
            确保源树哈希和副本树哈希使用同一个过滤后的文件集合。
            仅对 results/raw 源启用，不会误过滤 problem/code 中的合法文件。
    """
    source = _source_root(run_dir, source_relative)
    if source is None:
        return None, []
    # 只对候选结果目录应用标签过滤，不禁用 problem/code 中的 best/final 等正常文件名
    filter_labels = exclude_quality_labels and _source_is_candidate_results(source_relative)
    destination = packet_dir / destination_relative
    copied: list[dict[str, str]] = []
    exclude_visualization_scripts = source_relative == "code"
    if source.is_file():
        if filter_labels and _packet_should_exclude(source):
            return {"source": relative_inside(run_dir, source).as_posix(),
                    "packet": destination_relative, "sha256": ""}, []
        destination.parent.mkdir(parents=True, exist_ok=True)
        if filter_labels and source.suffix.lower() == ".json":
            _neutralize_candidate_json(source, destination)
            copied_hash = sha256_file(destination)  # 副本哈希（中性化后内容）
        else:
            shutil.copy2(source, destination)
            copied_hash = sha256_file(source)  # 源文件哈希（内容未变）
        copied.append(
            {
                "source": relative_inside(run_dir, source).as_posix(),
                "packet": destination.relative_to(packet_dir).as_posix(),
                "sha256": copied_hash,
            }
        )
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for item in _packet_files(
            source,
            exclude_visualization_scripts=exclude_visualization_scripts,
            exclude_quality_labels=filter_labels,
        ):
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if filter_labels and item.suffix.lower() == ".json":
                _neutralize_candidate_json(item, target)
                copied_hash = sha256_file(target)
            else:
                shutil.copy2(item, target)
                copied_hash = sha256_file(item)
            copied.append(
                {
                    "source": relative_inside(run_dir, item).as_posix(),
                    "packet": target.relative_to(packet_dir).as_posix(),
                    "sha256": copied_hash,
                }
            )
    # 哈希必须使用过滤后的同一视图（和 _packet_files 使用的 exclude_quality_labels 一致）
    # 对已复制的包目录计算哈希，而非源目录——中性化会改变 JSON 内容
    packet_source = packet_dir / destination_relative
    return {
        "source": relative_inside(run_dir, source).as_posix(),
        "packet": destination_relative,
        "sha256": _packet_tree_hash(
            packet_source if packet_source.exists() else source,
            exclude_visualization_scripts=exclude_visualization_scripts,
            exclude_quality_labels=False,  # 包目录已过滤+中性化，不再重复过滤
        ),
    }, copied


def _build_competition_review_packet(run_dir: Path, *, kind: str) -> dict[str, Any]:
    """冻结 v3.1 的最小审查包，不创建覆盖或终审生命周期。

    Args:
        run_dir: 当前 Competition-First 运行目录。
        kind: 目标语义、科学挑战或 PDF 盲审。

    Returns:
        审查包清单。
    """
    allowed = {"objective-semantics", "scientific", "paper-blind"}
    if kind not in allowed:
        raise ContractError("Competition-First 不支持 final-audit；可创建 objective-semantics、scientific 或 paper-blind 审查包")
    state = read_simple_state(run_dir)
    required_phase = {
        "objective-semantics": "analysis",
        "scientific": "experiment",
        "paper-blind": "paper_review",
    }[kind]
    if state["phase"] != required_phase:
        raise ContractError(f"{kind} 审查包只能在 {required_phase} 阶段创建")
    if kind == "paper-blind":
        if not (run_dir / "paper" / "final.pdf").is_file():
            raise ContractError("paper-blind 审查包需要已编译的 paper/final.pdf")

    roots_by_kind = {
        "objective-semantics": ("problem",),
        "scientific": ("problem", "code", "results/raw"),
        # 最终盲评只接收冻结 PDF，避免题面、源码、历史结论和作者解释污染评委视角。
        "paper-blind": ("paper/final.pdf",),
    }
    existing_roots = [
        relative for relative in roots_by_kind[kind] if _source_root(run_dir, relative) is not None
    ]
    if not existing_roots:
        raise ContractError("审查包没有可冻结的题面、源码、结果或论文输入")
    packet_id = _packet_identifier(kind, state["revision"])
    packet_dir = run_dir / REVIEW_ROOT / "packet" / kind / packet_id
    packet_dir.mkdir(parents=True, exist_ok=False)
    roots: list[dict[str, Any]] = []
    files: list[dict[str, str]] = []
    for source_relative in existing_roots:
        root, copied = _copy_packet_tree(
            run_dir,
            packet_dir,
            source_relative,
            _PACKET_DESTINATIONS[source_relative],
            exclude_quality_labels=kind == "scientific",
        )
        if root is not None:
            roots.append(root)
            files.extend(copied)
    manifest = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "packet_kind": kind,
        "packet_id": packet_id,
        "source_roots": roots,
        "files": files,
        "created_at": utc_now(),
    }
    if kind == "paper-blind":
        manifest["prompt_version"] = PAPER_BLIND_PROMPT_VERSION
    atomic_json(packet_dir / "manifest.json", manifest)
    return manifest


def build_review_packet(run_dir: Path, *, kind: str) -> dict[str, Any]:
    """冻结供独立对话阅读的无质量标签审查包。

    Args:
        run_dir: 当前 v3 运行目录。
        kind: ``objective-semantics``、``scientific``、``paper-blind`` 或 ``final-audit``。

    Returns:
        已写入的包清单。

    Raises:
        ContractError: 阶段、包类别或所需 PDF 不满足流程边界。
    """
    if _competition_first_run(run_dir):
        return _build_competition_review_packet(run_dir, kind=kind)
    if kind not in _PACKET_ROOTS:
        raise ContractError(
            "审查包类别必须为 objective-semantics、scientific、paper-blind 或 final-audit"
        )
    state = read_simple_state(run_dir)
    required_phase = {
        "objective-semantics": "analysis",
        "scientific": "scientific_review",
        "paper-blind": "paper_review",
        "final-audit": "final_review",
    }[kind]
    if state["phase"] != required_phase:
        raise ContractError(f"{kind} 审查包只能在 {required_phase} 阶段创建")
    if kind in {"paper-blind", "final-audit"} and not (
        run_dir / "paper" / "final.pdf"
    ).is_file():
        raise ContractError(f"{kind} 审查包需要已编译的 paper/final.pdf")
    if kind in {"paper-blind", "final-audit"}:
        materialize_submission_package(run_dir)
    if kind == "final-audit":
        require_final_review_allowed(run_dir)

    missing_roots = [
        relative
        for relative in sorted(_REQUIRED_PACKET_ROOTS[kind])
        if _source_root(run_dir, relative) is None
    ]
    if missing_roots:
        raise ContractError("审查包缺少必需输入根: " + ", ".join(missing_roots))

    packet_id = _packet_identifier(kind, state["revision"])
    packet_dir = run_dir / REVIEW_ROOT / "packet" / kind / packet_id
    packet_dir.mkdir(parents=True, exist_ok=False)
    roots: list[dict[str, Any]] = []
    files: list[dict[str, str]] = []
    for source_relative in _PACKET_ROOTS[kind]:
        root, copied = _copy_packet_tree(
            run_dir,
            packet_dir,
            source_relative,
            _PACKET_DESTINATIONS[source_relative],
            exclude_quality_labels=(kind == "scientific"),
        )
        if root is not None:
            roots.append(root)
            files.extend(copied)
    manifest = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "packet_kind": kind,
        "packet_id": packet_id,
        "source_roots": roots,
        "files": files,
        "created_at": utc_now(),
    }
    if kind == "paper-blind":
        manifest["prompt_version"] = PAPER_BLIND_PROMPT_VERSION
    atomic_json(packet_dir / "manifest.json", manifest)
    return manifest


def _read_packet_manifest(run_dir: Path, manifest_relative: str) -> tuple[Path, dict[str, Any]]:
    """读取并做最小结构检查的冻结审查包清单。"""
    manifest_path = _safe_run_path(run_dir, manifest_relative)
    payload = load_json(manifest_path)
    if not isinstance(payload, dict):
        raise ContractError("审查包 manifest 必须是对象")
    expected = {
        "schema_version",
        "run_id",
        "packet_kind",
        "packet_id",
        "source_roots",
        "files",
        "created_at",
    }
    packet_kind = payload.get("packet_kind")
    allowed_keys = [expected]
    if packet_kind == "paper-blind":
        allowed_keys.append(expected | {"prompt_version"})
    if set(payload) not in allowed_keys or payload.get("schema_version") != "1.0":
        raise ContractError("审查包 manifest 格式不兼容")
    if payload["run_id"] != run_dir.name:
        raise ContractError("审查包 run_id 不匹配")
    if payload["packet_kind"] not in _PACKET_ROOTS:
        raise ContractError("审查包类别不合法")
    prompt_version = payload.get("prompt_version")
    if prompt_version is not None and prompt_version != PAPER_BLIND_PROMPT_VERSION:
        raise ContractError("paper-blind 提示词版本不受支持")
    if not isinstance(payload["source_roots"], list) or not isinstance(payload["files"], list):
        raise ContractError("审查包缺少源树或文件清单")
    packet_id = payload["packet_id"]
    if not isinstance(packet_id, str) or not packet_id:
        raise ContractError("审查包 packet_id 不合法")
    packet_dir = _safe_run_path(
        run_dir,
        (REVIEW_ROOT / "packet" / payload["packet_kind"] / packet_id).as_posix(),
        must_exist=False,
    )
    if manifest_path != packet_dir / "manifest.json":
        raise ContractError("审查包 manifest 不在声明的冻结目录")

    roots_by_source: dict[str, dict[str, Any]] = {}
    for root in payload["source_roots"]:
        if not isinstance(root, dict) or set(root) != {"source", "packet", "sha256"}:
            raise ContractError("审查包源树条目格式不合法")
        source = root["source"]
        packet = root["packet"]
        digest = root["sha256"]
        if (
            not isinstance(source, str)
            or source not in _PACKET_ROOTS[payload["packet_kind"]]
            or not isinstance(packet, str)
            or packet != _PACKET_DESTINATIONS[source]
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ContractError("审查包源树条目包含未允许的路径或哈希")
        _safe_packet_path(packet_dir, packet)
        if source in roots_by_source:
            raise ContractError("审查包源树重复")
        roots_by_source[source] = root
    missing_roots = _required_packet_roots(run_dir, payload["packet_kind"]) - set(roots_by_source)
    if missing_roots:
        raise ContractError("审查包缺少必要源树: " + ", ".join(sorted(missing_roots)))

    for item in payload["files"]:
        if not isinstance(item, dict) or set(item) != {"source", "packet", "sha256"}:
            raise ContractError("审查包文件条目格式不合法")
        source = item["source"]
        packet = item["packet"]
        digest = item["sha256"]
        if not all(isinstance(value, str) and value for value in (source, packet, digest)):
            raise ContractError("审查包文件条目缺少路径或哈希")
        if len(digest) != 64:
            raise ContractError("审查包文件哈希格式不合法")
        matching_roots = [
            root
            for root_source, root in roots_by_source.items()
            if source == root_source or source.startswith(f"{root_source}/")
        ]
        if not matching_roots:
            raise ContractError("审查包文件源路径不属于允许源树")
        if not any(
            packet == str(root["packet"]) or packet.startswith(f"{root['packet']}/")
            for root in matching_roots
        ):
            raise ContractError("审查包文件路径不属于对应冻结源树")
        _safe_packet_path(packet_dir, packet)
    return manifest_path, payload


def paper_blind_review_prompt(run_dir: Path, manifest_relative: str) -> str:
    """返回启动全新顶层盲审任务时必须原样使用的极简提示词。

    Args:
        run_dir: 当前运行目录。
        manifest_relative: ``paper-blind`` 冻结包清单的运行内相对路径。

    Returns:
        只包含严格审核要求和冻结 PDF 绝对路径的提示词。

    Raises:
        ContractError: 清单类型错误或冻结 PDF 不存在。
    """
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_relative)
    if manifest["packet_kind"] != "paper-blind":
        raise ContractError("极简盲审提示词只能绑定 paper-blind 审查包")
    frozen_pdf = manifest_path.parent / _PACKET_DESTINATIONS["paper/final.pdf"]
    if not frozen_pdf.is_file():
        raise ContractError("paper-blind 审查包缺少冻结 PDF")
    prompt_version = manifest.get(
        "prompt_version", LEGACY_PAPER_BLIND_PROMPT_VERSION
    )
    if prompt_version == LEGACY_PAPER_BLIND_PROMPT_VERSION:
        prefix = LEGACY_PAPER_BLIND_PROMPT_PREFIX
    elif prompt_version == PAPER_BLIND_PROMPT_V2_VERSION:
        prefix = PAPER_BLIND_PROMPT_V2_PREFIX
    elif prompt_version == PAPER_BLIND_PROMPT_VERSION:
        state = read_simple_state(run_dir)
        prefix = PAPER_BLIND_PROMPT_PREFIX.replace(
            "除该 PDF 外不要读取任何文件或既有对话。论文 PDF：",
            _paper_blind_manual_intervention_instruction()
            + "\n\n"
            + _paper_blind_structured_instruction(state["required_questions"])
            + "\n\n除该 PDF 外不要读取任何文件或既有对话。论文 PDF：",
            1,
        )
    else:
        raise ContractError("paper-blind 提示词版本不受支持")
    return prefix + str(frozen_pdf.resolve())


def _paper_blind_manual_intervention_instruction() -> str:
    """生成最终 PDF 盲审中固定记录的人工干预要求。

    人工干预只补充审查维度，不改变 PDF-only 输入边界，也不构成新的工作流阶段。
    """
    return (
        "六、固定人工干预：按数学建模国赛标准严格审核\n"
        "以下要求来自用户的固定人工干预，必须逐项回答，不得只评价思路或建模方法：\n"
        f"“{MANUAL_INTERVENTION_PROMPT}”\n"
        "请只依据这份 PDF，给出有页码或图号定位的判断：\n"
        "- 与国赛优秀论文相比，具体差距是什么，按影响排序；\n"
        "- 哪些论点缺少图、图表或机制证据，哪些图应补、替换或移入正文；\n"
        "- 作品更像竞赛报告、技术报告还是完整论文，并说明达到论文形态还缺什么；\n"
        "- 检查笔法、学术文风、句式重复、空话、术语一致性和润色优先级；\n"
        "- 检查排版、字体字号、公式、图注、表注、分页、留白、图表可读性和版面层级；\n"
        "- 特别核对问题一、二、三（及后续各问）是否在各自章节开头先给直接结论，"
        "而不是让评委翻到章节末尾寻找答案；正文中文是否为宋体小四（12pt），"
        "数学公式中的字母是否为 Times New Roman 系斜体；\n"
        "- 检查论证主线、问题递进、观察—机制—结论链和结果解释是否成立；\n"
        "- 解释正文只有十几页的原因：区分合理压缩、论证缺失、图表不足和无效重复；\n"
        "- 给出不超过 8 条可执行修改，标明优先级、修复层级（paper/experiment/analysis）"
        "和验收标准。\n"
        "不得联网检索、对照外部论文或补读题面；“优秀论文差距”只能依据 PDF 中可观察的"
        "竞赛论文表现标准作相对判断，不能声称获奖或名次。\n"
    )


def _paper_blind_structured_instruction(required_questions: list[str]) -> str:
    """生成与自由盲评报告同源的结构化结果说明。"""
    answers = {question_id: False for question_id in required_questions}
    heroes = {question_id: False for question_id in required_questions}
    findings = {
        question_id: {
            "missing_roles": ["derivation"],
            "pages": [1],
            "finding": "请替换为该问在 PDF 中的具体定位与缺失或完整性判断。",
        }
        for question_id in required_questions
    }
    links = [
        {
            "from": previous,
            "to": current,
            "inheritance": "请替换为 PDF 中可见的继承对象与新增困难。",
        }
        for previous, current in zip(required_questions, required_questions[1:], strict=False)
    ]
    template = {
        "cold_read": {
            "input_scope": "frozen_pdf_only",
            "direct_answers_found_within_3_minutes": answers,
            "one_sentence_contribution": "请替换为仅依据 PDF 可复述的一句话贡献。",
            "cross_question_inheritance_understood": False,
            "first_five_pages_establish_data_intuition": False,
            "hero_figures_identified": heroes,
            "report_like_pages": [],
        },
        "structure": {field: "issue" for field in PAPER_BLIND_STRUCTURE_FIELDS},
        "argument_findings": findings,
        "question_progression": {
            "status": "issue",
            "interchangeable_questions": True,
            "links": links,
            "summary": "请替换为 PDF 中各问继承与递进关系的具体判断。",
        },
        "narrative_risks": [],
        "review_summary": "请替换为与前文自由盲评一致的结构化总结。",
    }
    question_text = "、".join(required_questions)
    return (
        "七、结构化盲评结果（必须与上文判断一致）\n"
        f"对必答问题 {question_text}，在报告末尾原样使用标题“{PAPER_BLIND_STRUCTURED_HEADING}”，"
        "并紧跟一个 json 代码块。不要另建文件。missing_roles 只能从以下角色中选择："
        + "、".join(PAPER_BLIND_ARGUMENT_ROLES)
        + "。每问 pages 至少填写一个实际页码；finding 必须写可定位的具体判断，不能只写 pass/完整/无问题。"
        "找不到直接答案时，cold_read 对应值必须为 false，且 missing_roles 必须包含 direct_answer。"
        "自由报告与结构化结果冲突时不得给出通过结论。请完整替换模板中的示例判断：\n\n"
        + PAPER_BLIND_STRUCTURED_HEADING
        + "\n```json\n"
        + json.dumps(template, ensure_ascii=False, indent=2)
        + "\n```"
    )


def paper_blind_review_prompt_sha256(run_dir: Path, manifest_relative: str) -> str:
    """返回当前冻结 PDF 极简盲审提示词的 SHA-256。"""
    return sha256_bytes(paper_blind_review_prompt(run_dir, manifest_relative).encode("utf-8"))


def verify_review_packet(run_dir: Path, manifest_relative: str) -> dict[str, Any]:
    """验证审查包及其原始输入没有在审查后漂移。

    对科学审查包的 results/raw 源使用与构建时相同的过滤视图计算哈希，
    确保验证不因质量标签文件被排除而产生假阳性。
    """
    try:
        manifest_path, manifest = _read_packet_manifest(run_dir, manifest_relative)
        errors: list[str] = []
        packet_dir = manifest_path.parent
        is_scientific = manifest.get("packet_kind") == "scientific"
        for root in manifest["source_roots"]:
            if not isinstance(root, dict):
                errors.append("审查包源树条目不是对象")
                continue
            source_relative = root.get("source")
            packet_relative = root.get("packet")
            expected_hash = root.get("sha256")
            if not all(
                isinstance(item, str) and item
                for item in (source_relative, packet_relative, expected_hash)
            ):
                errors.append("审查包源树条目缺少路径或哈希")
                continue
            source = _source_root(run_dir, source_relative)
            packet_source = _safe_packet_path(packet_dir, packet_relative)
            # 验证时使用包副本哈希（构建时已记录中性化后的哈希）
            if source is None:
                errors.append(f"原始审查输入已缺失: {source_relative}")
            if not packet_source.exists() or _packet_tree_hash(
                packet_source,
                exclude_visualization_scripts=source_relative == "code",
                exclude_quality_labels=False,
            ) != expected_hash:
                errors.append(f"冻结审查副本已变化: {packet_relative}")
            if source is not None:
                filter_labels = is_scientific and _source_is_candidate_results(source_relative)
                current_files = {
                    relative_inside(run_dir, path).as_posix()
                    for path in _packet_files(
                        source,
                        exclude_visualization_scripts=source_relative == "code",
                        exclude_quality_labels=filter_labels,
                    )
                }
                recorded_files = {
                    item.get("source")
                    for item in manifest["files"]
                    if isinstance(item, dict)
                    and isinstance(item.get("source"), str)
                    and (
                        item["source"] == source_relative
                        or item["source"].startswith(source_relative.rstrip("/") + "/")
                    )
                }
                if current_files != recorded_files:
                    added = sorted(current_files - recorded_files)
                    removed = sorted(recorded_files - current_files)
                    if added:
                        errors.append("审查后新增源文件: " + ", ".join(added))
                    if removed:
                        errors.append("审查后删除或改名源文件: " + ", ".join(removed))
        # ── 逐文件验证：包文件哈希匹配；对于中性化源文件，重新中性化并比较 ──
        for item in manifest["files"]:
            if not isinstance(item, dict):
                errors.append("审查包文件条目不是对象")
                continue
            source_relative = item.get("source", "")
            packet_relative = item.get("packet", "")
            expected_hash = item.get("sha256")
            if not all(isinstance(v, str) and v for v in (packet_relative, expected_hash)):
                errors.append("审查包文件条目缺少路径或哈希")
                continue
            try:
                packet_file = _safe_packet_path(packet_dir, packet_relative)
                if not packet_file.is_file():
                    errors.append(f"冻结审查文件缺失: {packet_relative}")
                    continue
                packet_hash = sha256_file(packet_file)
                if packet_hash != expected_hash:
                    errors.append(f"冻结审查文件已变化: {packet_relative}")
                # 中性化源文件：重新中性化当前源并与冻结副本比较
                if (
                    source_relative
                    and Path(source_relative).suffix.lower() == ".json"
                    and _source_is_candidate_results(_infer_source_root(source_relative))
                ):
                    source_file = _safe_run_path(run_dir, source_relative)
                    if not source_file.is_file():
                        errors.append(f"候选源文件已缺失: {source_relative}")
                    else:
                        import json as _json2

                        # 在内存中重新中性化当前源并计算哈希
                        try:
                            source_data = _json2.loads(
                                source_file.read_text(encoding="utf-8")
                            )
                        except (OSError, ValueError):
                            errors.append(f"候选源文件不可读: {source_relative}")
                            continue
                        neutralized = _neutralize_value(source_data)
                        neutralized_bytes = _json2.dumps(
                            neutralized, ensure_ascii=False, indent=2
                        ).encode("utf-8")
                        current_neutralized_hash = hashlib.sha256(
                            neutralized_bytes
                        ).hexdigest()
                        if current_neutralized_hash != expected_hash:
                            errors.append(
                                f"候选结果已变化（重新中性化后哈希不匹配）: "
                                f"{source_relative}"
                            )
                # 非中性化源文件：直接比较哈希
                elif source_relative:
                    source = _safe_run_path(run_dir, source_relative)
                    if not source.is_file():
                        errors.append(f"原始审查文件已缺失: {source_relative}")
                    elif sha256_file(source) != expected_hash:
                        errors.append(f"原始审查文件已变化: {source_relative}")
            except ContractError as exc:
                errors.append(str(exc))
        if not manifest["files"]:
            errors.append("审查包文件清单为空")
        return {
            "success": not errors,
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
            "errors": errors,
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"success": False, "errors": [str(exc)]}


def _verify_language_evidence_source(
    run_dir: Path, ref: dict[str, Any], manifest_file: str
) -> None:
    """验证 language_evidence_ref 引用的源文件真实存在于审查包中。

    只校验文件存在性和原文片段是否可定位，不判断原文是否真正排除其他解释。
    """
    source_file = ref.get("source_file", "").strip()
    excerpt = ref.get("excerpt", "").strip()
    if not source_file:
        return
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "objective-semantics":
        raise ContractError("language_evidence 必须绑定当前 objective-semantics 包")
    match = next(
        (
            item for item in manifest["files"]
            if item.get("source") == source_file or item.get("packet") == source_file
        ),
        None,
    )
    if match is None:
        raise ContractError(
            f"language_evidence 引用的精确相对路径不在当前审查包中: {source_file}"
        )
    if ref.get("file_sha256") != match["sha256"]:
        raise ContractError("language_evidence 引用的题面文件哈希不匹配")
    candidate = _safe_packet_path(manifest_path.parent, match["packet"], must_exist=True)
    try:
        content = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ContractError(f"language_evidence 引用的题面文件无法读取: {source_file}") from exc
    if " ".join(excerpt.split()) not in " ".join(content.split()):
        raise ContractError(f"language_evidence 引用的原文片段未在 {source_file} 中找到")


def objective_semantics_review_required(run_dir: Path) -> bool:
    """判断当前生产运行是否具有需要独立解释的正式题面。"""
    state = read_simple_state(run_dir)
    problem_root = run_dir / "problem"
    problem_files_present = bool(
        problem_root.is_dir() and any(path.is_file() for path in problem_root.rglob("*"))
    )
    return bool(
        state.get("execution_mode") == "production"
        and (state.get("artifacts", {}).get("statement") or problem_files_present)
    )


# ── 聚合语义冲突对：在这两组中任取一对都会导致不同的优化方向与最终答案 ──
_SEMANTIC_CONFLICT_PAIRS: tuple[tuple[str, str], ...] = (
    ("sum_per_entity", "intersection_all"),
    ("sum_per_entity", "union_any"),
    ("multiobjective", "intersection_all"),
    ("multiobjective", "sum_per_entity"),
)


def _derive_semantic_conflict_fields(question: dict[str, Any]) -> dict[str, Any]:
    """从结构化 interpretations 推导语义冲突，不依赖自填的 selection_confidence。

    Returns:
        可合并回 question 的机器判定字段。
    """
    aggregations = sorted({
        item["aggregation"]
        for item in question["interpretations"]
    })
    distinct_count = len(aggregations)

    # 任一对冲突聚合 → changes_primary_result = true
    has_conflict = any(
        (a in aggregations and b in aggregations)
        for a, b in _SEMANTIC_CONFLICT_PAIRS
    )
    distinct = list(dict.fromkeys(aggregations))
    # language_evidence 必须绑定题面原文引用，不能只靠字段自报
    evidence_ref = question.get("language_evidence_ref", {})
    has_bound_evidence = (
        isinstance(evidence_ref, dict)
        and bool(evidence_ref.get("source_file", "").strip())
        and bool(evidence_ref.get("excerpt", "").strip())
    )
    language_resolves = (
        question.get("selection_basis") == "language_evidence" and has_bound_evidence
    )
    user_decision_required = (
        distinct_count >= 2
        and has_conflict
        and not language_resolves
    )
    return {
        "distinct_aggregations": distinct,
        "distinct_aggregation_count": distinct_count,
        "changes_primary_result": has_conflict,
        "changes_strategy": has_conflict,
        "language_uniquely_resolves": language_resolves,
        "user_decision_required": user_decision_required,
    }


def _validate_objective_assessment(
    run_dir: Path, payload: dict[str, Any], manifest_file: str
) -> dict[str, Any]:
    """校验独立任务逐问给出的目标解释、备选聚合和选择依据。"""
    _validate_document(
        payload,
        "objective_semantics_assessment",
        "独立目标语义评估",
    )
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"]:
        raise ContractError("独立目标语义评估 run_id 不匹配")
    required_questions = list(state["required_questions"])
    if not required_questions:
        raise ContractError("目标语义预审前必须登记全部必答问题")
    question_ids = [item["question_id"] for item in payload["questions"]]
    if len(question_ids) != len(set(question_ids)):
        raise ContractError("独立目标语义评估包含重复问题")
    if set(question_ids) != set(required_questions):
        raise ContractError("独立目标语义评估必须逐一覆盖全部必答问题")
    for question in payload["questions"]:
        objective_ids = [item["objective_id"] for item in question["interpretations"]]
        if len(objective_ids) != len(set(objective_ids)):
            raise ContractError(f"{question['question_id']} 包含重复 objective_id")
        selected = question["selected_objective_id"]
        if selected not in objective_ids:
            raise ContractError(f"{question['question_id']} 的主目标不在候选解释中")
        diagnostics = set(question["diagnostic_objective_ids"])
        if not diagnostics.issubset(objective_ids):
            raise ContractError(f"{question['question_id']} 的诊断指标不在候选解释中")
        if selected in diagnostics:
            raise ContractError(f"{question['question_id']} 的主目标不能同时标为诊断指标")
        if question["selection_confidence"] == "ambiguous":
            if len(objective_ids) < 2 or not question["ambiguity_note"].strip():
                raise ContractError(f"{question['question_id']} 的歧义必须保留至少两个解释并说明原因")
            if question["selection_basis"] == "language_evidence":
                raise ContractError(
                    f"{question['question_id']} 仍有歧义时必须记录用户裁决或显式建模假设"
                )
        # 当 AI 声称 language_evidence 且存在语义冲突时，不能仅靠字段自报。
        # 必须有绑定的题面引用（源文件、页码/行号、原文、如何排除其他解释）。
        if question["selection_basis"] == "language_evidence":
            has_conflict = (
                len(question.get("distinct_aggregations", [])) >= 2
                or len(
                    {
                        item["aggregation"]
                        for item in question["interpretations"]
                    }
                )
                >= 2
            )
            if has_conflict:
                ref = question.get("language_evidence_ref", {})
                if not isinstance(ref, dict):
                    raise ContractError(
                        f"{question['question_id']} 的 language_evidence_ref 必须是对象"
                    )
                missing_parts = []
                if not ref.get("source_file", "").strip():
                    missing_parts.append("source_file")
                if not ref.get("excerpt", "").strip():
                    missing_parts.append("excerpt")
                if not ref.get("file_sha256", "").strip():
                    missing_parts.append("file_sha256")
                if not ref.get("page_or_line", "").strip():
                    missing_parts.append("page_or_line")
                if not ref.get("how_it_excludes_alternatives", "").strip():
                    missing_parts.append("how_it_excludes_alternatives")
                if missing_parts:
                    raise ContractError(
                        f"{question['question_id']} 的 language_evidence 必须绑定题面原文引用，"
                        f"缺少: {', '.join(missing_parts)}"
                    )
                # 验证 source_file 真实存在于 objective-semantics 冻结包中
                _verify_language_evidence_source(run_dir, ref, manifest_file)
        if question["materiality"] == "high" and question["selection_confidence"] == "ambiguous":
            if question["selection_basis"] != "user_decision":
                raise ContractError(
                    f"{question['question_id']} 的高影响歧义必须由真实用户裁决，不能用建模假设自行放行"
                )
            if not question["human_confirmation_required"]:
                raise ContractError(f"{question['question_id']} 的高影响歧义必须要求人工确认")

        # ── 结构判定：当同一问题存在多个实质不同的聚合方式时，不能由 AI 自行填写
        # selection_confidence 绕过。必须按题面语言和聚合语义机器判定是否需要用户裁决。 ──
        machine = _derive_semantic_conflict_fields(question)
        question.update(machine)
        if machine["user_decision_required"]:
            if question["selection_basis"] != "user_decision":
                raise ContractError(
                    f"{question['question_id']} 存在 {machine['distinct_aggregation_count']} "
                    f"种实质不同的聚合语义（{', '.join(machine['distinct_aggregations'])}），"
                    f"会改变最终结果 ({machine['changes_primary_result']})，"
                    f"题面语言不能唯一排除 ({not machine['language_uniquely_resolves']})，"
                    f"必须由真实用户裁决，不能用 selection_confidence="
                    f"{question['selection_confidence']!r} 绕过"
                )
            if not question["human_confirmation_required"]:
                raise ContractError(
                    f"{question['question_id']} 的结构语义冲突要求 human_confirmation_required=true"
                )
    return payload


def _validate_question_reviews(
    run_dir: Path, question_reviews: list[dict[str, Any]] | None
) -> list[dict[str, Any]] | None:
    """校验逐问审查结论覆盖全部必答问题，且每个结论自洽。

    Returns:
        规范化后的逐问审查列表。

    Raises:
        ContractError: 生产模式下 question_reviews 为 None，或覆盖/自洽性不合法。
    """
    if question_reviews is None:
        # 兼容不含必答问题的运行（如纯探索、技能学习、无题面运行）
        state = read_simple_state(run_dir)
        if state.get("required_questions"):
            raise ContractError(
                "生产模式下逐问审查 (question_reviews) 必须覆盖全部必答问题，不能省略。"
            )
        return None
    if not isinstance(question_reviews, list):
        raise ContractError("question_reviews 必须是列表")
    state = read_simple_state(run_dir)
    required = set(state["required_questions"])
    covered = {item["question_id"] for item in question_reviews}
    if covered != required:
        missing = required - covered
        extra = covered - required
        parts = []
        if missing:
            parts.append("缺少必答问题: " + ", ".join(sorted(missing)))
        if extra:
            parts.append("含非必答问题: " + ", ".join(sorted(extra)))
        raise ContractError("逐问审查必须覆盖全部必答问题且不引入无关问题: " + "; ".join(parts))
    for item in question_reviews:
        if item["verdict"] not in _VERDICTS:
            raise ContractError(f"{item['question_id']} verdict 不合法: {item['verdict']}")
        if item["competition_strength"] not in {"weak", "qualified", "strong", "unknown"}:
            raise ContractError(
                f"{item['question_id']} competition_strength 不合法: {item['competition_strength']}"
            )
    return [
        {
            "question_id": item["question_id"],
            "verdict": item["verdict"],
            "competition_strength": item["competition_strength"],
            "evidence_ids": list(dict.fromkeys(item.get("evidence_ids", []))),
            "blocking_findings": list(dict.fromkeys(item.get("blocking_findings", []))),
        }
        for item in question_reviews
    ]


def _selected_objectives_sha256(assessment: dict[str, Any]) -> str:
    """稳定绑定逐问主目标，避免只改选择字段却复用旧人工裁决。"""
    selected = {
        question["question_id"]: question["selected_objective_id"]
        for question in assessment["questions"]
    }
    return sha256_bytes(json_bytes(selected))


def _human_ambiguity_binding(run_dir: Path, assessment: dict[str, Any]) -> dict[str, str] | None:
    """核验高影响歧义的人工原话与目标选择逐项一致。

    触发条件现在包括两套机制：
    1. 自填的高影响 + 显式 ambiguous（原有逻辑，保留兼容）；
    2. 机器派生的语义冲突（user_decision_required=true），不再依赖 AI 自评。
    """
    required = {
        question["question_id"]: question["selected_objective_id"]
        for question in assessment["questions"]
        if (
            question["materiality"] == "high"
            and question["selection_confidence"] == "ambiguous"
        )
        or question.get("user_decision_required", False)
    }
    if not required:
        return None
    path = _safe_run_path(run_dir, AMBIGUITY_DECISIONS_PATH.as_posix())
    decisions = load_json(path)
    _validate_document(decisions, "ambiguity_decisions", "高影响歧义人工裁决")
    if decisions["run_id"] != run_dir.name:
        raise ContractError("高影响歧义人工裁决 run_id 不匹配")
    by_question = {item["question_id"]: item for item in decisions["decisions"]}
    missing = sorted(set(required) - set(by_question))
    if missing:
        raise ContractError("高影响歧义缺少人工裁决: " + ", ".join(missing))
    mismatched = sorted(
        question_id
        for question_id, selected in required.items()
        if by_question[question_id]["selected_objective_id"] != selected
    )
    if mismatched:
        raise ContractError("人工裁决与选定主目标不一致: " + ", ".join(mismatched))
    return {
        "file": relative_inside(run_dir, path).as_posix(),
        "sha256": sha256_file(path),
    }


def _bound_review_file(run_dir: Path, relative: Path, *, suffix: str) -> dict[str, str]:
    """将审查任务写入的运行内文件绑定为路径与哈希。"""
    path = _safe_run_path(run_dir, relative.as_posix())
    path_relative = relative_inside(run_dir, path)
    if (
        not path_relative.parts
        or path_relative.parts[0] != REVIEW_ROOT.name
        or path_relative.parts[1:2] == ("packet",)
        or path.suffix.lower() != suffix
    ):
        raise ContractError(f"独立审查文件必须位于 review/ 下且扩展名为 {suffix}")
    return {"file": path_relative.as_posix(), "sha256": sha256_file(path)}


def _stale_results_for_objective_change(
    run_dir: Path, question_bindings: dict[str, str]
) -> None:
    """目标语义变化后精确失效绑定旧逐问哈希的产物。

    不直接修改结果 JSON 内容（那可能触发额外的 Schema 校验），
    而是将未绑定新目标哈希的 current 结果标记为 superseded。
    同时将质量和图表标记为失效。
    """
    # 1. 结果索引
    affected_questions: set[str] = set()
    affected_results: set[str] = set()
    try:
        index = read_result_index(run_dir)
    except (ContractError, OSError):
        index = None
    if index is not None:
        dirty = False
        for item in index["results"]:
            if item.get("execution_mode") != "production" or item.get("status") != "current":
                continue
            qid = item.get("question_id")
            expected = question_bindings.get(qid)
            if expected is None or item.get("objective_semantics_sha256") == expected:
                continue
            scope = item.get("dependency_scope", "question")
            impacted = set(item.get("affected_question_ids", [qid]))
            if scope == "global":
                impacted = set(question_bindings)
            item["status"] = "superseded"
            affected_questions.update(impacted)
            affected_results.add(item["result_id"])
            dirty = True
        if dirty:
            atomic_json(run_dir / "results" / "index.json", index)

    # 2. 质量文档：paper_allowed 强制回退
    quality_path = run_dir / "results" / "quality.json"
    if quality_path.is_file():
        try:
            q = load_json(quality_path)
            stale = False
            current_objective_hashes = set(question_bindings.values())
            for item in q.get("assessments", []):
                objective_changed = (
                    isinstance(item.get("objective_semantics_sha256"), str)
                    and item["objective_semantics_sha256"] not in current_objective_hashes
                )
                if (
                    item.get("result_id") in affected_results or objective_changed
                ) and item.get("result_role") == "accepted":
                    item["result_role"] = "candidate"
                    item["paper_allowed"] = False
                    item.setdefault("reasons", []).append(
                        "objective_semantics_changed"
                    )
                    stale = True
            if stale:
                from shumozizi.core.io import atomic_json as _atomic

                _atomic(quality_path, q)
        except (OSError, ValueError):
            pass

    # 3. 图表索引：标记依赖旧目标或旧结果的图为 superseded
    fig_index_path = run_dir / "figures" / "index.json"
    if fig_index_path.is_file():
        try:
            fig_idx = load_json(fig_index_path)
            stale = False
            for item in fig_idx.get("figures", []):
                source_ids = set(item.get("source_result_ids", [item.get("result_id")]))
                qid = item.get("question_id")
                expected = question_bindings.get(qid)
                objective_changed = bool(
                    expected
                    and item.get("objective_semantics_sha256") != expected
                )
                if source_ids & affected_results or objective_changed:
                    item["status"] = "superseded"
                    item["superseded_reason"] = "objective_semantics_changed"
                    stale = True
            if stale:
                from shumozizi.core.io import atomic_json as _atomic

                _atomic(fig_index_path, fig_idx)
        except (OSError, ValueError):
            pass

    # 结果索引损坏也不能阻止按逐问目标哈希继续失效带直接绑定的图。
    if index is None and fig_index_path.is_file():
        try:
            fig_idx = load_json(fig_index_path)
            dirty = False
            for item in fig_idx.get("figures", []):
                qid = item.get("question_id")
                expected = question_bindings.get(qid)
                if expected and item.get("objective_semantics_sha256") != expected:
                    item["status"] = "superseded"
                    item["superseded_reason"] = "objective_semantics_changed"
                    dirty = True
            if dirty:
                atomic_json(fig_index_path, fig_idx)
        except (OSError, ValueError):
            pass


def import_objective_semantics_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    task_receipt_file: str,
    assessment_file: Path = OBJECTIVE_SEMANTICS_ASSESSMENT_PATH,
    report_file: Path = OBJECTIVE_SEMANTICS_REPORT_PATH,
) -> dict[str, Any]:
    """绑定只读题面的独立目标语义预审，并冻结实验必须消费的主目标。"""
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("目标语义预审 verdict 或严重性不合法")
    if verdict == "pass" and highest_severity in {"P0", "P1"}:
        raise ContractError("目标语义预审含 P0/P1 时不能导入为 pass")
    if read_simple_state(run_dir)["phase"] == "complete":
        raise ContractError("已完成运行不能覆盖目标语义预审；请新建修订运行")
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "objective-semantics":
        raise ContractError("目标语义预审必须绑定 objective-semantics 审查包")
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("目标语义预审包已失效: " + "；".join(packet["errors"]))
    assessment_path = _safe_run_path(run_dir, assessment_file.as_posix())
    assessment = load_json(assessment_path)
    if not isinstance(assessment, dict):
        raise ContractError("独立目标语义评估必须是 JSON 对象")
    _validate_objective_assessment(run_dir, assessment, manifest_file)
    # 将机器派生字段（distinct_aggregations 等）持久化回评估文件，
    # 让下游消费者无需重复推导即可统一读取语义冲突判定。
    atomic_json(assessment_path, assessment)
    if not reviewer_thread_id.strip():
        raise ContractError("目标语义预审必须记录新对话 thread_id")
    ambiguity_decisions = _human_ambiguity_binding(run_dir, assessment)
    decisions_payload = None
    if ambiguity_decisions is not None:
        decisions_payload = load_json(run_dir / ambiguity_decisions["file"])
    question_bindings = build_question_objective_bindings(assessment, decisions_payload)
    report_binding = _review_report(run_dir, report_file)
    packet_task_binding = {
        "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
    }
    task_reference, _ = _review_task_reference(
        run_dir,
        receipt_file=task_receipt_file,
        task_type="objective_semantics",
        report_file=report_binding["file"],
        packet=packet_task_binding,
        reviewer_thread_id=reviewer_thread_id,
    )
    receipt = {
        "schema_name": "objective_semantics_review",
        "schema_version": "1.1",
        "run_id": run_dir.name,
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": {
            "file": relative_inside(run_dir, manifest_path).as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "assessment": _bound_review_file(run_dir, assessment_file, suffix=".json"),
        "selected_objectives_sha256": _selected_objectives_sha256(assessment),
        "question_bindings": question_bindings,
        "report": report_binding,
        "task_receipt": task_reference,
        "reviewer": {"thread_id": reviewer_thread_id},
        "reviewed_at": utc_now(),
    }
    if ambiguity_decisions is not None:
        receipt["ambiguity_decisions"] = ambiguity_decisions
    _validate_document(receipt, "objective_semantics_review", "目标语义预审收据")
    atomic_json(run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH, receipt)
    summary_path = run_dir / SUMMARY_PATH
    if summary_path.is_file():
        # 目标函数或聚合口径一旦重审，旧实验、论文和终审结论都失去共同前提。
        summary = read_review_summary(run_dir)
        summary["scientific_review"]["verdict"] = "revoked"
        summary["paper_blind_review"] = None
        summary["final_audit"] = None
        summary["updated_at"] = utc_now()
        _require_summary(summary)
        atomic_json(summary_path, summary)
    # 使所有绑定旧目标语义的结果 stale，并标记质量/图/Excel 必须重跑。
    _stale_results_for_objective_change(run_dir, question_bindings)
    # 目标改变后状态强制回退到 analysis，不能在旧结果上直接产出论文。
    update_simple_state(run_dir, phase="analysis")
    return receipt


def objective_semantics_review_status(run_dir: Path) -> dict[str, Any]:
    """复验题面、独立目标解释、选择结果和报告均未漂移。"""
    if not objective_semantics_review_required(run_dir):
        return {"allowed": True, "required": False, "reason": "当前运行没有登记正式题面"}
    try:
        receipt = load_json(run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH)
        if not isinstance(receipt, dict):
            raise ContractError("目标语义预审收据必须是 JSON 对象")
        _validate_document(receipt, "objective_semantics_review", "目标语义预审收据")
        if receipt.get("schema_version") != "1.1":
            raise ContractError("旧目标语义预审缺少真实任务回执，不能用于当前生产放行")
        if receipt["run_id"] != run_dir.name:
            raise ContractError("目标语义预审收据 run_id 不匹配")
        packet = verify_review_packet(run_dir, receipt["packet"]["file"])
        if not packet["success"]:
            raise ContractError("目标语义预审包已失效: " + "；".join(packet["errors"]))
        if packet["manifest_sha256"] != receipt["packet"]["sha256"]:
            raise ContractError("目标语义预审包清单哈希已变化")
        assessment_path = _safe_run_path(run_dir, receipt["assessment"]["file"])
        if sha256_file(assessment_path) != receipt["assessment"]["sha256"]:
            raise ContractError("目标语义评估已变化")
        assessment = load_json(assessment_path)
        if not isinstance(assessment, dict):
            raise ContractError("独立目标语义评估必须是 JSON 对象")
        _validate_objective_assessment(run_dir, assessment, receipt["packet"]["file"])
        if _selected_objectives_sha256(assessment) != receipt["selected_objectives_sha256"]:
            raise ContractError("逐问选定目标已变化")
        ambiguity_decisions = _human_ambiguity_binding(run_dir, assessment)
        if ambiguity_decisions != receipt.get("ambiguity_decisions"):
            raise ContractError("高影响歧义人工裁决已变化或缺失")
        decisions_payload = None
        if ambiguity_decisions is not None:
            decisions_payload = load_json(run_dir / ambiguity_decisions["file"])
        if build_question_objective_bindings(assessment, decisions_payload) != receipt["question_bindings"]:
            raise ContractError("逐问目标语义绑定已变化")
        report_path = _safe_run_path(run_dir, receipt["report"]["file"])
        if sha256_file(report_path) != receipt["report"]["sha256"]:
            raise ContractError("目标语义预审报告已变化")
        task_reference = receipt["task_receipt"]
        task_path = _safe_run_path(run_dir, task_reference["file"])
        if sha256_file(task_path) != task_reference["sha256"]:
            raise ContractError("目标语义预审任务回执已变化")
        from shumozizi.simple.review_tasks import validate_review_task_receipt

        task = validate_review_task_receipt(
            run_dir,
            task_reference["file"],
            expected_type="objective_semantics",
            expected_report=receipt["report"]["file"],
            expected_input_bindings={
                "packet": {
                    "manifest_file": receipt["packet"]["file"],
                    "manifest_sha256": receipt["packet"]["sha256"],
                }
            },
        )
        if (
            task["task_id"] != task_reference["task_id"]
            or task["thread_id"] != receipt["reviewer"]["thread_id"]
        ):
            raise ContractError("目标语义预审任务身份不一致")
        allowed = bool(
            receipt["verdict"] == "pass"
            and receipt["highest_severity"] not in {"P0", "P1"}
        )
        return {
            "allowed": allowed,
            "required": True,
            "review": receipt,
            "assessment": assessment,
            "reason": "" if allowed else "目标语义预审未通过",
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "required": True, "reason": str(exc)}


def require_objective_semantics_review(run_dir: Path) -> None:
    """要求实验前已有只读题面的独立目标语义结论。"""
    status = objective_semantics_review_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入能力路由：独立目标语义预审未通过或已失效: " + status["reason"])


def read_review_summary(run_dir: Path) -> dict[str, Any]:
    """读取当前独立审查摘要。"""
    payload = load_json(run_dir / SUMMARY_PATH)
    _require_summary(payload)
    if payload["run_id"] != run_dir.name:
        raise ContractError("审查摘要 run_id 不匹配")
    return payload


def _reviewer_scientific(thread_id: str) -> dict[str, Any]:
    """记录由协调层负责核验的新科学审查对话标识。"""
    if not thread_id.strip():
        raise ContractError("独立科学审查必须记录新对话 thread_id")
    return {"thread_id": thread_id}


def _reviewer_paper(thread_id: str) -> dict[str, Any]:
    """记录由协调层负责核验的独立 PDF 盲审对话标识。"""
    if not thread_id.strip():
        raise ContractError("独立盲审必须记录新对话 thread_id")
    return {"thread_id": thread_id}


def _reviewer_final(thread_id: str) -> dict[str, Any]:
    """记录最终交付审核使用的第三个独立对话标识。"""
    if not thread_id.strip():
        raise ContractError("最终交付审核必须记录新对话 thread_id")
    return {"thread_id": thread_id}


def _require_competition_strength_evidence(
    competition_strength: str,
    artifacts: dict[str, Any],
    evidence_assessment: dict[str, Any],
    run_dir: Path,
    semantics: dict[str, Any],
    question_reviews: list[dict[str, Any]] | None = None,
) -> None:
    """阻止 CLI 仅靠一个标签把科学结果抬成可竞赛提交。"""
    if competition_strength not in {"qualified", "strong"}:
        return
    kinds = set(artifacts.get("evidence_kinds", []))
    has_independent_check = bool(kinds & {"independent-recompute", "alternative-formula"})
    has_adversarial_check = bool(
        kinds & {"counterexample", "small-enumeration", "search-challenge", "property-test"}
    )
    if not has_independent_check or not has_adversarial_check:
        raise ContractError(
            "qualified/strong 需要至少一项独立复算或替代公式，且需要一项反例、枚举、挑战或性质测试的真实收据"
        )
    if not evidence_assessment["promotion_allowed"]:
        raise ContractError(
            "qualified/strong 与红队证据结论冲突: "
            + "；".join(evidence_assessment["promotion_blockers"])
        )
    route = require_capability_route(run_dir)
    if "geometry_kinematics" in route["problem_families"] and (
        "geometry-continuous-validation" not in kinds
    ):
        raise ContractError(
            "几何/运动题的 qualified/strong 需要 geometry-continuous-validation，"
            "随机内部采样不能替代连续边界证明"
        )
    # ── 逐问证据绑定：qualified/strong 的每个问题必须有独立证据 ──
    verification = verify_red_team_artifacts(run_dir)
    semantic_evidence = verification.get("semantic_evidence", [])
    if question_reviews is not None:
        evidence_by_question: dict[str, dict[str, set[str]]] = {}
        for kind, evidence in semantic_evidence:
            qid = evidence.get("question_id")
            if not qid:
                continue
            groups = evidence_by_question.setdefault(
                qid, {"independent": set(), "adversarial": set()}
            )
            if kind in {"independent-recompute", "alternative-formula"}:
                groups["independent"].add(kind)
            elif kind in {
                "counterexample", "small-enumeration", "search-challenge",
                "property-test", "action-activation-challenge",
                "fixed-action-utilization",
            }:
                groups["adversarial"].add(kind)
        for item in question_reviews:
            if item["competition_strength"] not in {"qualified", "strong"}:
                continue
            qid = item["question_id"]
            ev = evidence_by_question.get(qid, {})
            if not ev.get("independent"):
                raise ContractError(
                    f"{qid} 标记为 {item['competition_strength']}，"
                    f"但没有属于该问题的独立复算或替代公式证据——"
                    f"Q1 的独立验证不能替其他问题背书"
                )
            if not ev.get("adversarial"):
                raise ContractError(
                    f"{qid} 缺少属于自己的对抗性证据"
                    f"（搜索挑战/消融/性质测试），不能标记为 qualified/strong"
                )

    required_actions = {
        question["question_id"]: question["decision_space"]["allowed_action_count"]
        for question in semantics.get("assessment", {}).get("questions", [])
        if question.get("decision_space", {}).get("action_cardinality") == "variable"
    }
    if required_actions:
        verification = verify_red_team_artifacts(run_dir)
        action_evidence = {
            evidence["question_id"]: evidence
            for kind, evidence in verification.get("semantic_evidence", [])
            if kind == "action-activation-challenge"
        }
        missing = sorted(set(required_actions) - set(action_evidence))
        if missing:
            raise ContractError(
                "可变动作数量问题缺少 action-activation-challenge: "
                + ", ".join(missing)
            )
        mismatched = sorted(
            question_id
            for question_id, allowed_count in required_actions.items()
            if action_evidence[question_id]["allowed_action_count"] != allowed_count
        )
        if mismatched:
            raise ContractError(
                "动作激活挑战未覆盖题面声明的完整动作数量: "
                + ", ".join(mismatched)
            )
    # ── 固定多动作利用检查：删除每个必要动作，验证边际贡献是否正 ──
    required_fixed = {
        question["question_id"]: question["decision_space"]["allowed_action_count"]
        for question in semantics.get("assessment", {}).get("questions", [])
        if question.get("decision_space", {}).get("action_cardinality") == "fixed"
        and (question["decision_space"].get("allowed_action_count") or 0) >= 2
    }
    if required_fixed:
        verification = verify_red_team_artifacts(run_dir)
        fixed_evidence = {
            evidence["question_id"]: evidence
            for kind, evidence in verification.get("semantic_evidence", [])
            if kind == "fixed-action-utilization"
        }
        missing = sorted(set(required_fixed) - set(fixed_evidence))
        if missing:
            raise ContractError(
                "固定多动作问题缺少 fixed-action-utilization 消融证据: "
                + ", ".join(missing)
            )
        for question_id, required_count in required_fixed.items():
            evidence = fixed_evidence[question_id]
            gains = [float(item) for item in evidence.get("marginal_gains", [])]
            if len(gains) != required_count:
                raise ContractError(
                    f"{question_id} fixed-action-utilization 消融动作数 "
                    f"({len(gains)}) 与题面要求 ({required_count}) 不一致"
                )
            tolerance = float(evidence.get("tolerance", 1e-12))
            zero_gain = [i + 1 for i, g in enumerate(gains) if g <= tolerance]
            if evidence.get("all_required_actions_material") and zero_gain:
                raise ContractError(
                    f"{question_id} 声称 all_required_actions_material=true，"
                    f"但第 {zero_gain} 枚动作边际贡献 ≤ {tolerance}"
                )
            if zero_gain:
                raise ContractError(
                    f"{question_id} 第 {zero_gain} 枚动作边际贡献 ≤ {tolerance}，"
                    f"不能标记为 qualified/strong；需重搜或降级为 weak"
            )


# ── 红队覆盖声明：自由审核 + 动态风险差集 + 专项追问闭环 ──
#
# 设计要点（防止 general-coverage 自报退化）：
# 1. required_risks 由协调层从能力路由、目标语义、decision_space 和关键主张
#    动态派生；自由审核 AI 不读取该集合，只产出自由报告。
# 2. 独立覆盖提取器读取当前 SCIENTIFIC_RED_TEAM.md，产出 covered_risks 映射，
#    每项必须绑定当前报告 SHA 和真实标题锚点或行范围。
# 3. 协调层比较 required_risks 与 covered_risks：缺失或 insufficient 的风险
#    必须有 closed 的专项 follow_up（真实任务回执 + 专项报告）才放行。
# 4. covered_risks 只能引用动态派生的 risk_id；general-coverage 或任意未知
#    risk_id 一律拒绝；未预设的新风险放入 additional_findings，不替代具体风险。

_COVERAGE_DECLARATION_PATH = REVIEW_ROOT / "coverage" / "scientific.json"
_REQUIRED_RISKS_PATH = REVIEW_ROOT / "required_risks.json"
_PAPER_COVERAGE_DECLARATION_PATH = REVIEW_ROOT / "coverage" / "paper_blind.json"
_PAPER_REQUIRED_RISKS_PATH = REVIEW_ROOT / "paper_required_risks.json"
_COVERAGE_SATISFIED = {"sufficient", "not_applicable"}
_COVERAGE_NEEDS_FOLLOW_UP = {
    "insufficient",
    "partial",
    "uncovered",
    "requires_independent_verification",
}


def _derive_required_risks(
    route: dict[str, Any],
    assessment: dict[str, Any] | None,
) -> dict[str, str]:
    """兼容入口：只派生不依赖方法画像的题型与决策空间风险。"""
    return derive_required_review_risks(route, assessment, None, None, [])


def _declared_bool(properties: dict[str, Any], name: str) -> bool:
    """读取方法画像中的布尔或 declared 布尔属性。"""
    value = properties.get(name)
    if isinstance(value, bool):
        return value
    return bool(value.get("value")) if isinstance(value, dict) else False


def derive_general_risks(route: dict[str, Any]) -> dict[str, str]:
    """派生题型固有、与具体算法实现无关的风险。"""
    families = set(route.get("problem_families", []))
    risks: dict[str, str] = {}
    if "mechanism_dynamics" in families:
        risks["dynamics.dimension_consistency"] = "机理方程的量纲与状态定义是否一致"
    if "network_system" in families:
        risks["network.flow_conservation"] = "网络流与节点守恒约束是否闭合"
    return risks


def derive_method_risks(method_profile: dict[str, Any] | None) -> dict[str, str]:
    """严格按实际方法属性派生专项风险。"""
    risks: dict[str, str] = {}
    rules = {
        "solver_properties": {
            "stochastic": ("optimization.multiseed", "随机求解的同预算多种子稳定性"),
            "local_search": ("optimization.multistart_or_landscape", "局部搜索的多起点或景观挑战"),
            "uses_proxy_objective": ("optimization.proxy_exact", "代理目标与精确目标的一致性"),
            "variable_dimension": ("optimization.dimension_coverage", "变维决策空间的维度覆盖"),
            "discrete_decisions": ("optimization.discrete_feasibility", "离散决策的可行性复验"),
            "exact_within_declared_space": ("optimization.scope_and_certificate", "精确性声明的空间边界与证书"),
        },
        "data_properties": {
            "time_ordered": ("prediction.temporal_leakage", "时间顺序数据的未来信息泄漏"),
            "feature_selection_used": ("prediction.selection_leakage", "特征选择在验证折外执行导致的泄漏"),
            "class_imbalance": ("prediction.imbalance_metrics", "类别不平衡下指标与阈值适用性"),
            "repeated_measurements": ("prediction.group_leakage", "重复测量跨训练验证组泄漏"),
        },
        "mathematical_properties": {
            "continuous_geometry": ("geometry.continuous_boundary", "连续几何边界和临界事件"),
            "finite_segment_logic": ("geometry.finite_segment_endpoint", "有限线段端点、切线与退化情形"),
            "coordinate_transform": ("geometry.coordinate_consistency", "坐标变换方向、原点和单位一致性"),
            "critical_event_detection": ("geometry.root_isolation", "临界事件根隔离与漏根风险"),
            "differential_equation": ("dynamics.step_convergence", "微分方程步长与积分器收敛"),
            "conservation_law": ("dynamics.conservation", "守恒量数值漂移"),
            "network_structure": ("network.topology_perturbation", "拓扑扰动下结论稳定性"),
            "ranking_weights": ("evaluation.weight_sensitivity", "权重扰动下排名稳定性"),
        },
    }
    for question in (method_profile or {}).get("questions", []):
        qid = question.get("question_id", "unknown")
        for group, group_rules in rules.items():
            properties = question.get(group, {})
            for field, (prefix, reason) in group_rules.items():
                if _declared_bool(properties, field):
                    risks[f"{prefix}.{qid}"] = f"{qid}: {reason}"
        data = question.get("data_properties", {})
        if _declared_bool(data, "time_ordered"):
            risks[f"prediction.time_split.{qid}"] = f"{qid}: 时间顺序切分或滚动验证"
        if _declared_bool(data, "class_imbalance"):
            risks[f"prediction.calibration.{qid}"] = f"{qid}: 概率校准与决策阈值"
        if _declared_bool(data, "repeated_measurements"):
            risks[f"prediction.correlation_structure.{qid}"] = f"{qid}: 组内相关结构"
        math_props = question.get("mathematical_properties", {})
        if _declared_bool(math_props, "differential_equation"):
            risks[f"dynamics.integrator_crosscheck.{qid}"] = f"{qid}: 独立积分器交叉复验"
        if _declared_bool(math_props, "network_structure"):
            risks[f"network.scale_robustness.{qid}"] = f"{qid}: 网络规模变化稳健性"
        if _declared_bool(math_props, "ranking_weights"):
            risks[f"evaluation.ranking_stability.{qid}"] = f"{qid}: 排名区间与翻转点"
    return risks


def derive_decision_space_risks(assessment: dict[str, Any] | None) -> dict[str, str]:
    """从已确认目标的决策空间派生动作完整性风险。"""
    risks: dict[str, str] = {}
    for question in (assessment or {}).get("questions", []):
        decision = question.get("decision_space", {})
        qid = question.get("question_id", "unknown")
        if decision.get("action_cardinality") == "variable":
            risks[f"decision_space.activation.{qid}"] = f"{qid}: 可变动作数量的完整激活挑战"
        elif decision.get("action_cardinality") == "fixed" and decision.get("allowed_action_count", 0) >= 2:
            risks[f"decision_space.fixed_ablation.{qid}"] = f"{qid}: 固定多动作的逐一消融"
    return risks


def derive_claim_risks(critical_claims: dict[str, Any] | None) -> dict[str, str]:
    """从高价值主张类型派生证明责任。"""
    mapping = {
        "global_optimality": ("claim.global_optimality_certificate", "全局最优性证书或反例挑战"),
        "comparative_superiority": ("claim.equal_budget_baseline", "同预算基线比较"),
        "robustness": ("claim.perturbation_robustness", "扰动稳健性"),
        "all_actions_material": ("claim.deletion_ablation", "逐动作删除消融"),
        "generalization": ("claim.holdout_or_ood", "留出或分布外验证"),
        "mechanism_explanation": ("claim.mechanism_counterfactual", "机理反事实"),
        "parameter_insensitivity": ("claim.sensitivity_analysis", "参数敏感性"),
        "result_correctness": ("claim.independent_recompute", "独立重算"),
    }
    risks: dict[str, str] = {}
    for claim in (critical_claims or {}).get("claims", []):
        rule = mapping.get(claim.get("claim_type"))
        if rule:
            prefix, reason = rule
            risks[f"{prefix}.{claim['claim_id']}"] = f"{claim['question_id']}: {reason}"
    return risks


def derive_required_review_risks(
    route: dict[str, Any],
    assessment: dict[str, Any] | None,
    method_profile: dict[str, Any] | None,
    critical_claims: dict[str, Any] | None,
    execution_receipts: list[dict[str, Any]],
) -> dict[str, str]:
    """合并路线、目标、实际方法、关键主张和执行收据的动态风险。"""
    risks: dict[str, str] = {}
    for source in (
        derive_general_risks(route),
        derive_method_risks(method_profile),
        derive_decision_space_risks(assessment),
        derive_claim_risks(critical_claims),
    ):
        risks.update(source)
    profile_questions = {
        item.get("question_id"): item
        for item in (method_profile or {}).get("questions", [])
    }
    receipts_by_question: dict[str, list[dict[str, Any]]] = {}
    for receipt in execution_receipts:
        qid = receipt.get("question_id")
        if isinstance(qid, str):
            receipts_by_question.setdefault(qid, []).append(receipt)
    for qid, question in profile_questions.items():
        if not isinstance(qid, str):
            continue
        if _declared_bool(question.get("solver_properties", {}), "uses_proxy_objective"):
            has_bound_scores = any(
                {"proxy_score", "exact_score"}.issubset(set(item.get("metrics", {})))
                for item in receipts_by_question.get(qid, [])
            )
            if not has_bound_scores:
                risks[f"optimization.proxy_receipt_integrity.{qid}"] = (
                    f"{qid}: 代理目标声明缺少同一执行收据中的 proxy/exact 绑定"
                )
    return risks


def _route_required_risks(run_dir: Path) -> dict[str, str]:
    """在自由报告完成后生成并绑定本轮动态风险产物。"""
    from shumozizi.simple.critical_claims import read_critical_claims
    from shumozizi.simple.method_profile import read_method_profile
    from shumozizi.simple.objective_semantics import objective_semantics_digest

    report_path = run_dir / SCIENTIFIC_REPORT_PATH
    if not report_path.is_file():
        raise ContractError("必须先完成自由科学审核报告，再派生 required_risks")
    route = require_capability_route(run_dir)
    semantics = objective_semantics_review_status(run_dir)
    assessment = semantics.get("assessment") if semantics.get("required") else None
    profile = read_method_profile(run_dir)
    claims = read_critical_claims(run_dir)
    index = read_result_index(run_dir)
    risks = derive_required_review_risks(route, assessment, profile, claims, index["results"])
    route_path = run_dir / "state" / "capability-route.json"
    profile_path = run_dir / "analysis" / "method_profile.json"
    claims_path = run_dir / "analysis" / "critical_claims.json"
    payload = {
        "schema_name": "required_review_risks",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "source_bindings": {
            "route_sha256": sha256_file(route_path),
            "objective_semantics_sha256": objective_semantics_digest(run_dir),
            "method_profile_sha256": sha256_file(profile_path),
            "critical_claims_sha256": sha256_file(claims_path),
            "execution_receipts_sha256": sha256_file(run_dir / "results" / "index.json"),
        },
        "risks": [
            {"risk_id": risk_id, "reason": reason}
            for risk_id, reason in sorted(risks.items())
        ],
        "generated_at": utc_now(),
    }
    path = run_dir / _REQUIRED_RISKS_PATH
    if path.is_file():
        previous = load_json(path)
        if (
            previous.get("source_bindings") == payload["source_bindings"]
            and previous.get("risks") == payload["risks"]
        ):
            return risks
    atomic_json(path, payload)
    return risks


def _paper_required_risks(run_dir: Path, report_file: str) -> dict[str, str]:
    """在开放 PDF 盲审报告完成后派生论文专项风险。"""
    report_path = _safe_run_path(run_dir, report_file)
    if not report_path.is_file():
        raise ContractError("必须先完成开放 PDF 盲审报告，再派生论文风险")
    state = read_simple_state(run_dir)
    claims_path = run_dir / "analysis" / "critical_claims.json"
    argument_path = run_dir / "paper" / "argument_map.json"
    figures_path = run_dir / "figures" / "index.json"
    claims = load_json(claims_path)
    argument_map = load_json(argument_path)
    figures = load_json(figures_path)
    risks: dict[str, str] = {}
    for question_id in state.get("required_questions", []):
        risks[f"paper.question_closure.{question_id}"] = (
            f"{question_id}: 题目要求、模型、推导、结果和边界是否闭合"
        )
        risks[f"paper.model_rationale.{question_id}"] = (
            f"{question_id}: 模型选择是否有题意和数据依据"
        )
        risks[f"paper.direct_answer.{question_id}"] = (
            f"{question_id}: 是否给出可定位的直接答案"
        )
    for claim in claims.get("claims", []):
        risks[f"paper.claim_support.{claim['claim_id']}"] = (
            f"{claim['question_id']}: 主张是否由当前结果、验证和边界共同支撑"
        )
    for claim in argument_map.get("claims", []):
        risks[f"paper.result_explanation.{claim['claim_id']}"] = (
            f"{claim['question_id']}: 当前结果是否在正文中得到解释而非只被罗列"
        )
    for figure in figures.get("figures", []):
        if (
            figure.get("status") == "current"
            and figure.get("figure_stage", "publication") == "publication"
        ):
            risks[f"paper.figure_readability.{figure['figure_id']}"] = (
                f"{figure.get('question_id', 'global')}: 图形、图注和正文解释是否可读且一致"
            )
    risks["paper.source_appendix"] = "源码呈现与附件策略是否满足当前竞赛要求"
    risks["paper.competition_fit"] = (
        f"论文是否符合 {state.get('competition', '当前竞赛')} 的匿名与提交边界"
    )
    source_bindings = {
        "critical_claims_sha256": sha256_file(claims_path),
        "argument_map_sha256": sha256_file(argument_path),
        "publication_figures_sha256": sha256_file(figures_path),
        "paper_pdf_sha256": sha256_file(run_dir / "paper" / "final.pdf"),
        "competition_profile_sha256": sha256_bytes(
            json_bytes(
                {
                    "competition": state.get("competition"),
                    "required_questions": state.get("required_questions", []),
                }
            )
        ),
    }
    payload = {
        "schema_name": "required_review_risks",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "source_bindings": source_bindings,
        "risks": [
            {"risk_id": risk_id, "reason": reason}
            for risk_id, reason in sorted(risks.items())
        ],
        "generated_at": utc_now(),
    }
    path = run_dir / _PAPER_REQUIRED_RISKS_PATH
    if path.is_file():
        previous = load_json(path)
        if (
            previous.get("source_bindings") == payload["source_bindings"]
            and previous.get("risks") == payload["risks"]
        ):
            return risks
    atomic_json(path, payload)
    return risks


def generate_required_review_risks(
    run_dir: Path,
    *,
    scope: str = "scientific",
    report_file: str | None = None,
) -> dict[str, str]:
    """在开放审核报告完成后生成当前动态风险清单。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        scope: ``scientific`` 或 ``paper``。
        report_file: 论文开放盲审报告路径；科学审核使用固定报告路径。

    Returns:
        风险 ID 到派生原因的映射。

    Raises:
        ContractError: scope 不合法或开放报告尚未生成。
    """
    if scope == "scientific":
        return _route_required_risks(run_dir)
    if scope == "paper":
        return _paper_required_risks(
            run_dir,
            report_file or PAPER_BLIND_REPORT_PATH.as_posix(),
        )
    raise ContractError("coverage scope 必须是 scientific 或 paper")


def _report_heading_anchors(text: str) -> set[str]:
    """提取 Markdown 报告中的标题锚点（归一化后用于位置校验）。"""
    anchors: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                anchors.add(_normalize_anchor(title))
    return anchors


def _normalize_anchor(value: str) -> str:
    """归一化标题锚点：小写、去空白与连字符，便于稳健匹配。"""
    return re.sub(r"[\s\-_]+", "", value.strip().lower())


def _evidence_location_is_real(
    location: str, report_text: str, report_relative: str, anchors: set[str]
) -> bool:
    """校验 evidence_location 指向报告中真实存在的标题锚点或行范围。

    支持两种形式：
    - ``review/X.md#标题``：标题必须在报告中真实存在；
    - ``review/X.md:L10-L20``：行范围必须落在报告实际行数内。
    """
    if "#" in location:
        path_part, _, anchor = location.partition("#")
        if path_part and path_part != report_relative:
            return False
        return bool(anchor.strip()) and _normalize_anchor(anchor) in anchors
    match = re.search(r":L(\d+)(?:-L?(\d+))?$", location)
    if match:
        path_part = location[: match.start()]
        if path_part and path_part != report_relative:
            return False
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        total_lines = len(report_text.splitlines())
        return 1 <= start <= end <= total_lines
    return False


def _evaluate_coverage(
    declaration: dict[str, Any],
    required_risks: dict[str, str],
    report_text: str,
    report_relative: str,
) -> list[str]:
    """纯函数：在已知 required_risks 和报告内容下评估覆盖声明是否放行。

    不做 schema 结构校验（调用方已用 Draft202012Validator 校验），只做语义门：
    风险归属、位置真实性、差集覆盖、追问闭环。
    """
    errors: list[str] = []
    anchors = _report_heading_anchors(report_text)
    covered = declaration.get("covered_risks", [])
    follow_ups = {
        item["risk_id"]: item
        for item in declaration.get("follow_ups", [])
        if isinstance(item, dict) and isinstance(item.get("risk_id"), str)
    }

    seen: set[str] = set()
    covered_ok: set[str] = set()
    for item in covered:
        risk_id = item["risk_id"]
        conclusion = item["conclusion"]
        if risk_id in seen:
            errors.append(f"risk_id 重复: {risk_id}")
            continue
        seen.add(risk_id)
        # 4. 只接受动态派生的 risk_id；general-coverage / 未知 ID 一律拒绝
        if risk_id not in required_risks:
            errors.append(
                f"covered_risks 含未派生的 risk_id: {risk_id}；"
                "general-coverage 或任意 ID 不能替代具体动态风险，"
                "新风险应放入 additional_findings"
            )
            continue
        # 4. evidence_location 必须指向报告真实标题锚点或行范围
        if not _evidence_location_is_real(
            item["evidence_location"], report_text, report_relative, anchors
        ):
            errors.append(
                f"{risk_id}: evidence_location 未指向报告真实标题或行范围: "
                f"{item['evidence_location']}"
            )
            continue
        # 5/6. insufficient / requires_independent_verification 需要 closed 专项追问
        if conclusion in _COVERAGE_NEEDS_FOLLOW_UP:
            follow_up = follow_ups.get(risk_id)
            if follow_up is None:
                errors.append(
                    f"{risk_id}: conclusion={conclusion} 但缺少专项 follow_up"
                )
            elif follow_up.get("status") != "closed":
                errors.append(
                    f"{risk_id}: 专项 follow_up 未关闭（status="
                    f"{follow_up.get('status')}），不能放行"
                )
            else:
                covered_ok.add(risk_id)
        elif conclusion in _COVERAGE_SATISFIED:
            covered_ok.add(risk_id)

    for finding in declaration.get("additional_findings", []):
        severity = finding.get("severity")
        disposition = finding.get("disposition")
        if severity in {"P0", "P1"} or disposition == "blocking":
            errors.append(
                f"additional finding {finding.get('finding_id')} 为 "
                f"severity={severity}, disposition={disposition}，必须阻断并闭环"
            )

    # 5. required_risks 差集：任一未被充分覆盖（缺失或未闭合）即阻断
    uncovered = sorted(set(required_risks) - covered_ok)
    if uncovered:
        errors.append(
            "以下动态派生的高风险方向未被充分覆盖或专项追问未闭合: "
            + ", ".join(uncovered)
        )
    return errors


def _validate_coverage_declaration(
    run_dir: Path,
    declaration: dict[str, Any],
    *,
    expected_report_file: str,
    declaration_file: str,
    required_risks: dict[str, str],
    required_risks_file: Path,
    coverage_task_type: str,
    follow_up_task_type: str,
    expected_parent_task_id: str,
) -> list[str]:
    """校验覆盖声明：真实 schema 调用 + 报告绑定 + 动态差集 + 追问闭环。"""
    # 8. 真实调用 Schema（Draft202012Validator），不再手写字段检查
    schema_errors = validate_document(
        declaration, "red_team_coverage_declaration"
    )
    if schema_errors:
        return schema_errors

    errors: list[str] = []
    if declaration["run_id"] != run_dir.name:
        errors.append("覆盖声明 run_id 不匹配")

    review_file = declaration["review_file"]
    if Path(review_file).as_posix() != Path(expected_report_file).as_posix():
        errors.append("覆盖声明绑定的报告不是本次实际导入报告")
        return errors
    try:
        report_path = _safe_run_path(run_dir, review_file)
    except (ContractError, OSError, KeyError, ValueError):
        errors.append(f"review_file 不存在或越界: {review_file}")
        return errors
    if not report_path.is_file():
        errors.append(f"review_file 不存在: {review_file}")
        return errors

    report_text = report_path.read_text(encoding="utf-8")
    # 4. 覆盖必须绑定当前报告内容 SHA，报告变更即失效
    if sha256_file(report_path) != declaration["report_sha256"]:
        errors.append(
            "report_sha256 与当前报告不一致：覆盖提取所依据的报告已变化，"
            "需重新提取覆盖映射"
        )
        return errors

    risks_path = run_dir / required_risks_file
    if declaration["required_risks_file"] != required_risks_file.as_posix():
        errors.append(f"覆盖声明未绑定本轮 {required_risks_file.as_posix()}")
    if not risks_path.is_file() or declaration["required_risks_sha256"] != sha256_file(risks_path):
        errors.append("覆盖声明的 required_risks 哈希已失效")
        return errors

    from shumozizi.simple.review_tasks import validate_review_task_receipt

    coverage_inputs = {
        "report": {"file": review_file, "sha256": sha256_file(report_path)},
        "required_risks": {
            "file": required_risks_file.as_posix(),
            "sha256": sha256_file(risks_path),
        },
    }
    try:
        coverage_receipt = validate_review_task_receipt(
            run_dir,
            declaration["coverage_task_receipt"],
            expected_type=coverage_task_type,
            expected_report=declaration_file,
            expected_input_bindings=coverage_inputs,
            expected_parent_task_id=expected_parent_task_id,
        )
    except (ContractError, OSError, KeyError, ValueError) as exc:
        errors.append(str(exc))
        return errors

    # not_applicable 只能由协调层依据当前结构事实批准。
    for item in declaration.get("covered_risks", []):
        if item.get("conclusion") != "not_applicable":
            continue
        basis = item.get("basis")
        if not item.get("not_applicable_reason") or not isinstance(basis, dict):
            errors.append(f"{item.get('risk_id')}: not_applicable 缺少结构事实依据")
            continue
        try:
            basis_path = _safe_run_path(run_dir, basis["file"])
            fact: Any = load_json(basis_path)
            field = basis["field"].replace("[", ".").replace("]", "")
            for token in [part for part in field.split(".") if part]:
                if isinstance(fact, list):
                    if token.isdigit():
                        fact = fact[int(token)]
                    else:
                        fact = next(
                            item
                            for item in fact
                            if isinstance(item, dict)
                            and item.get("question_id") == token
                        )
                else:
                    fact = fact[token]
            if fact is not True and not (isinstance(fact, dict) and fact.get("value") is True):
                raise KeyError(field)
        except (ContractError, OSError, KeyError, IndexError, TypeError, ValueError):
            errors.append(f"{item.get('risk_id')}: not_applicable 依据不是当前可验证结构事实")

    for follow_up in declaration.get("follow_ups", []):
        report_file = follow_up.get("report_file", "")
        try:
            follow_report = _safe_run_path(run_dir, report_file)
            if sha256_file(follow_report) != follow_up.get("report_sha256"):
                raise ContractError("专项报告哈希不匹配")
            validate_review_task_receipt(
                run_dir,
                follow_up["task_receipt"],
                expected_type=follow_up_task_type,
                expected_report=report_file,
                expected_input_bindings={
                    **coverage_inputs,
                    "risk_id": follow_up["risk_id"],
                },
                expected_parent_task_id=coverage_receipt["task_id"],
            )
            if follow_up.get("status") != "closed" or not follow_up.get("resolution"):
                raise ContractError("专项追问没有 closed resolution")
        except (ContractError, OSError, KeyError, ValueError) as exc:
            errors.append(f"follow_up[{follow_up.get('risk_id')}] 无效: {exc}")
    report_relative = relative_inside(run_dir, report_path).as_posix()
    errors.extend(
        _evaluate_coverage(declaration, required_risks, report_text, report_relative)
    )
    return errors


def require_coverage_declaration_valid(
    run_dir: Path,
    *,
    expected_report_file: str = "review/SCIENTIFIC_RED_TEAM.md",
    scope: str = "scientific",
    expected_parent_task_id: str,
) -> dict[str, Any]:
    """要求科学红队输出覆盖声明，验证后返回声明内容。

    若覆盖声明缺失或无效，抛出 ContractError。
    """
    if scope == "scientific":
        declaration_path = _COVERAGE_DECLARATION_PATH
        required_risks_path = _REQUIRED_RISKS_PATH
        required_risks = _route_required_risks(run_dir)
        coverage_task_type = "coverage_extract"
        follow_up_task_type = "scientific_follow_up"
    elif scope == "paper":
        declaration_path = _PAPER_COVERAGE_DECLARATION_PATH
        required_risks_path = _PAPER_REQUIRED_RISKS_PATH
        required_risks = _paper_required_risks(run_dir, expected_report_file)
        coverage_task_type = "paper_coverage_extract"
        follow_up_task_type = "paper_follow_up"
    else:
        raise ContractError(f"未知覆盖范围: {scope}")
    path = run_dir / declaration_path
    if not path.is_file():
        raise ContractError(
            f"审核必须输出 {declaration_path.as_posix()}；"
            "该声明由独立覆盖提取器在自由报告完成后生成，"
            "把报告中的实际论证绑定到协调层动态派生的高风险方向，"
            "不能退化为 general-coverage 自报"
        )
    try:
        declaration = load_json(path)
    except (OSError, ValueError) as exc:
        raise ContractError(f"覆盖声明无法解析: {exc}") from exc
    errors = _validate_coverage_declaration(
        run_dir,
        declaration,
        expected_report_file=expected_report_file,
        declaration_file=declaration_path.as_posix(),
        required_risks=required_risks,
        required_risks_file=required_risks_path,
        coverage_task_type=coverage_task_type,
        follow_up_task_type=follow_up_task_type,
        expected_parent_task_id=expected_parent_task_id,
    )
    if errors:
        raise ContractError("红队覆盖声明无效: " + "; ".join(errors))
    return declaration



def _review_report(run_dir: Path, relative: Path) -> dict[str, str]:
    """绑定非空自由文本审查报告，而不把其压缩为固定检查表。"""
    report = _safe_run_path(run_dir, relative.as_posix())
    report_relative = relative_inside(run_dir, report)
    if (
        not report_relative.parts
        or report_relative.parts[0] != REVIEW_ROOT.name
        or report_relative.parts[1:2] == ("packet",)
        or report.suffix.lower() != ".md"
    ):
        raise ContractError("独立审查报告必须是 review/ 下、审查包外的 Markdown 文件")
    if report.stat().st_size < 32:
        raise ContractError("独立审查报告过短，缺少可复现判断")
    return {"file": report_relative.as_posix(), "sha256": sha256_file(report)}


def _review_task_reference(
    run_dir: Path,
    *,
    receipt_file: str,
    task_type: str,
    report_file: str,
    packet: dict[str, str],
    reviewer_thread_id: str,
    expected_prompt_sha256: str | None = None,
    require_fresh_thread: bool = False,
) -> tuple[dict[str, str], dict[str, Any]]:
    """复验开放审核任务并返回可持久化的回执引用。"""
    from shumozizi.simple.review_tasks import validate_review_task_receipt

    receipt = validate_review_task_receipt(
        run_dir,
        receipt_file,
        expected_type=task_type,
        expected_report=report_file,
        expected_input_bindings={"packet": packet},
        expected_prompt_sha256=expected_prompt_sha256,
        require_fresh_thread=require_fresh_thread,
    )
    if receipt["thread_id"] != reviewer_thread_id:
        raise ContractError("审核任务回执 thread_id 与导入参数不一致")
    path = _safe_run_path(run_dir, receipt_file)
    return (
        {
            "file": relative_inside(run_dir, path).as_posix(),
            "sha256": sha256_file(path),
            "task_id": receipt["task_id"],
        },
        receipt,
    )


def _competition_review_reference(
    run_dir: Path,
    *,
    manifest_file: str,
    expected_kind: str,
    receipt_file: str,
    task_type: str,
    report_file: Path,
    reviewer_thread_id: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """绑定 v3.1 单次审查的包、报告和真实任务回执。"""
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != expected_kind:
        raise ContractError(f"审查结论必须绑定 {expected_kind} 审查包")
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("审查包已失效: " + "；".join(packet["errors"]))
    report = _review_report(run_dir, report_file)
    packet_binding = {
        "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
    }
    expected_prompt_sha256 = None
    if expected_kind == "paper-blind":
        expected_prompt_sha256 = paper_blind_review_prompt_sha256(
            run_dir, relative_inside(run_dir, manifest_path).as_posix()
        )
    task_reference, _ = _review_task_reference(
        run_dir,
        receipt_file=receipt_file,
        task_type=task_type,
        report_file=report["file"],
        packet=packet_binding,
        reviewer_thread_id=reviewer_thread_id,
        expected_prompt_sha256=expected_prompt_sha256,
        require_fresh_thread=True,
    )
    return packet_binding, report, task_reference


def _competition_review_current(
    run_dir: Path, review: dict[str, Any], *, expected_kind: str, task_type: str
) -> tuple[bool, str]:
    """复验 v3.1 单次审查及其全面审核后的结构化查漏。"""
    try:
        packet = verify_review_packet(run_dir, review["packet"]["manifest_file"])
        if not packet["success"]:
            return False, "；".join(packet["errors"])
        if packet["manifest_sha256"] != review["packet"]["manifest_sha256"]:
            return False, "审查包清单哈希已变化"
        report = _safe_run_path(run_dir, review["report"]["file"])
        if sha256_file(report) != review["report"]["sha256"]:
            return False, "审查报告哈希已变化"
        task = review.get("task_receipt")
        if not isinstance(task, dict):
            return False, "审查摘要缺少真实任务回执"
        task_path = _safe_run_path(run_dir, task["file"])
        if sha256_file(task_path) != task["sha256"]:
            return False, "审核任务回执哈希已变化"
        from shumozizi.simple.review_tasks import validate_review_task_receipt

        receipt = validate_review_task_receipt(
            run_dir,
            task["file"],
            expected_type=task_type,
            expected_report=review["report"]["file"],
            expected_input_bindings={"packet": review["packet"]},
            require_fresh_thread=True,
        )
        if receipt["task_id"] != task["task_id"] or receipt["thread_id"] != review["reviewer"]["thread_id"]:
            return False, "审核摘要与任务回执身份不一致"
        if expected_kind in {"scientific", "paper-blind"}:
            from shumozizi.simple.review_gaps import verify_review_gap_completion

            gap = verify_review_gap_completion(
                run_dir,
                scope="scientific" if expected_kind == "scientific" else "paper",
                review_report=review,
            )
            if not gap["allowed"]:
                return False, "全面审核后的查漏未完成: " + gap["reason"]
        return True, ""
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return False, str(exc)


# 科学挑战报告最低字符数。关键词门控已移除——检查"独立/目标""风险""攻击""竞争力"
# 等词只能识别格式，不能区分真正的独立重建与复述当前实现。
# 保留字符数作为"非空壳"的最低门槛：报告过短说明没有实质分析。
_CHALLENGE_REPORT_MIN_CHARS = 300


def _require_scientific_challenge_sections(report_path: Path) -> None:
    """检查科学挑战报告至少包含实质内容，阻止完全空壳的报告通过门禁。

    关键词检查已移除：
    - "独立/目标""风险""攻击""竞争力"这类词可以被机械填入而没有实质内容；
    - 真正的独立重建不一定会使用这些词，而真正有价值的报告可能花大部分篇幅
      在一个核心缺陷的深度推导上，不使用任何关键词分类。

    只保留最低字符数检查，拦截明显的空文件或单行占位报告。
    实质性判断由 PDF 盲评和 record_stronger_alternative 的二选一承担。

    Args:
        report_path: 科学挑战报告绝对路径。

    Raises:
        ContractError: 报告不存在或过短。
    """
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"科学挑战报告无法读取: {exc}") from exc
    if len(text.strip()) < _CHALLENGE_REPORT_MIN_CHARS:
        raise ContractError(
            f"科学挑战报告过短（< {_CHALLENGE_REPORT_MIN_CHARS} 字符），缺少实质分析。"
            "报告应包含独立重建的模型判断、对当前方案的具体比较和至少一次真实攻击，"
            "而不是几行关键词占位。"
        )


def _import_competition_scientific_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    competition_strength: str,
    full_rerun_required: bool,
    affected_questions: list[str],
    reviewer_thread_id: str,
    task_receipt_file: str,
    report_file: Path,
) -> dict[str, Any]:
    """导入 v3.1 的自由科学挑战，保留 P0/P1 与真实回执边界。"""
    state = read_simple_state(run_dir)
    if state["phase"] != "experiment":
        raise ContractError("科学挑战结论只能在 experiment 阶段导入")
    packet, report, task = _competition_review_reference(
        run_dir,
        manifest_file=manifest_file,
        expected_kind="scientific",
        receipt_file=task_receipt_file,
        task_type="scientific_open",
        report_file=report_file,
        reviewer_thread_id=reviewer_thread_id,
    )
    from shumozizi.simple.review_focus import verify_scientific_challenge_evidence

    challenge_evidence = verify_scientific_challenge_evidence(run_dir)
    if not challenge_evidence["valid"]:
        raise ContractError("科学挑战缺少有效的实际攻击证据: " + "；".join(challenge_evidence["errors"]))
    verification = verify_red_team_artifacts(run_dir)
    if not verification["valid"]:
        raise ContractError("科学挑战的已登记执行证据无效: " + "；".join(verification["errors"]))
    if verification["evidence_records"]:
        from shumozizi.simple.evidence_consequences import apply_independent_evidence_consequences

        consequences = apply_independent_evidence_consequences(run_dir, verification["evidence_records"])
        if consequences:
            raise ContractError("独立负面证据已回退 experiment，不能导入挑战通过结论")
    # v3.1/v3.2 Competition-First 的科学挑战不使用旧覆盖率查漏系统（review_gaps.py）。
    # 隔离由"自由报告 + record_stronger_alternative 闭合 + 真实攻击证据"三者组合保证，
    # 与 Capability-First 的 required_risks / coverage_declaration 体系互不兼容。
    _require_scientific_challenge_sections(run_dir / report_file)
    review = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "competition_strength": competition_strength,
        "full_rerun_required": full_rerun_required,
        "affected_questions": list(dict.fromkeys(affected_questions)),
        "packet": packet,
        "report": report,
        "task_receipt": task,
        "challenge_evidence": challenge_evidence["evidence"],
        "reviewer": _reviewer_scientific(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    summary = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "scientific_review": review,
        "paper_blind_review": None,
        "updated_at": utc_now(),
    }
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def _paper_blind_text(value: Any, label: str, *, minimum: int = 8) -> str:
    """读取盲评结构化结果中的实质文本并拒绝模板占位。"""
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ContractError(f"结构化盲评 {label} 至少需要 {minimum} 个字符")
    text = value.strip()
    if re.search(r"请替换|待填写|待补充|TODO|TBD", text, re.IGNORECASE):
        raise ContractError(f"结构化盲评 {label} 仍包含模板占位")
    return text


def _paper_blind_pages(value: Any, label: str, *, allow_empty: bool = False) -> list[int]:
    """规整盲评页码，确保结论能够回到冻结 PDF 定位。"""
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"结构化盲评 {label} 必须包含实际 PDF 页码")
    pages: list[int] = []
    for page in value:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ContractError(f"结构化盲评 {label} 只能包含正整数页码")
        if page not in pages:
            pages.append(page)
    return pages


def _parse_paper_blind_structured_results(
    run_dir: Path, report: Path
) -> dict[str, Any]:
    """从同一份独立盲评报告中解析并校验结构化冷读结果。"""
    source = report.read_text(encoding="utf-8")
    if source.count(PAPER_BLIND_STRUCTURED_HEADING) != 1:
        raise ContractError(
            f"PDF 盲评报告必须且只能包含一个 {PAPER_BLIND_STRUCTURED_HEADING}"
        )
    match = re.search(
        rf"(?ms)^{re.escape(PAPER_BLIND_STRUCTURED_HEADING)}\s*$\s*"
        r"```json\s*(\{.*?\})\s*```",
        source,
    )
    if match is None:
        raise ContractError("PDF 盲评报告缺少紧随结构化标题的 json 代码块")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ContractError(f"PDF 盲评结构化 JSON 无法解析: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("PDF 盲评结构化结果必须是 JSON 对象")
    expected_top = {
        "cold_read",
        "structure",
        "argument_findings",
        "question_progression",
        "narrative_risks",
        "review_summary",
    }
    if set(payload) != expected_top:
        raise ContractError("PDF 盲评结构化结果字段不完整或包含未知字段")

    state = read_simple_state(run_dir)
    questions = list(state["required_questions"])
    question_set = set(questions)
    cold_read = payload["cold_read"]
    cold_fields = {
        "input_scope",
        "direct_answers_found_within_3_minutes",
        "one_sentence_contribution",
        "cross_question_inheritance_understood",
        "first_five_pages_establish_data_intuition",
        "hero_figures_identified",
        "report_like_pages",
    }
    if not isinstance(cold_read, dict) or set(cold_read) != cold_fields:
        raise ContractError("结构化盲评 cold_read 字段不完整或包含未知字段")
    if cold_read["input_scope"] != "frozen_pdf_only":
        raise ContractError("结构化盲评 cold_read 只能读取 frozen_pdf_only")
    answers = cold_read["direct_answers_found_within_3_minutes"]
    heroes = cold_read["hero_figures_identified"]
    if not isinstance(answers, dict) or set(answers) != question_set:
        raise ContractError("结构化盲评必须逐问记录三分钟直接答案检索")
    if not isinstance(heroes, dict) or set(heroes) != question_set:
        raise ContractError("结构化盲评必须逐问记录主图识别结果")
    if any(not isinstance(value, bool) for value in [*answers.values(), *heroes.values()]):
        raise ContractError("结构化盲评的直接答案和主图判断必须为布尔值")
    _paper_blind_text(cold_read["one_sentence_contribution"], "one_sentence_contribution")
    for field in (
        "cross_question_inheritance_understood",
        "first_five_pages_establish_data_intuition",
    ):
        if not isinstance(cold_read[field], bool):
            raise ContractError(f"结构化盲评 cold_read.{field} 必须为布尔值")
    cold_read["report_like_pages"] = _paper_blind_pages(
        cold_read["report_like_pages"], "cold_read.report_like_pages", allow_empty=True
    )

    structure = payload["structure"]
    if not isinstance(structure, dict) or set(structure) != set(PAPER_BLIND_STRUCTURE_FIELDS):
        raise ContractError("结构化盲评 structure 未完整覆盖论文结构")
    if any(value not in {"pass", "issue"} for value in structure.values()):
        raise ContractError("结构化盲评 structure 只能填写 pass 或 issue")

    findings = payload["argument_findings"]
    if not isinstance(findings, dict) or set(findings) != question_set:
        raise ContractError("结构化盲评 argument_findings 必须逐问完整覆盖")
    allowed_roles = set(PAPER_BLIND_ARGUMENT_ROLES)
    for question_id in questions:
        finding = findings[question_id]
        if not isinstance(finding, dict) or set(finding) != {
            "missing_roles",
            "pages",
            "finding",
        }:
            raise ContractError(f"结构化盲评 {question_id} 论证发现字段不完整")
        missing_roles = finding["missing_roles"]
        if (
            not isinstance(missing_roles, list)
            or len(set(missing_roles)) != len(missing_roles)
            or any(role not in allowed_roles for role in missing_roles)
        ):
            raise ContractError(f"结构化盲评 {question_id}.missing_roles 无效")
        finding["pages"] = _paper_blind_pages(
            finding["pages"], f"argument_findings.{question_id}.pages"
        )
        _paper_blind_text(
            finding["finding"], f"argument_findings.{question_id}.finding", minimum=12
        )
        answer_found = answers[question_id]
        direct_missing = "direct_answer" in missing_roles
        if answer_found == direct_missing:
            raise ContractError(
                f"结构化盲评 {question_id} 的三分钟答案检索与 direct_answer 缺失判断冲突"
            )

    progression = payload["question_progression"]
    if not isinstance(progression, dict) or set(progression) != {
        "status",
        "interchangeable_questions",
        "links",
        "summary",
    }:
        raise ContractError("结构化盲评 question_progression 字段不完整")
    if progression["status"] not in {"pass", "issue"} or not isinstance(
        progression["interchangeable_questions"], bool
    ):
        raise ContractError("结构化盲评 question_progression 状态无效")
    if not isinstance(progression["links"], list):
        raise ContractError("结构化盲评 question_progression.links 必须为数组")
    for index, link in enumerate(progression["links"]):
        if not isinstance(link, dict) or set(link) != {"from", "to", "inheritance"}:
            raise ContractError(f"结构化盲评 progression link {index} 字段无效")
        if (
            link["from"] not in question_set
            or link["to"] not in question_set
            or link["from"] == link["to"]
        ):
            raise ContractError(f"结构化盲评 progression link {index} 问题编号无效")
        _paper_blind_text(link["inheritance"], f"progression link {index}.inheritance")
    if (
        len(questions) > 1
        and progression["status"] == "pass"
        and len(progression["links"]) < len(questions) - 1
    ):
        raise ContractError("问题递进判为 pass 时必须提供足以串联各问的继承关系")
    _paper_blind_text(progression["summary"], "question_progression.summary", minimum=12)

    risks = payload["narrative_risks"]
    if not isinstance(risks, list):
        raise ContractError("结构化盲评 narrative_risks 必须为数组")
    for index, risk in enumerate(risks):
        if not isinstance(risk, dict) or set(risk) != {
            "severity",
            "location",
            "issue",
            "status",
        }:
            raise ContractError(f"结构化盲评 narrative_risks[{index}] 字段无效")
        if risk["severity"] not in {"P0", "P1", "P2", "P3"}:
            raise ContractError(f"结构化盲评 narrative_risks[{index}] 严重度无效")
        if risk["status"] not in {"open", "resolved"}:
            raise ContractError(f"结构化盲评 narrative_risks[{index}] 状态无效")
        _paper_blind_text(risk["location"], f"narrative_risks[{index}].location", minimum=1)
        _paper_blind_text(risk["issue"], f"narrative_risks[{index}].issue")
    _paper_blind_text(payload["review_summary"], "review_summary", minimum=20)
    return payload


def _paper_blind_core_questions(run_dir: Path, required_questions: list[str]) -> set[str]:
    """读取核心问题；缺少正式建模单元时保守检查全部必答问题。"""
    try:
        modeling = load_json(run_dir / "analysis" / "MODELING_UNITS.json")
    except ContractError:
        return set(required_questions)
    core = {
        str(unit.get("question_id"))
        for unit in modeling.get("units", [])
        if isinstance(unit, dict) and unit.get("core_question") is True
    }
    return core or set(required_questions)


def _import_v32_paper_blind_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    task_receipt_file: str,
    report_file: Path,
) -> dict[str, Any]:
    """导入 v3.2 的 PDF 盲评，写入独立记录而不依赖 v3.1 ``summary.json``。

    v3.2 的科学挑战由 ``review/SCIENTIFIC_CHALLENGE.md`` 加 fresh-thread 回执承载，
    不生成 ``review/summary.json``；盲评隔离仍由"冻结 PDF + 独立任务回执 +
    不同于科学挑战的新对话"三者保证。
    """
    if read_simple_state(run_dir)["phase"] != "paper_review":
        raise ContractError("PDF 盲评结论只能在 paper_review 阶段导入")
    scientific = _v32_scientific_challenge_status(run_dir)
    if not scientific["allowed"]:
        raise ContractError("科学挑战未通过或已失效，不能导入 PDF 盲评: " + scientific["reason"])
    scientific_thread = scientific["review"]["task_receipt"]["thread_id"]
    if reviewer_thread_id == scientific_thread:
        raise ContractError("PDF 盲评必须使用不同于科学挑战的新对话")
    packet, report, task = _competition_review_reference(
        run_dir,
        manifest_file=manifest_file,
        expected_kind="paper-blind",
        receipt_file=task_receipt_file,
        task_type="paper_blind_open",
        report_file=report_file,
        reviewer_thread_id=reviewer_thread_id,
    )
    state = read_simple_state(run_dir)
    structured = _parse_paper_blind_structured_results(
        run_dir, _safe_run_path(run_dir, report["file"])
    )
    core_questions = _paper_blind_core_questions(run_dir, state["required_questions"])
    structured_blockers = [
        question_id
        for question_id in core_questions
        if structured["argument_findings"][question_id]["missing_roles"]
    ]
    if verdict == "pass" and structured_blockers:
        raise ContractError(
            "盲评判为 pass，但核心问题仍有论证角色缺失: " + ", ".join(sorted(structured_blockers))
        )
    if verdict == "pass" and (
        structured["question_progression"]["status"] != "pass"
        or structured["question_progression"]["interchangeable_questions"] is True
    ):
        raise ContractError("盲评判为 pass，但结构化结果认为各问递进仍有问题")
    open_high_risks = [
        risk
        for risk in structured["narrative_risks"]
        if risk["severity"] in {"P0", "P1"} and risk["status"] == "open"
    ]
    if verdict == "pass" and open_high_risks:
        raise ContractError("盲评判为 pass，但结构化结果仍包含未关闭 P0/P1 叙事风险")
    render_revision = int(
        state.get("render_revision", state.get("paper_render_revision", 0))
    )
    argument_revision = int(state.get("argument_revision", render_revision))
    record = {
        "schema_name": "v32_paper_blind_review",
        "schema_version": "1.2",
        "run_id": run_dir.name,
        "verdict": verdict,
        "highest_severity": highest_severity,
        "paper_render_revision": render_revision,
        "render_revision": render_revision,
        "argument_revision": argument_revision,
        "packet": packet,
        "report": report,
        "task_receipt": task,
        "reviewer": _reviewer_paper(reviewer_thread_id),
        "cold_read": structured["cold_read"],
        "structure": structured["structure"],
        "argument_findings": structured["argument_findings"],
        "question_progression": structured["question_progression"],
        "narrative_risks": structured["narrative_risks"],
        "review_summary": structured["review_summary"],
        # 将用户固定的人工干预写入回执，便于后续审计确认审查范围未缩水。
        "manual_intervention": MANUAL_INTERVENTION_RECORD,
        "structured_results_sha256": sha256_bytes(json_bytes(structured)),
        "reviewed_at": utc_now(),
    }
    atomic_json(run_dir / V32_PAPER_BLIND_RECORD_PATH, record)
    from shumozizi.simple.state import record_paper_review

    record_paper_review(run_dir, argument_revision=argument_revision)
    return {"paper_blind_review": record}


def _v32_paper_blind_review_status(run_dir: Path) -> dict[str, Any]:
    """返回 v3.2 PDF 盲评或其显式跳过说明是否允许继续机械 QA。"""
    try:
        record_path = run_dir / V32_PAPER_BLIND_RECORD_PATH
        if not record_path.is_file():
            skip = run_dir / REVIEW_ROOT / "PAPER_BLIND_REVIEW_SKIP.md"
            if skip.is_file() and len(skip.read_text(encoding="utf-8").strip()) > 32:
                return {"allowed": True, "skipped": True, "reason": "已显式记录 PDF 盲评跳过原因"}
            return {"allowed": False, "reason": "缺少独立 PDF 盲评或明确跳过原因"}
        review = load_json(record_path)
        if (
            review.get("schema_name") != "v32_paper_blind_review"
            or review.get("schema_version") not in {"1.0", "1.1", "1.2"}
            or review.get("run_id") != run_dir.name
        ):
            return {"allowed": False, "reason": "v3.2 PDF 盲评记录格式无效"}
        if review["verdict"] == "pass" and review["highest_severity"] in {"P0", "P1"}:
            return {"allowed": False, "reason": "盲评含 P0/P1 时不能给出 pass"}
        current, reason = _v32_paper_blind_review_current(run_dir, review)
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
        )
        return {"allowed": allowed, "review": review, "reason": reason if not allowed else ""}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def _v32_paper_blind_review_current(run_dir: Path, review: dict[str, Any]) -> tuple[bool, str]:
    """复验 v3.2 盲评仍绑定未漂移的冻结 PDF、报告和独立回执。"""
    try:
        state = read_simple_state(run_dir)
        if review.get("schema_version") == "1.2":
            review_argument = review.get("argument_revision")
            if (
                review_argument != state.get("argument_revision", 0)
                or review_argument != state.get("reviewed_argument_revision", 0)
            ):
                return False, "当前论证修订尚未完成独立 PDF 盲评"
        else:
            review_revision = review.get("paper_render_revision")
            if review_revision is not None and (
                review_revision != state.get("paper_render_revision", 0)
                or review_revision != state.get("paper_reviewed_revision", 0)
            ):
                return False, "当前渲染修订尚未完成独立 PDF 盲评"
        packet = _verify_v32_frozen_packet_copy(
            run_dir, review.get("packet"), expected_kind="paper-blind"
        )
        report = _safe_run_path(run_dir, review["report"]["file"])
        if sha256_file(report) != review["report"]["sha256"]:
            return False, "盲评报告哈希已变化"
        if review.get("schema_version") in {"1.1", "1.2"}:
            structured = _parse_paper_blind_structured_results(run_dir, report)
            if sha256_bytes(json_bytes(structured)) != review.get(
                "structured_results_sha256"
            ):
                return False, "盲评结构化结果与同源报告不一致"
            for field in (
                "cold_read",
                "structure",
                "argument_findings",
                "question_progression",
                "narrative_risks",
                "review_summary",
            ):
                if review.get(field) != structured[field]:
                    return False, f"盲评记录字段 {field} 与同源报告不一致"
        task = review.get("task_receipt")
        if not isinstance(task, dict):
            return False, "盲评记录缺少真实任务回执"
        task_path = _safe_run_path(run_dir, task["file"])
        if sha256_file(task_path) != task["sha256"]:
            return False, "盲评任务回执哈希已变化"
        from shumozizi.simple.review_tasks import validate_review_task_receipt

        receipt = validate_review_task_receipt(
            run_dir,
            task["file"],
            expected_type="paper_blind_open",
            expected_report=review["report"]["file"],
            expected_input_bindings={"packet": packet},
            expected_prompt_sha256=paper_blind_review_prompt_sha256(
                run_dir, packet["manifest_file"]
            ),
            require_fresh_thread=True,
        )
        if (
            receipt["task_id"] != task["task_id"]
            or receipt["thread_id"] != review["reviewer"]["thread_id"]
        ):
            return False, "盲评记录与任务回执身份不一致"
        if review.get("schema_version") != "1.2":
            # 旧记录只能靠 PDF 哈希判断当前性；1.2 已改由 argument revision 绑定。
            frozen = _v32_frozen_paper_pdf(run_dir, packet["manifest_file"])
            current_pdf = run_dir / "paper" / "final.pdf"
            if not current_pdf.is_file():
                return False, "缺少当前 paper/final.pdf"
            if sha256_file(current_pdf) != frozen:
                return False, "当前 PDF 已在盲评后重新编译，需要重新盲评"
        return True, ""
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return False, str(exc)


def require_current_paper_blind_review_record(run_dir: Path) -> dict[str, Any]:
    """返回绑定当前 PDF、报告和独立任务的 v3.2 结构化盲评记录。

    该接口只校验事实来源是否当前，不把 verdict 当作读取门槛；因此版式审计可以
    如实记录需要返工的同一轮盲评，而不是另造一套作者输入。
    """
    record_path = run_dir / V32_PAPER_BLIND_RECORD_PATH
    if not record_path.is_file():
        raise ContractError("缺少 review/paper-blind-review.json 独立盲评记录")
    review = load_json(record_path)
    if (
        review.get("schema_name") != "v32_paper_blind_review"
        or review.get("schema_version") not in {"1.1", "1.2"}
        or review.get("run_id") != run_dir.name
    ):
        raise ContractError("当前 CUMCM 审计需要 v3.2 结构化盲评记录 1.1 或 1.2")
    current, reason = _v32_paper_blind_review_current(run_dir, review)
    if not current:
        raise ContractError("独立 PDF 盲评记录已失效: " + reason)
    return review


def _v32_frozen_paper_pdf(run_dir: Path, manifest_file: str) -> str:
    """返回盲评冻结包中最终 PDF 的 SHA-256。"""
    _, manifest = _read_packet_manifest(run_dir, manifest_file)
    for item in manifest["files"]:
        if isinstance(item, dict) and item.get("source") == "paper/final.pdf":
            sha256 = item.get("sha256")
            if isinstance(sha256, str):
                return sha256
    raise ContractError("盲评冻结包未包含 paper/final.pdf")


def _import_competition_paper_blind_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    task_receipt_file: str,
    report_file: Path,
) -> dict[str, Any]:
    """导入 v3.1 的相对竞争力 PDF 盲评，不创建覆盖闭环。"""
    if is_competition_first_v32_state(read_simple_state(run_dir)):
        return _import_v32_paper_blind_review(
            run_dir,
            manifest_file=manifest_file,
            verdict=verdict,
            highest_severity=highest_severity,
            reviewer_thread_id=reviewer_thread_id,
            task_receipt_file=task_receipt_file,
            report_file=report_file,
        )
    if read_simple_state(run_dir)["phase"] != "paper_review":
        raise ContractError("PDF 盲评结论只能在 paper_review 阶段导入")
    packet, report, task = _competition_review_reference(
        run_dir,
        manifest_file=manifest_file,
        expected_kind="paper-blind",
        receipt_file=task_receipt_file,
        task_type="paper_blind_open",
        report_file=report_file,
        reviewer_thread_id=reviewer_thread_id,
    )
    summary = read_review_summary(run_dir)
    scientific_thread = summary["scientific_review"]["reviewer"]["thread_id"]
    if reviewer_thread_id == scientific_thread:
        raise ContractError("PDF 盲评必须使用不同于科学挑战的新对话")
    # v3.1/v3.2 Competition-First 的 PDF 盲评不使用旧覆盖率查漏系统（review_gaps.py）；
    # 盲评只负责论文相对竞争力和可读性，隔离由冻结 PDF + 独立任务回执 + fresh thread 保证。
    summary["paper_blind_review"] = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": packet,
        "report": report,
        "task_receipt": task,
        "reviewer": _reviewer_paper(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    summary["updated_at"] = utc_now()
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def import_scientific_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    competition_strength: str,
    full_rerun_required: bool,
    affected_questions: list[str],
    reviewer_thread_id: str,
    task_receipt_file: str,
    report_file: Path = SCIENTIFIC_REPORT_PATH,
    question_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """将新对话的自由科学审查报告绑定为可机读的放行摘要。

    Args:
        question_reviews: 逐问细化结论，每项至少包含 question_id / verdict /
            competition_strength。当运行有必答问题时必须提供，不可回退到全局值。
    """
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("科学审查 verdict 或严重性不合法")
    if competition_strength not in {"weak", "qualified", "strong", "unknown"}:
        raise ContractError("competition_strength 不合法")
    if verdict == "pass" and (highest_severity in {"P0", "P1"} or full_rerun_required):
        raise ContractError("P0/P1 或全量重跑要求不能导入为 pass")
    state = read_simple_state(run_dir)
    if is_competition_first_state(state):
        return _import_competition_scientific_review(
            run_dir,
            manifest_file=manifest_file,
            verdict=verdict,
            highest_severity=highest_severity,
            competition_strength=competition_strength,
            full_rerun_required=full_rerun_required,
            affected_questions=affected_questions,
            reviewer_thread_id=reviewer_thread_id,
            task_receipt_file=task_receipt_file,
            report_file=report_file,
        )
    if state["phase"] != "scientific_review":
        raise ContractError("科学审查结论只能在 scientific_review 阶段导入")
    # 有必答问题时逐问审查不可省略
    if state.get("required_questions") and question_reviews is None:
        raise ContractError(
            "有必答问题时逐问审查 (question_reviews) 必须覆盖全部问题，不能省略"
        )
    semantics = objective_semantics_review_status(run_dir)
    if not semantics["allowed"]:
        raise ContractError("科学审查前的目标语义预审未通过或已失效: " + semantics["reason"])
    if semantics.get("required") and reviewer_thread_id == semantics["review"]["reviewer"]["thread_id"]:
        raise ContractError("科学红队必须使用不同于目标语义预审的新对话")
    _, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "scientific":
        raise ContractError("科学审查必须绑定 scientific 审查包")
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("科学审查包已失效: " + "；".join(packet["errors"]))
    report = _review_report(run_dir, report_file)
    packet_binding = {
        "manifest_file": packet["manifest_file"],
        "manifest_sha256": packet["manifest_sha256"],
    }
    task_reference, task_receipt = _review_task_reference(
        run_dir,
        receipt_file=task_receipt_file,
        task_type="scientific_open",
        report_file=report["file"],
        packet=packet_binding,
        reviewer_thread_id=reviewer_thread_id,
    )
    artifacts = _bind_red_team_artifacts(run_dir, report)
    verification = verify_red_team_artifacts(run_dir)
    if not verification["valid"]:
        raise ContractError("红队执行证据无效: " + "；".join(verification["errors"]))
    from shumozizi.simple.evidence_consequences import (
        apply_independent_evidence_consequences,
    )

    consequences = apply_independent_evidence_consequences(
        run_dir, verification["evidence_records"]
    )
    evidence_assessment = _verified_evidence_assessment(run_dir)
    if consequences:
        raise ContractError(
            "独立负面证据已先执行级联失效并回退 experiment: "
            + ", ".join(item["source_evidence_id"] for item in consequences)
        )
    if verdict == "pass" and not evidence_assessment["pass_allowed"]:
        raise ContractError(
            "科学审查 pass 与红队负面证据冲突: "
            + "；".join(evidence_assessment["blocking_reasons"])
        )
    # ── 逐问审查：校验并合并 per-question verdicts ──
    validated_question_reviews = _validate_question_reviews(
        run_dir, question_reviews
    )
    _require_competition_strength_evidence(
        competition_strength,
        artifacts,
        evidence_assessment,
        run_dir,
        semantics,
        validated_question_reviews,
    )
    # ── 验证覆盖声明不是关键词扫描 ──
    require_coverage_declaration_valid(
        run_dir,
        expected_report_file=report["file"],
        scope="scientific",
        expected_parent_task_id=task_receipt["task_id"],
    )
    semantics_binding = None
    if semantics.get("required"):
        semantics_receipt = run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH
        semantics_binding = {
            "file": relative_inside(run_dir, semantics_receipt).as_posix(),
            "sha256": sha256_file(semantics_receipt),
        }
    review = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "competition_strength": competition_strength,
        "full_rerun_required": full_rerun_required,
        "affected_questions": list(dict.fromkeys(affected_questions)),
        "packet": {
            "manifest_file": packet["manifest_file"],
            "manifest_sha256": packet["manifest_sha256"],
        },
        "report": report,
        "task_receipt": task_reference,
        "artifacts": artifacts,
        "objective_semantics": semantics_binding,
        "reviewer": _reviewer_scientific(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    if validated_question_reviews is not None:
        review["question_reviews"] = validated_question_reviews
    # 没有必答问题时仍用 v1.5 兼容旧运行
    summary_version = "1.7"
    summary = {
        "schema_version": summary_version,
        "run_id": run_dir.name,
        "scientific_review": review,
        # 新科学结论会改变论文可用性；旧盲审不能跨越该边界复用。
        "paper_blind_review": None,
        "final_audit": None,
        "updated_at": utc_now(),
    }
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def import_paper_blind_review(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    task_receipt_file: str,
    report_file: Path = PAPER_BLIND_REPORT_PATH,
) -> dict[str, Any]:
    """绑定独立盲审报告；它只决定提交可读性，不替代科学红队。"""
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("盲审 verdict 或严重性不合法")
    if verdict == "pass" and highest_severity in {"P0", "P1"}:
        raise ContractError("盲审含 P0/P1 时不能导入为 pass")
    if _competition_first_run(run_dir):
        return _import_competition_paper_blind_review(
            run_dir,
            manifest_file=manifest_file,
            verdict=verdict,
            highest_severity=highest_severity,
            reviewer_thread_id=reviewer_thread_id,
            task_receipt_file=task_receipt_file,
            report_file=report_file,
        )
    if read_simple_state(run_dir)["phase"] != "paper_review":
        raise ContractError("PDF 盲审结论只能在 paper_review 阶段导入")
    require_paper_generation_allowed(run_dir)
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("盲审包已失效: " + "；".join(packet["errors"]))
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "paper-blind":
        raise ContractError("盲审必须绑定 paper-blind 审查包")
    report = _review_report(run_dir, report_file)
    packet_binding = {
        "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
    }
    task_reference, task_receipt = _review_task_reference(
        run_dir,
        receipt_file=task_receipt_file,
        task_type="paper_blind_open",
        report_file=report["file"],
        packet=packet_binding,
        reviewer_thread_id=reviewer_thread_id,
    )
    require_coverage_declaration_valid(
        run_dir,
        expected_report_file=report["file"],
        scope="paper",
        expected_parent_task_id=task_receipt["task_id"],
    )
    summary = read_review_summary(run_dir)
    used_threads = {summary["scientific_review"]["reviewer"]["thread_id"]}
    semantics = objective_semantics_review_status(run_dir)
    if semantics.get("required"):
        used_threads.add(semantics["review"]["reviewer"]["thread_id"])
    if reviewer_thread_id in used_threads:
        raise ContractError("PDF 盲审必须使用不同于科学红队、目标语义预审的新对话")
    summary["schema_version"] = "1.7"
    summary["paper_blind_review"] = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": {
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
        },
        "report": report,
        "task_receipt": task_reference,
        "reviewer": _reviewer_paper(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    # 新 PDF 盲审会改变最终交付边界，旧终审不能复用。
    summary["final_audit"] = None
    summary["updated_at"] = utc_now()
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def import_final_audit(
    run_dir: Path,
    *,
    manifest_file: str,
    verdict: str,
    highest_severity: str,
    reviewer_thread_id: str,
    task_receipt_file: str,
    report_file: Path = FINAL_AUDIT_REPORT_PATH,
) -> dict[str, Any]:
    """绑定第三个新对话完成的最终交付审核报告。"""
    if _competition_first_run(run_dir):
        raise ContractError("Competition-First v3.1 不再创建或导入 final-audit；请执行机械 QA")
    if verdict not in _VERDICTS or highest_severity not in _SEVERITIES:
        raise ContractError("最终交付审核 verdict 或严重性不合法")
    if verdict == "pass" and highest_severity in {"P0", "P1"}:
        raise ContractError("最终交付审核含 P0/P1 时不能导入为 pass")
    if read_simple_state(run_dir)["phase"] != "final_review":
        raise ContractError("最终交付审核只能在 final_review 阶段导入")
    require_final_review_allowed(run_dir)
    packet = verify_review_packet(run_dir, manifest_file)
    if not packet["success"]:
        raise ContractError("最终交付审核包已失效: " + "；".join(packet["errors"]))
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != "final-audit":
        raise ContractError("最终交付审核必须绑定 final-audit 审查包")
    report = _review_report(run_dir, report_file)
    packet_binding = {
        "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
    }
    task_reference, _ = _review_task_reference(
        run_dir,
        receipt_file=task_receipt_file,
        task_type="final_audit",
        report_file=report["file"],
        packet=packet_binding,
        reviewer_thread_id=reviewer_thread_id,
    )
    summary = read_review_summary(run_dir)
    used_threads = {
        summary["scientific_review"]["reviewer"]["thread_id"],
        summary["paper_blind_review"]["reviewer"]["thread_id"],
    }
    semantics = objective_semantics_review_status(run_dir)
    if semantics.get("required"):
        used_threads.add(semantics["review"]["reviewer"]["thread_id"])
    if reviewer_thread_id in used_threads:
        raise ContractError("最终交付审核必须使用不同于前两轮审核的第三个新对话")
    summary["schema_version"] = "1.7"
    summary["final_audit"] = {
        "verdict": verdict,
        "highest_severity": highest_severity,
        "packet": {
            "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
        },
        "report": report,
        "task_receipt": task_reference,
        "reviewer": _reviewer_final(reviewer_thread_id),
        "reviewed_at": utc_now(),
    }
    summary["updated_at"] = utc_now()
    _require_summary(summary)
    atomic_json(run_dir / SUMMARY_PATH, summary)
    return summary


def _review_current(
    run_dir: Path, review: dict[str, Any], *, expected_kind: str
) -> tuple[bool, str]:
    """确认摘要仍绑定同一份未漂移的冻结审查包与报告。"""
    _, manifest = _read_packet_manifest(run_dir, review["packet"]["manifest_file"])
    if manifest["packet_kind"] != expected_kind:
        return False, f"审查摘要绑定了 {manifest['packet_kind']} 审查包，而非 {expected_kind}"
    packet = verify_review_packet(run_dir, review["packet"]["manifest_file"])
    if not packet["success"]:
        return False, "；".join(packet["errors"])
    if packet["manifest_sha256"] != review["packet"]["manifest_sha256"]:
        return False, "审查包清单哈希已变化"
    report = _safe_run_path(run_dir, review["report"]["file"])
    if sha256_file(report) != review["report"]["sha256"]:
        return False, "审查报告哈希已变化"
    task_type = {
        "scientific": "scientific_open",
        "paper-blind": "paper_blind_open",
        "final-audit": "final_audit",
    }[expected_kind]
    task_reference = review.get("task_receipt")
    if not isinstance(task_reference, dict):
        return False, "审核摘要缺少真实任务回执；旧摘要不能用于当前生产放行"
    try:
        task_path = _safe_run_path(run_dir, task_reference["file"])
        if sha256_file(task_path) != task_reference["sha256"]:
            return False, "审核任务回执哈希已变化"
        from shumozizi.simple.review_tasks import validate_review_task_receipt

        task_receipt = validate_review_task_receipt(
            run_dir,
            task_reference["file"],
            expected_type=task_type,
            expected_report=review["report"]["file"],
            expected_input_bindings={"packet": review["packet"]},
        )
        if (
            task_receipt["task_id"] != task_reference["task_id"]
            or task_receipt["thread_id"] != review["reviewer"]["thread_id"]
        ):
            return False, "审核摘要与任务回执身份不一致"
        if expected_kind == "scientific":
            require_coverage_declaration_valid(
                run_dir,
                expected_report_file=review["report"]["file"],
                scope="scientific",
                expected_parent_task_id=task_receipt["task_id"],
            )
        elif expected_kind == "paper-blind":
            require_coverage_declaration_valid(
                run_dir,
                expected_report_file=review["report"]["file"],
                scope="paper",
                expected_parent_task_id=task_receipt["task_id"],
            )
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return False, str(exc)
    if expected_kind == "scientific":
        if "artifacts" not in review:
            return False, "科学审查缺少可执行红队证据；旧摘要不能作为生产放行依据"
        try:
            artifacts = _bind_red_team_artifacts(run_dir, review["report"])
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            return False, str(exc)
        if artifacts != review["artifacts"]:
            return False, "红队证据收据或报告引用已变化"
        evidence_assessment = _verified_evidence_assessment(run_dir)
        if not evidence_assessment["pass_allowed"]:
            return False, "红队出现负面科学证据: " + "；".join(
                evidence_assessment["blocking_reasons"]
            )
        semantics = objective_semantics_review_status(run_dir)
        binding = review.get("objective_semantics")
        if semantics.get("required"):
            receipt_path = run_dir / OBJECTIVE_SEMANTICS_RECEIPT_PATH
            if not isinstance(binding, dict) or binding.get("sha256") != sha256_file(
                receipt_path
            ):
                return False, "科学审查绑定的目标语义版本已变化"
        elif binding is not None:
            return False, "科学审查绑定了当前运行不需要的目标语义收据"
    return True, ""


def _competition_scientific_review_status(run_dir: Path) -> dict[str, Any]:
    """返回 v3.1 单次科学挑战是否仍有效。"""
    try:
        summary = read_review_summary(run_dir)
        review = summary["scientific_review"]
        current, reason = _competition_review_current(
            run_dir, review, expected_kind="scientific", task_type="scientific_open"
        )
        from shumozizi.simple.review_focus import verify_scientific_challenge_evidence

        challenge_evidence = verify_scientific_challenge_evidence(run_dir)
        if not challenge_evidence["valid"]:
            current = False
            reason = "科学挑战实际攻击证据已失效: " + "；".join(challenge_evidence["errors"])
        elif review.get("challenge_evidence") != challenge_evidence["evidence"]:
            current = False
            reason = "科学挑战实际攻击证据绑定已变化"
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
            and not review["full_rerun_required"]
        )
        return {
            "allowed": allowed,
            "submission_ready": allowed,
            "competition_strength": review.get("competition_strength", "unknown"),
            "review": review,
            "reason": reason if not allowed else "",
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            "allowed": False,
            "submission_ready": False,
            "competition_strength": "unknown",
            "reason": str(exc),
        }


def _verify_v32_frozen_packet_copy(
    run_dir: Path, packet_binding: dict[str, Any], *, expected_kind: str
) -> dict[str, Any]:
    """验证 v3.2 审查任务实际读取过的冻结副本未被改写。

    v3.2 的当前性由建模单元和科学挑战证据中的生产结果负责；这里仅验证
    当时交给独立对话的副本及其清单，避免工作簿导出等非评分脚本改动把已绑定
    的数值攻击错误判成失效。
    """
    if not isinstance(packet_binding, dict):
        raise ContractError("v3.2 科学挑战回执缺少冻结审查包绑定")
    manifest_file = packet_binding.get("manifest_file")
    manifest_sha256 = packet_binding.get("manifest_sha256")
    if not isinstance(manifest_file, str) or not isinstance(manifest_sha256, str):
        raise ContractError("v3.2 科学挑战冻结审查包绑定格式无效")
    manifest_path, manifest = _read_packet_manifest(run_dir, manifest_file)
    if manifest["packet_kind"] != expected_kind:
        raise ContractError(f"v3.2 科学挑战绑定了 {manifest['packet_kind']} 审查包")
    if sha256_file(manifest_path) != manifest_sha256:
        raise ContractError("v3.2 科学挑战审查包清单已变化")
    packet_dir = manifest_path.parent
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ContractError("v3.2 科学挑战审查包文件条目无效")
        packet_relative = item.get("packet")
        expected_sha256 = item.get("sha256")
        if not isinstance(packet_relative, str) or not isinstance(expected_sha256, str):
            raise ContractError("v3.2 科学挑战审查包文件缺少路径或哈希")
        frozen_file = _safe_packet_path(packet_dir, packet_relative)
        if not frozen_file.is_file() or sha256_file(frozen_file) != expected_sha256:
            raise ContractError(f"v3.2 科学挑战冻结副本已变化: {packet_relative}")
    return {
        "manifest_file": relative_inside(run_dir, manifest_path).as_posix(),
        "manifest_sha256": manifest_sha256,
    }


def _v32_unresolved_high_severities(report_text: str) -> list[str]:
    """从挑战报告的风险清单中提取仍未关闭的 P0/P1 风险。

    没有结构化风险清单时保持保守：只要报告提到 P0/P1，就不能把该运行标记为
    可提交；这不会阻断论文生成或后续独立审稿。
    """
    entries = re.findall(
        r"(?m)^\s*[-*]\s+\*\*(P[0-3])(?:-[^：:*]+)?[：:]\*\*\s*(.+)$",
        report_text,
    )
    unresolved = {
        severity
        for severity, detail in entries
        if severity in {"P0", "P1"}
        and not re.search(r"(?:无|已修复|已关闭|resolved)", detail, flags=re.IGNORECASE)
    }
    if not entries and re.search(r"\bP[01](?:[-：:]|\b)", report_text):
        unresolved.add("P0/P1（未结构化）")
    return sorted(unresolved)


def _v32_scientific_challenge_status(run_dir: Path) -> dict[str, Any]:
    """返回 v3.2 科学挑战的证据状态，不依赖 v3.1 ``summary.json``。

    已发现的高风险不会被此函数隐藏：它们允许透明论文进入盲评和网页审核，
    但会持续令 ``submission_ready`` 为假，直到真实修复和重新挑战完成。
    """
    try:
        report_file = SCIENTIFIC_CHALLENGE_REPORT_PATH.as_posix()
        report_path = run_dir / SCIENTIFIC_CHALLENGE_REPORT_PATH
        if not report_path.is_file() or not report_path.read_text(encoding="utf-8").strip():
            raise ContractError("缺少非空的 review/SCIENTIFIC_CHALLENGE.md")

        from shumozizi.simple.modeling_units import require_v32_experiment_evidence
        from shumozizi.simple.review_focus import verify_scientific_challenge_evidence
        from shumozizi.simple.review_tasks import validate_review_task_receipt

        # 开放的模型级发现会立即撤销其绑定结果，因此必须先报告发现本身，
        # 不能让后续“结果已失效”校验掩盖真正的回退原因。
        raw_challenge = load_json(run_dir / "review" / "scientific-challenge-evidence.json")
        raw_blocking = [
            item
            for item in raw_challenge.get("findings", [])
            if item.get("status") == "open"
            and item.get("action_type")
            in {"MODEL_REPAIR", "OBJECTIVE_REDESIGN", "ANSWER_REJECTION"}
        ]
        if raw_blocking:
            detail = ", ".join(
                f"{item['finding_id']}→{item['rollback_target']}"
                for item in raw_blocking
            )
            raise ContractError("科学挑战发现要求回退，不能进入 paper: " + detail)

        require_v32_experiment_evidence(run_dir)
        challenge_evidence = verify_scientific_challenge_evidence(run_dir)
        if not challenge_evidence["valid"]:
            raise ContractError(
                "科学挑战实际攻击证据已失效: " + "；".join(challenge_evidence["errors"])
            )
        blocking_findings = challenge_evidence.get("blocking_findings", [])
        if blocking_findings:
            detail = ", ".join(
                f"{item['finding_id']}→{item['rollback_target']}"
                for item in blocking_findings
            )
            raise ContractError("科学挑战发现要求回退，不能进入 paper: " + detail)

        receipts: list[dict[str, Any]] = []
        receipt_errors: list[str] = []
        tasks_root = run_dir / REVIEW_ROOT / "tasks"
        for receipt_path in sorted(tasks_root.rglob("receipt.json")):
            try:
                candidate = load_json(receipt_path)
                if (
                    not isinstance(candidate, dict)
                    or candidate.get("task_type") != "scientific_open"
                    or candidate.get("report_file") != report_file
                ):
                    continue
                bindings_path = receipt_path.parent / "input-bindings.json"
                if not bindings_path.is_file():
                    raise ContractError("科学挑战任务缺少 input-bindings.json")
                bindings = load_json(bindings_path)
                if not isinstance(bindings, dict):
                    raise ContractError("科学挑战任务输入绑定格式无效")
                packet = _verify_v32_frozen_packet_copy(
                    run_dir, bindings.get("packet"), expected_kind="scientific"
                )
                receipt = validate_review_task_receipt(
                    run_dir,
                    receipt_path.relative_to(run_dir).as_posix(),
                    expected_type="scientific_open",
                    expected_report=report_file,
                    expected_input_bindings=bindings,
                    require_fresh_thread=True,
                )
                receipts.append(
                    {
                        "receipt": receipt,
                        "receipt_file": receipt_path.relative_to(run_dir).as_posix(),
                        "packet": packet,
                    }
                )
            except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
                receipt_errors.append(str(exc))
        if not receipts:
            detail = "；".join(receipt_errors) if receipt_errors else "未找到绑定当前报告的 scientific_open 回执"
            raise ContractError("缺少有效的 v3.2 科学挑战 fresh-thread 回执: " + detail)

        selected = max(receipts, key=lambda item: item["receipt"]["completed_at"])
        unresolved = _v32_unresolved_high_severities(report_path.read_text(encoding="utf-8"))
        submission_ready = not unresolved
        return {
            "allowed": True,
            "submission_ready": submission_ready,
            "competition_strength": "limited" if unresolved else "not_assessed",
            "unresolved_high_severities": unresolved,
            "review": {
                "report": {
                    "file": report_file,
                    "sha256": sha256_file(report_path),
                },
                "task_receipt": {
                    "file": selected["receipt_file"],
                    "task_id": selected["receipt"]["task_id"],
                    "thread_id": selected["receipt"]["thread_id"],
                },
                "packet": selected["packet"],
                "challenge_evidence": challenge_evidence["evidence"],
            },
            "reason": (
                "科学挑战仍有未解决高风险: " + ", ".join(unresolved)
                if unresolved
                else ""
            ),
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            "allowed": False,
            "submission_ready": False,
            "competition_strength": "unknown",
            "unresolved_high_severities": [],
            "reason": str(exc),
        }


def scientific_review_status(run_dir: Path) -> dict[str, Any]:
    """返回科学红队是否仍可作为论文放行依据。

    当逐问审查 (question_reviews) 存在时，全部必答问题 verdict=pass 才允许放行，
    单问证据不能替其他问题背书。
    """
    if _competition_first_run(run_dir):
        if is_competition_first_v32_state(read_simple_state(run_dir)):
            return _v32_scientific_challenge_status(run_dir)
        return _competition_scientific_review_status(run_dir)
    try:
        semantics = objective_semantics_review_status(run_dir)
        if not semantics["allowed"]:
            return {
                "allowed": False,
                "submission_ready": False,
                "competition_strength": "unknown",
                "reason": "目标语义预审未通过或已失效: " + semantics["reason"],
            }
        summary = read_review_summary(run_dir)
        review = summary["scientific_review"]
        current, reason = _review_current(run_dir, review, expected_kind="scientific")
        evidence_assessment = _verified_evidence_assessment(run_dir) if current else None
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
            and not review["full_rerun_required"]
        )
        question_reviews = review.get("question_reviews")
        if question_reviews is not None and allowed:
            # 逐问模式下，任一必答问题非 pass 即阻断
            failed = [
                item["question_id"]
                for item in question_reviews
                if item["verdict"] != "pass"
            ]
            if failed:
                allowed = False
                reason = "逐问审查未全部通过: " + ", ".join(failed)
        submission_ready = bool(
            allowed
            and review["competition_strength"] in {"qualified", "strong"}
            and evidence_assessment is not None
            and evidence_assessment["promotion_allowed"]
        )
        if question_reviews is not None and submission_ready:
            # 逐问模式下任一问题 competition_strength 不达标 → 不可提交
            weak_questions = [
                item["question_id"]
                for item in question_reviews
                if item["competition_strength"] not in {"qualified", "strong"}
            ]
            if weak_questions:
                submission_ready = False
        return {
            "allowed": allowed,
            "submission_ready": submission_ready,
            "competition_strength": review["competition_strength"],
            "question_reviews": question_reviews,
            "review": review,
            "reason": reason,
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {
            "allowed": False,
            "submission_ready": False,
            "competition_strength": "unknown",
            "reason": str(exc),
        }


def require_paper_generation_allowed(run_dir: Path) -> None:
    """要求当前源代码、输入和候选结果已通过独立科学红队。"""
    if _competition_first_run(run_dir):
        state = read_simple_state(run_dir)
        from shumozizi.simple.results import read_result_index

        current = {
            item["question_id"]
            for item in read_result_index(run_dir)["results"]
            if item.get("status") == "current"
            and item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
        }
        missing = sorted(set(state["required_questions"]) - current)
        if missing:
            raise ContractError("不能进入论文阶段：必答问题缺少 current production 结果: " + ", ".join(missing))
        if is_competition_first_v32_state(state):
            # v3.2 的真实路线竞争由 modeling units 的 compare 证据承载；
            # 不能以 v3.1 的单一 route_tournament 元数据缺失阻断论文。
            from shumozizi.simple.modeling_units import require_v32_experiment_evidence
            from shumozizi.simple.objective_consequences import (
                require_objective_consequences,
            )

            require_objective_consequences(run_dir)
            require_v32_experiment_evidence(run_dir)
            from shumozizi.simple.review_focus import stronger_alternative_status

            alternative = stronger_alternative_status(run_dir)
            if not alternative["allowed"]:
                raise ContractError(
                    "不能进入论文阶段：更强路线判断未闭合: " + alternative["reason"]
                )
        else:
            from shumozizi.simple.competition import require_route_tournament_for_paper

            require_route_tournament_for_paper(run_dir)
        challenge = scientific_review_status(run_dir)
        if not challenge["allowed"]:
            raise ContractError("不能进入论文阶段：科学挑战未通过或已失效: " + challenge["reason"])
        return
    status = scientific_review_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入论文阶段：独立科学红队未通过或已失效: " + status["reason"])


def record_paper_blind_review_skip(run_dir: Path, reason: str) -> Path:
    """显式记录无法执行 PDF 盲评的原因，避免静默跳过。

    Args:
        run_dir: 当前运行目录。
        reason: 无法创建独立盲评的具体原因。

    Returns:
        已写入的跳过说明路径。
    """
    if not reason.strip():
        raise ContractError("跳过 PDF 盲评必须记录具体原因")
    path = run_dir / REVIEW_ROOT / "PAPER_BLIND_REVIEW_SKIP.md"
    path.write_text("# PDF 盲评跳过说明\n\n" + reason.strip() + "\n", encoding="utf-8", newline="\n")
    return path


def _competition_paper_blind_review_status(run_dir: Path) -> dict[str, Any]:
    """返回 v3.1 PDF 盲评或其跳过说明是否允许继续机械 QA。

    跳过说明只保留无法开展盲评时的可追溯性，不能作为 ``complete`` 放行依据。
    """
    try:
        if is_competition_first_v32_state(read_simple_state(run_dir)):
            return _v32_paper_blind_review_status(run_dir)
        summary = read_review_summary(run_dir)
        review = summary.get("paper_blind_review")
        if review is None:
            skip = run_dir / REVIEW_ROOT / "PAPER_BLIND_REVIEW_SKIP.md"
            if skip.is_file() and len(skip.read_text(encoding="utf-8").strip()) > 32:
                return {"allowed": True, "skipped": True, "reason": "已显式记录 PDF 盲评跳过原因"}
            return {"allowed": False, "reason": "缺少独立 PDF 盲评或明确跳过原因"}
        current, reason = _competition_review_current(
            run_dir, review, expected_kind="paper-blind", task_type="paper_blind_open"
        )
        allowed = bool(current and review["verdict"] == "pass" and review["highest_severity"] not in {"P0", "P1"})
        return {"allowed": allowed, "review": review, "reason": reason if not allowed else ""}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def paper_blind_review_status(run_dir: Path) -> dict[str, Any]:
    """返回盲审是否仍可作为提交前放行依据。"""
    if _competition_first_run(run_dir):
        return _competition_paper_blind_review_status(run_dir)
    try:
        scientific = scientific_review_status(run_dir)
        if not scientific["allowed"]:
            return {"allowed": False, "reason": "科学红队未通过或已失效"}
        summary = read_review_summary(run_dir)
        review = summary["paper_blind_review"]
        if review is None:
            return {"allowed": False, "reason": "缺少独立 PDF 盲审"}
        current, reason = _review_current(run_dir, review, expected_kind="paper-blind")
        allowed = bool(
            current
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
        )
        return {"allowed": allowed, "review": review, "reason": reason}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def require_paper_blind_review_allowed(run_dir: Path) -> None:
    """要求当前 PDF 已通过盲审，或已记录可继续机械 QA 的跳过原因。"""
    status = paper_blind_review_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入机械终检：独立 PDF 盲审未通过或已失效: " + status["reason"])


def mechanical_qa_status(run_dir: Path) -> dict[str, Any]:
    """返回机械 QA 是否通过且仍绑定当前最终 PDF。

    机械 QA 必须由正式检查器生成，不接受手写 synthetic 单条检查。
    """
    try:
        state = read_simple_state(run_dir)
        mechanical = load_json(run_dir / "qa" / "mechanical-qa.json")
        pdf = run_dir / "paper" / "final.pdf"
        if (
            not isinstance(mechanical, dict)
            or mechanical.get("schema_version") != "1.0"
            or mechanical.get("run_id") != run_dir.name
            or mechanical.get("workflow") != state["workflow"]
            or mechanical.get("status") != "pass"
        ):
            return {"allowed": False, "reason": "机械 QA 未通过"}
        # 拒绝 synthetic 伪造：必须由真实检查器生成
        generator = mechanical.get("generator_id", "")
        if not generator or generator == "synthetic":
            return {"allowed": False, "reason": "机械 QA 必须由正式检查器生成，不接受手写伪造"}
        if not mechanical.get("generated_at"):
            return {"allowed": False, "reason": "机械 QA 缺少 generator_id 或 generated_at"}
        # 最低必要检查集合：与 run_final_checks.py 使用的稳定 ID 一致
        required_check_ids = {
            "state-phase", "paper-template-manifest", "paper-compile-receipt",
            "paper-blind-review-release", "pdf", "paper-structure-signals",
            "placeholders", "result-references", "numeric-consistency",
            "current-result-files", "current-figure-files", "contact-sheet",
            "central-metric-coherence",
        }
        if _competition_first_run(run_dir):
            required_check_ids.add("scientific-challenge-release")
            if is_competition_first_v32_state(state):
                required_check_ids.add("web-paper-audit-release")
        else:
            required_check_ids |= {
                "scientific-review-release", "competition-submission-release",
                "visualization-contract",
            }
        checks = mechanical.get("checks")
        if not isinstance(checks, list):
            return {"allowed": False, "reason": "机械 QA 缺少检查列表"}
        check_ids = {check.get("id", "") for check in checks}
        if "synthetic" in check_ids:
            return {"allowed": False, "reason": "机械 QA 包含 synthetic 伪造检查"}
        # 必须覆盖全部必要检查（issubset）
        if not required_check_ids.issubset(check_ids):
            missing_ids = required_check_ids - check_ids
            return {
                "allowed": False,
                "reason": f"机械 QA 缺少必要检查项: {', '.join(sorted(missing_ids))}",
            }
        if any(
            not isinstance(check, dict) or check.get("passed") is not True
            for check in checks
        ):
            return {"allowed": False, "reason": "机械 QA 存在未通过的检查记录"}
        if (
            mechanical.get("final_pdf") != "paper/final.pdf"
            or not pdf.is_file()
            or mechanical.get("final_pdf_sha256") != sha256_file(pdf)
        ):
            return {"allowed": False, "reason": "机械 QA 未绑定当前最终 PDF"}
        return {"allowed": True, "reason": "", "mechanical_qa": mechanical}
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": "机械 QA 无法读取: " + str(exc)}


def require_mechanical_qa_allowed(run_dir: Path) -> None:
    """要求当前 PDF 的机械 QA 已全部通过。"""
    status = mechanical_qa_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入最终交付审核：" + status["reason"])


def require_final_review_allowed(run_dir: Path) -> None:
    """要求前两轮独立审核和机械 QA 均仍绑定当前交付物。"""
    require_paper_blind_review_allowed(run_dir)
    require_mechanical_qa_allowed(run_dir)


def final_audit_status(run_dir: Path) -> dict[str, Any]:
    """返回第三轮最终交付审核是否仍可作为完成依据。"""
    try:
        require_final_review_allowed(run_dir)
        summary = read_review_summary(run_dir)
        review = summary.get("final_audit")
        if review is None:
            return {"allowed": False, "reason": "缺少独立最终交付审核"}
        current, reason = _review_current(run_dir, review, expected_kind="final-audit")
        reviewer_threads = {
            summary["scientific_review"]["reviewer"]["thread_id"],
            summary["paper_blind_review"]["reviewer"]["thread_id"],
            review["reviewer"]["thread_id"],
        }
        distinct_reviewers = len(reviewer_threads) == 3
        allowed = bool(
            current
            and distinct_reviewers
            and review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
        )
        if current and not distinct_reviewers:
            reason = "三轮独立审核未使用三个不同对话"
        return {"allowed": allowed, "review": review, "reason": reason}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def competition_submission_status(run_dir: Path) -> dict[str, Any]:
    """区分科学可用与竞赛可提交，避免 weak 结果被标记为 complete。"""
    scientific = scientific_review_status(run_dir)
    if _competition_first_run(run_dir):
        submission_ready = bool(scientific.get("submission_ready", scientific["allowed"]))
        return {
            "scientific_valid": scientific["allowed"],
            "competition_strength": scientific.get("competition_strength", "unknown"),
            "submission_ready": submission_ready,
            "status": (
                "submission_ready"
                if submission_ready
                else (
                    "scientifically_valid_but_not_submission_ready"
                    if scientific["allowed"]
                    else "scientific_challenge_unavailable"
                )
            ),
            "reason": scientific.get("reason", ""),
        }
    if not scientific["allowed"]:
        return {
            "scientific_valid": False,
            "competition_strength": scientific.get("competition_strength", "unknown"),
            "submission_ready": False,
            "status": "scientific_review_unavailable",
            "reason": scientific["reason"],
        }
    strength = scientific["competition_strength"]
    if strength not in {"qualified", "strong"}:
        return {
            "scientific_valid": True,
            "competition_strength": strength,
            "submission_ready": False,
            "status": "scientifically_valid_but_not_competitive",
            "reason": f"科学结果可写成论文但竞争力为 {strength}，不能标记 complete",
        }
    return {
        "scientific_valid": True,
        "competition_strength": strength,
        "submission_ready": True,
        "status": "submission_ready",
        "reason": "",
    }


def completion_status(run_dir: Path) -> dict[str, Any]:
    """组合当前审核、事实产物与机械 QA，形成唯一的 complete 放行结论。"""
    if _competition_first_run(run_dir):
        scientific = scientific_review_status(run_dir)
        if not scientific["allowed"]:
            return {
                "allowed": False,
                "reason": "科学挑战未通过或已因生产事实变化而失效: "
                + scientific["reason"],
                "scientific_valid": False,
                "competition_strength": scientific.get("competition_strength", "unknown"),
                "submission_ready": False,
                "status": "scientific_challenge_unavailable",
            }
        if not scientific.get("submission_ready", scientific["allowed"]):
            return {
                "allowed": False,
                "reason": "科学挑战存在未解决的提交风险: " + scientific.get("reason", ""),
                "scientific_valid": True,
                "competition_strength": scientific.get("competition_strength", "unknown"),
                "submission_ready": False,
                "status": "not_submission_ready",
                "completion_status": "not_submission_ready",
            }
        paper = _competition_paper_blind_review_status(run_dir)
        if not paper["allowed"]:
            return {"allowed": False, "reason": paper["reason"]}
        if paper.get("skipped") is True:
            execution_mode = read_simple_state(run_dir)["execution_mode"]
            if execution_mode == "production":
                reason = "生产运行虽已记录 PDF 盲评跳过原因，但未完成独立盲评，不能标记 complete"
            else:
                reason = "探索运行已记录 PDF 盲评跳过原因，只能维持 unreviewed，不能标记 complete"
            return {
                "allowed": False,
                "reason": reason,
                "scientific_valid": True,
                "competition_strength": scientific.get("competition_strength", "unknown"),
                "submission_ready": False,
                "status": "unreviewed",
                "completion_status": "unreviewed",
            }
        if is_competition_first_v32_state(read_simple_state(run_dir)):
            from shumozizi.knowledge.external_discussion import (
                validate_web_paper_audit_if_present,
                web_paper_audit_started,
                web_paper_audit_status,
            )

            # 网页审核可选：未发起时不构成完成门，已发起则必须闭合到放行状态，
            # 否则会出现"发起审核后弃之不管即可完成"的绕过路径。
            if web_paper_audit_started(run_dir):
                web_audit = web_paper_audit_status(run_dir)
                if not web_audit["allowed"]:
                    return {"allowed": False, "reason": web_audit["reason"]}
            else:
                try:
                    validate_web_paper_audit_if_present(run_dir)
                except (ContractError, OSError, TypeError, ValueError) as exc:
                    return {"allowed": False, "reason": str(exc)}
        mechanical = mechanical_qa_status(run_dir)
        if not mechanical["allowed"]:
            return {"allowed": False, "reason": mechanical["reason"]}
        if is_competition_first_v32_state(read_simple_state(run_dir)):
            from shumozizi.paper.cumcm_adapter import require_cumcm_layout_audit

            try:
                require_cumcm_layout_audit(run_dir)
            except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
                return {"allowed": False, "reason": str(exc)}
        from shumozizi.simple.figures import verify_current_figure_files
        from shumozizi.simple.results import verify_current_result_files

        results = verify_current_result_files(run_dir)
        if not results["success"]:
            return {"allowed": False, "reason": "当前结果已漂移"}
        figures = verify_current_figure_files(run_dir)
        if not figures["success"]:
            return {"allowed": False, "reason": "当前图表已漂移"}
        return {
            "allowed": True,
            "reason": "",
            "scientific_valid": True,
            "competition_strength": scientific.get("competition_strength", "unknown"),
            "submission_ready": True,
            "status": "submission_ready",
            "completion_status": "complete",
        }
    review = final_audit_status(run_dir)
    if not review["allowed"]:
        return {"allowed": False, "reason": review["reason"]}
    competition = competition_submission_status(run_dir)
    if not competition["submission_ready"]:
        return {"allowed": False, **competition}
    return {
        "allowed": True,
        "reason": "",
        "scientific_valid": True,
        "competition_strength": competition["competition_strength"],
        "submission_ready": True,
        "status": "submission_ready",
    }


def require_completion_allowed(run_dir: Path) -> None:
    """要求三轮独立审查与机械 QA 同时通过，禁止仅凭 PDF 交付。"""
    status = completion_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能标记 complete：" + status["reason"])
