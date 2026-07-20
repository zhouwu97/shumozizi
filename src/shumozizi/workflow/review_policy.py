"""定义各独立审核阶段不可由调用者削减的材料和质量策略。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json
from shumozizi.profiles.lock import verify_run_config_lock

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
        "optional_inputs": [],
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
        "optional_inputs": ["figure_plan", "figure_receipts", "failure_samples"],
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
        "optional_inputs": ["figure_plan"],
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
            "submission_manifest",
            "final_pdf",
            "source_manifest",
        ],
        "optional_inputs": ["paper_source"],
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
            "evidence_report",
            "source_manifest",
        ],
        "optional_inputs": ["paper_plan", "submission_manifest", "source_archive"],
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
        "quality_dimensions": ["题目覆盖", "模型深度", "实验验证", "论文表达", "图表质量"],
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
    stage: str, run_dir: Path | None = None
) -> dict[str, Any]:
    """返回阶段策略；J0 的评委可见角色来自冻结比赛 Profile。"""
    policy = deepcopy(REVIEW_STAGE_POLICIES[stage])
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
