"""定义各独立审核阶段不可由调用者削减的材料和质量策略。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

REVIEW_STAGE_POLICIES: dict[str, dict[str, Any]] = {
    "R1_MODELING": {
        "mandatory_inputs": ["problem_manifest", "route_lock", "model_spec"],
        "optional_inputs": ["route_candidates", "validation_plan", "attachments_summary"],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["题意错误", "变量或约束不可计算", "必做问题遗漏"],
        "quality_dimensions": ["路线竞争力", "机制差异", "模型适配性", "可证伪性"],
    },
    "R2_EXPERIMENT": {
        "mandatory_inputs": [
            "model_spec",
            "execution_manifest",
            "execution_record",
            "source_code",
            "result_registry",
            "sealed_result",
        ],
        "optional_inputs": ["figure_plan", "figure_receipts", "failure_samples"],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["无法复现", "指标不对应题意", "约束失败", "数据泄漏"],
        "quality_dimensions": ["基线公平性", "实验辨识力", "稳健性", "实际意义"],
    },
    "R3_PAPER_LOGIC": {
        "mandatory_inputs": [
            "problem_manifest",
            "model_spec",
            "result_registry",
            "question_acceptance",
            "paper_plan",
            "final_pdf",
        ],
        "optional_inputs": ["claim_evidence", "evidence_map", "figure_plan", "paper_source"],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["某问未直接回答", "数字无证据", "重大推导错误"],
        "quality_dimensions": ["推导深度", "逐问递进", "结果解释", "摘要与结论"],
    },
    "R4_FORMAT_VISUAL": {
        "mandatory_inputs": [
            "run_config_lock",
            "paper_plan",
            "figure_plan",
            "final_pdf",
            "source_manifest",
        ],
        "optional_inputs": ["paper_source", "submission_manifest", "rendered_pages"],
        "forbidden_inputs": ["review_report.json", "review_receipt.json"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["匿名失败", "页面或模板违规", "公式图表裁切", "提交包缺失"],
        "quality_dimensions": ["机械合规", "图表清晰度", "页面密度", "黑白可辨性"],
    },
    "R5_COMPREHENSIVE": {
        "mandatory_inputs": [
            "problem_manifest",
            "run_config_lock",
            "result_registry",
            "paper_plan",
            "final_pdf",
            "qa_report",
            "evidence_report",
            "source_manifest",
        ],
        "optional_inputs": ["submission_manifest", "source_archive"],
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
            "problem_manifest",
            "final_pdf",
            "submission_manifest",
            "source_manifest",
        ],
        "optional_inputs": [],
        "forbidden_inputs": ["review/r1_", "review/r2_", "review/r3_", "review/r4_", "review/r5_"],
        "required_outputs": ["verdict", "findings"],
        "hard_blocks": ["某问未回答", "结论明显错误", "不具备提交质量"],
        "quality_dimensions": ["自然评委可读性", "完整性", "说服力", "整体奖项竞争力"],
    },
}


def get_review_stage_policy(stage: str) -> dict[str, Any]:
    """返回不可由调用者修改的阶段策略副本。"""
    return deepcopy(REVIEW_STAGE_POLICIES[stage])
