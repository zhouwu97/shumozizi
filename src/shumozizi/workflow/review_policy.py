"""定义各独立审核阶段不可由调用者削减的材料和质量策略。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json
from shumozizi.profiles.lock import verify_run_config_lock

REVIEW_MODES = (
    "full_scientific",
    "targeted_recheck",
    "diff_check",
    "machine_check",
)
FINDING_CONFIDENCE_LEVELS = ("low", "medium", "high")
FINDING_STATUSES = ("open", "deferred_empirical")
FINDING_DOMAINS = ("scientific", "machine")
VERIFICATION_MODES = (
    "targeted_recheck",
    "diff_check",
    "machine_check",
    "human_decision",
    "none",
)
DEFERRED_BLOCK_POINTS = (
    "formal_experiment",
    "model_selection",
    "paper_claim",
    "final_submission",
)

_SCOPED_FORBIDDEN_INPUTS = [
    "problem/",
    "problems/",
    "brief/",
    "results/",
    "paper/",
    "src/",
    "scripts/",
    "review_report.json",
    "review_receipt.json",
]

REVIEW_MODE_POLICIES: dict[str, dict[str, Any]] = {
    "targeted_recheck": {
        "mandatory_inputs": [
            "original_finding",
            "source_adjudication",
            "before_after_diff",
            "repair_evidence",
            "direct_dependencies",
        ],
        "optional_inputs": [],
        "forbidden_inputs": _SCOPED_FORBIDDEN_INPUTS,
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["原 finding 未关闭", "修改引入新的 P0/P1"],
        "quality_dimensions": ["原问题关闭", "修改范围", "直接依赖"],
    },
    "diff_check": {
        "mandatory_inputs": [
            "original_finding",
            "source_adjudication",
            "before_after_diff",
            "repair_evidence",
        ],
        "optional_inputs": ["direct_dependencies"],
        "forbidden_inputs": _SCOPED_FORBIDDEN_INPUTS,
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["修改超出声明范围", "证据未对应修改"],
        "quality_dimensions": ["差异范围", "修复证据"],
    },
    "machine_check": {
        "mandatory_inputs": [
            "original_finding",
            "source_adjudication",
            "machine_evidence",
        ],
        "optional_inputs": ["repair_evidence"],
        "forbidden_inputs": _SCOPED_FORBIDDEN_INPUTS,
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["机器证据不可复验", "确定性检查仍失败"],
        "quality_dimensions": ["确定性复验", "证据完整性"],
    },
}
SUPPLEMENTAL_EVIDENCE_ROLE_PREFIX = "supplemental_evidence:"

REVIEW_STAGE_POLICIES: dict[str, dict[str, Any]] = {
    "R1_MODELING": {
        "mandatory_inputs": [
            "problem_source",
            "problem_attachments_manifest",
            "problem_manifest",
            "run_config_lock",
            "route_candidates",
            "route_lock",
            "model_spec",
            "data_dictionary",
            "data_profile",
            "validation_plan",
        ],
        "optional_inputs": [
            "phase_a",
            "scientific_viability",
            "supplemental_evidence_manifest",
        ],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["题意错误", "变量或约束不可计算", "必做问题遗漏"],
        "quality_dimensions": ["路线竞争力", "机制差异", "模型适配性", "可证伪性"],
    },
    "R2_EXPERIMENT": {
        "mandatory_inputs": [
            "problem_source",
            "problem_manifest",
            "question_contract",
            "model_spec",
            "data_snapshot_manifest",
            "environment_lock",
            "execution_manifest",
            "execution_record",
            "source_code",
            "metric_specs",
            "result_registry",
            "sealed_result",
            "baseline_results",
            "robustness_results",
        ],
        "optional_inputs": [
            "figure_plan",
            "figure_receipts",
            "failure_samples",
            "scientific_viability",
            "supplemental_evidence_manifest",
        ],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["无法复现", "指标不对应题意", "约束失败", "数据泄漏"],
        "quality_dimensions": ["基线公平性", "实验辨识力", "稳健性", "实际意义"],
    },
    "R3_PAPER_LOGIC": {
        "mandatory_inputs": [
            "problem_source",
            "problem_manifest",
            "model_spec",
            "question_acceptance",
            "result_registry",
            "sealed_results_manifest",
            "claim_gate",
            "claim_evidence",
            "evidence_map",
            "paper_plan",
            "paper_source",
            "figure_receipts",
            "bibliography",
            "final_pdf",
        ],
        "optional_inputs": [
            "figure_plan",
            "scientific_viability",
            "supplemental_evidence_manifest",
        ],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["某问未直接回答", "数字无证据", "重大推导错误"],
        "quality_dimensions": ["推导深度", "逐问递进", "结果解释", "摘要与结论"],
    },
    "R4_FORMAT_VISUAL": {
        "mandatory_inputs": [
            "competition_rules",
            "official_template",
            "run_config_lock",
            "paper_plan",
            "paper_build_receipt",
            "figure_plan",
            "figure_receipts",
            "font_report",
            "rendered_pages_manifest",
            "format_audit",
            "submission_manifest",
            "final_pdf",
            "source_manifest",
        ],
        "optional_inputs": ["paper_source", "supplemental_evidence_manifest"],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["匿名失败", "页面或模板违规", "公式图表裁切", "提交包缺失"],
        "quality_dimensions": ["机械合规", "图表清晰度", "页面密度", "黑白可辨性"],
    },
    "R5_COMPREHENSIVE": {
        "mandatory_inputs": [
            "problem_source",
            "problem_attachments_manifest",
            "problem_manifest",
            "run_config_lock",
            "model_spec",
            "result_registry",
            "sealed_results_manifest",
            "source_code",
            "reproduction_entrypoint",
            "final_pdf",
            "qa_report",
            "format_audit",
            "evidence_report",
            "source_manifest",
        ],
        "optional_inputs": [
            "paper_plan",
            "submission_manifest",
            "source_archive",
            "scientific_viability",
            "supplemental_evidence_manifest",
        ],
        "forbidden_inputs": [
            "review/r1_modeling/",
            "review/r2_experiment/",
            "review/r3_paper_logic/",
            "review/r4_format_visual/",
            "review/r5_comprehensive/",
        ],
        "required_outputs": [
            "integrity_axis",
            "quality_axis",
            "joint_verdict",
            "repair_scope",
            "required_retests",
        ],
        "hard_blocks": ["A_BLOCKED", "重大模型错误", "某问基本未回答", "虚假创新"],
        "quality_dimensions": [
            "题目覆盖",
            "模型深度",
            "实验验证",
            "论文表达",
            "图表质量",
            "judge_readability",
            "overall_persuasiveness",
            "award_competitiveness",
        ],
    },
    "J0_FINAL_BLIND_JUDGE": {
        "mandatory_inputs": [
            "problem_source",
            "problem_attachments_manifest",
            "competition_rules",
            "final_pdf",
            "submission_manifest",
        ],
        "optional_inputs": [],
        "forbidden_inputs": [
            "review/r1_",
            "review/r2_",
            "review/r3_",
            "review/r4_",
            "review/r5_",
            "model_spec.json",
            "result_registry.json",
            "source/SOURCE_MANIFEST.json",
            "qa_report.json",
            "evidence_report.json",
        ],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["某问未回答", "结论明显错误", "不具备提交质量"],
        "quality_dimensions": ["自然评委可读性", "完整性", "说服力", "整体奖项竞争力"],
    },
}


def get_review_stage_policy(
    stage: str,
    run_dir: Path | None = None,
    *,
    question_id: str | None = None,
    review_mode: str = "full_scientific",
) -> dict[str, Any]:
    """返回审核模式策略；full 模式再按阶段冻结完整材料。"""
    if review_mode not in REVIEW_MODES:
        raise ContractError(f"未知审核模式: {review_mode}")
    if review_mode != "full_scientific":
        return deepcopy(REVIEW_MODE_POLICIES[review_mode])
    policy = deepcopy(REVIEW_STAGE_POLICIES[stage])
    if stage == "R3_PAPER_LOGIC" and question_id is not None:
        policy["mandatory_inputs"] = [
            "problem_source",
            "problem_manifest",
            "model_spec",
            "result_registry",
            "claim_evidence",
            "paper_source",
        ]
        policy["optional_inputs"] = [
            "question_acceptance",
            "sealed_results_manifest",
            "claim_gate",
            "evidence_map",
            "paper_plan",
            "figure_receipts",
            "bibliography",
            "final_pdf",
            "figure_plan",
        ]
    if stage != "J0_FINAL_BLIND_JUDGE" or run_dir is None:
        return policy
    repo_root = run_dir.parent.parent
    lock = verify_run_config_lock(repo_root, run_dir)
    profile_path = repo_root / lock["competition_profile"]["profile_path"]
    profile = load_json(profile_path)
    roles = profile.get("judge_visible_roles")
    if roles is None:
        roles = [
            "problem_source",
            "problem_attachments_manifest",
            "competition_rules",
            "final_pdf",
            "submission_manifest",
        ]
        if any(
            path != "paper/final.pdf" for path in profile["required_submission_files"]
        ):
            roles.append("allowed_submission_attachments")
    allowed = {
        "problem_source",
        "problem_attachments_manifest",
        "competition_rules",
        "final_pdf",
        "submission_manifest",
        "allowed_submission_attachments",
        "submission_code",
        "commitment_statement",
        "ai_use_statement",
    }
    unknown = sorted(set(roles) - allowed)
    if unknown:
        raise ContractError("冻结 Profile 包含不受支持的 J0 可见角色: " + ", ".join(unknown))
    policy["mandatory_inputs"] = list(roles)
    return policy


def review_material_role_allowed(role: str, policy: dict[str, Any]) -> bool:
    """允许固定策略角色及经过冻结清单约束的动态补充证据角色。"""
    fixed = set(policy["mandatory_inputs"]) | set(policy["optional_inputs"])
    return role in fixed or role.startswith(SUPPLEMENTAL_EVIDENCE_ROLE_PREFIX)
