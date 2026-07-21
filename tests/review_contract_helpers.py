"""独立审核协议测试的阶段材料与 session 夹具。"""

from __future__ import annotations

from pathlib import Path

import yaml

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.qa.visual import audit_pdf_format
from shumozizi.workflow.review_policy import get_review_stage_policy
from shumozizi.workflow.review_sessions import claim_review_request
from shumozizi.workflow.reviews import write_review_adjudication
from shumozizi.workflow.viability import (
    create_minimum_scientific_contract,
    create_scientific_viability,
)


def write_minimum_scientific_contract_fixture(run_dir: Path) -> Path:
    """写入可通过正式实验门的最低科学合同夹具。"""
    candidates = (
        run_dir / "brief/model_spec.json",
        run_dir / "reports/model_spec.md",
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        source = run_dir / "analysis/contract-source.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("frozen test contract source\n", encoding="utf-8")
    target = run_dir / "analysis/MINIMUM_SCIENTIFIC_CONTRACT.md"
    if target.exists():
        return target
    return create_minimum_scientific_contract(
        run_dir,
        source_paths=[source],
        values={
            "required_outputs": ["Q1 直接答案"],
            "core_objective": "最小化冻结验证集误差",
            "hard_constraints": ["输出满足题目单位与可行域"],
            "baseline": "冻结均值 baseline",
            "primary_model_family": "冻结统计模型族",
            "data_split": "固定训练验证划分",
            "primary_metrics": ["验证误差"],
            "positive_control": "已知真值合成恢复",
            "route_failure_criterion": "正控制无法达到题目误差要求",
            "fallback_trigger": "正控制失败后启动已批准 baseline",
            "experiment_budget": "最多 60 分钟与 20 次拟合",
        },
    )


def write_viable_scientific_viability_fixture(run_dir: Path) -> Path:
    """写入可通过正式全文门的单风险 viability 夹具。"""
    source = run_dir / "results/viability-summary.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("positive control and baseline comparison passed\n", encoding="utf-8")
    target = run_dir / "analysis/SCIENTIFIC_VIABILITY.md"
    if not target.exists():
        create_scientific_viability(
            run_dir,
            question_scope=["q1"],
            source_paths=[source],
        )
    text = target.read_text(encoding="utf-8")
    marker = text.find("\n---\n", 4)
    metadata = yaml.safe_load(text[4:marker])
    metadata.update(
        {
            "verdict": "VIABLE",
            "evaluated_at": "2026-07-21T00:00:00Z",
            "threshold_basis": "题目误差要求与冻结 baseline",
            "highest_risk": "模型可能无法恢复题目要求输出",
            "counterexample": "已知真值正例恢复失败会推翻路线",
            "falsification_experiment": "运行冻结正例并与 baseline 比较",
            "experiment_result": "真实夹具结果通过冻结阈值",
            "baseline_fallback_comparison": "primary 优于 baseline，无需启动 fallback",
            "decision_reason": "正控制和直接答案均支持继续",
            "next_action": "进入正式全文并保持稳健性边界",
            "action_status": "completed",
            "remaining_time_minutes": 120,
            "investment_limit_minutes": 30,
        }
    )
    header = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    target.write_text(
        f"---\n{header}\n---\n{text[marker + 5:]}",
        encoding="utf-8",
        newline="\n",
    )
    return target


def write_passing_format_audit(run_dir: Path, final_pdf: Path) -> Path:
    """写入与当前 PDF 绑定的无硬失败格式审计测试夹具。"""
    path = run_dir / "review" / "FORMAT_AUDIT.json"
    atomic_json(
        path,
        {
            "schema_name": "format_audit",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "profile_id": "generic",
            "final_pdf_path": final_pdf.relative_to(run_dir).as_posix(),
            "final_pdf_sha256": sha256_file(final_pdf),
            "page_count": 1,
            "page_sizes": [
                {
                    "page": 1,
                    "width_pt": 595.276,
                    "height_pt": 841.89,
                    "a4": True,
                }
            ],
            "file_size_bytes": final_pdf.stat().st_size,
            "measured_margins_cm": {
                "required_cm": 2.5,
                "pages": [],
                "minimum": {
                    "left_cm": 2.5,
                    "right_cm": 2.5,
                    "top_cm": 2.5,
                    "bottom_cm": 2.5,
                },
            },
            "summary_on_first_page": True,
            "keywords_present": True,
            "font_resources": [],
            "fonts_embedded": True,
            "body_font_size_distribution": {"10": 1},
            "caption_font_size_distribution": {},
            "figure_numbering_complete": True,
            "table_numbering_complete": True,
            "references_present": True,
            "citations_linked": False,
            "image_dpi": [],
            "clipping_detected": False,
            "overlap_detected": False,
            "anonymous_check": True,
            "checks": [],
            "hard_failures": [],
            "warnings": [],
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )
    return path


def complete_stage_bindings(
    run_dir: Path,
    stage: str,
    overrides: dict[str, Path] | None = None,
) -> dict[str, Path]:
    """为阶段策略补齐最小文件；语义相关材料应由调用方覆盖。"""
    bindings = dict(overrides or {})
    policy = get_review_stage_policy(stage, run_dir)
    for role in policy["mandatory_inputs"]:
        if role in bindings:
            continue
        if role == "format_audit":
            path = run_dir / "review" / "FORMAT_AUDIT.json"
            final_pdf = bindings.get("final_pdf")
            if final_pdf is not None and final_pdf.is_file():
                existing = load_json(path) if path.is_file() else None
                if not existing or existing.get("final_pdf_sha256") != sha256_file(final_pdf):
                    audit_pdf_format(run_dir, final_pdf)
                bindings[role] = path
                continue
            atomic_json(
                path,
                {
                    "schema_name": "format_audit",
                    "schema_version": "2.0",
                    "run_id": run_dir.name,
                    "profile_id": "generic",
                    "final_pdf_path": "paper/final.pdf",
                    "final_pdf_sha256": "0" * 64,
                    "page_count": 1,
                    "page_sizes": [{"page": 1, "width_pt": 595.276, "height_pt": 841.89, "a4": True}],
                    "file_size_bytes": 1,
                    "measured_margins_cm": {"required_cm": 2.5, "pages": [], "minimum": {"left_cm": 2.5, "right_cm": 2.5, "top_cm": 2.5, "bottom_cm": 2.5}},
                    "summary_on_first_page": True,
                    "keywords_present": True,
                    "font_resources": [],
                    "fonts_embedded": True,
                    "body_font_size_distribution": {"10": 1},
                    "caption_font_size_distribution": {},
                    "figure_numbering_complete": True,
                    "table_numbering_complete": True,
                    "references_present": True,
                    "citations_linked": False,
                    "image_dpi": [],
                    "clipping_detected": False,
                    "overlap_detected": False,
                    "anonymous_check": True,
                    "checks": [],
                    "hard_failures": [],
                    "warnings": [],
                    "generated_at": "2026-07-20T00:00:00Z",
                },
            )
            bindings[role] = path
            continue
        suffix = ".txt" if role in {"problem_source", "source_code", "paper_source"} else ".json"
        path = run_dir / "review-inputs" / stage.lower() / f"{role}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n" if suffix == ".txt" else "{}\n", encoding="utf-8")
        bindings[role] = path
    return bindings


def rich_r1_evidence(*, required_output_id: str = "q1-output") -> dict:
    """返回满足五项新增 R1 预检的结构化证据。"""
    return {
        "data_and_attachment_mapping": {
            "source_fields": [
                {
                    "source_ref": "attachment.xlsx:Sheet1",
                    "raw_field": "observed_y",
                    "variable": "y",
                    "source_unit": "dimensionless",
                    "model_unit": "dimensionless",
                    "conversion": "identity",
                }
            ],
            "derived_variables": [
                {
                    "name": "beta",
                    "formula": "beta = argmin RSS",
                    "unit": "dimensionless",
                }
            ],
            "missing_and_anomaly_handling": "缺失行拒绝，异常值保留并标记",
        },
        "equation_closure": {
            "equations": ["y = beta"],
            "declared_symbols": ["y", "beta"],
            "output_symbols": ["y"],
        },
        "stopping_rule": {
            "mode": "iterative",
            "max_iterations": 200,
            "tolerance": 1e-8,
            "convergence_condition": "目标函数相对变化小于 tolerance",
            "failure_handling": "记录不收敛状态并禁止结果准入",
            "fallback": "切换已批准的有界最小二乘求解器",
        },
        "baseline_design": {
            "baseline_id": "q1-mean-baseline",
            "input_equivalence": "与 primary 使用同一数据窗口和划分",
            "metrics": ["validation_rmse"],
            "comparison_rule": "validation_rmse 越小越优",
        },
        "evidence_plan": [
            {
                "required_output_id": required_output_id,
                "experiment_or_result_id": "Q1-P0",
                "table_or_figure_id": "table-q1-primary",
                "paper_section": "4.1",
            }
        ],
    }


def rich_model_spec(
    run_dir: Path,
    path: Path,
    *,
    route_sha256: str | None = None,
    required_output_id: str = "q1-output",
) -> Path:
    """写入满足 R1 最低结构证据预检的模型规格。"""
    atomic_json(
        path,
        {
            "schema_name": "model_spec",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "route_lock_sha256": route_sha256 or "0" * 64,
            "questions": [
                {
                    "question_id": "q1",
                    "model_family": "statistical",
                    "target_role": "target",
                    "feature_roles": ["feature"],
                    "variables": [
                        {"name": "y", "role": "target", "unit": "dimensionless"},
                        {"name": "beta", "role": "parameter", "unit": "dimensionless"},
                    ],
                    "assumptions": ["误差独立"],
                    "objective": "比较 baseline 与候选模型，选择 BIC 最小者",
                    "constraints": ["参数 beta 在有界范围 [0, 1] 内估计"],
                    "algorithm": "有界拟合并检查 Jacobian 条件数以说明参数可辨识性",
                    "validation_plan": [
                        "Bootstrap 重采样 200 次，报告参数 95% 置信区间"
                    ],
                    "r1_evidence": rich_r1_evidence(
                        required_output_id=required_output_id
                    ),
                }
            ],
        },
    )
    return path


def rich_problem_manifest(run_dir: Path, path: Path) -> Path:
    """写入与 ``rich_model_spec`` 对齐的最小权威问题清单。"""
    atomic_json(
        path,
        {
            "schema_name": "problem_manifest",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "run_config_lock_sha256": "0" * 64,
            "problem_source": {"path": "problems/sample.md", "sha256": "0" * 64},
            "questions": [
                {
                    "question_id": "q1",
                    "title": "测试问题",
                    "required": True,
                    "required_outputs": [
                        {
                            "output_id": "q1-output",
                            "description": "输出测试问题的模型结果",
                            "unit": "dimensionless",
                        }
                    ],
                    "depends_on": [],
                    "source_refs": ["problems/sample.md:1"],
                }
            ],
            "frozen_at": "2026-07-20T00:00:00Z",
        },
    )
    return path


def claim_and_hash(request_path: Path, thread_id: str) -> str:
    """领取审核请求并返回报告必须绑定的 session 哈希。"""
    session = claim_review_request(request_path, thread_id=thread_id)
    return sha256_file(session)


def adjudicate_report(report_path: Path) -> Path:
    """以生产主 AI 身份生成覆盖全部 finding 的测试裁决。"""
    report = load_json(report_path)
    request = load_json(report_path.with_name("review_request.json"))
    decisions = []
    for finding in report["findings"]:
        severity = finding["severity"]
        main_decision = "accepted" if severity in {"P0", "P1"} else "accepted_as_advisory"
        decisions.append(
            {
                "finding_id": finding["finding_id"],
                "reviewer_severity": severity,
                "main_decision": main_decision,
                "effective_severity": severity,
                "gate_effect": {
                    "accepted": "block",
                    "accepted_as_advisory": "warn",
                    "rejected": "none",
                }.get(main_decision, "block"),
                "decision_reason": "测试生产主 AI 独立核验结论",
                "confirmation_evidence": ["test:confirmation"]
                if main_decision == "accepted"
                else [],
                "counter_evidence": ["second-review:test"] if severity == "P0" else [],
                "resolution_evidence_type": None,
                "effective_change_level": finding["change_level"],
                "affected_questions": finding.get("affected_questions", []),
                "required_retests": finding.get("required_retests", []),
                "route_reapproval_required": finding["change_level"] == "L5",
            }
        )
    document = {
        "schema_name": "review_adjudication",
        "schema_version": "2.0",
        "run_id": report["run_id"],
        "request_id": report["request_id"],
        "stage": report["stage"],
        "state_revision": request["state_revision"],
        "review_report_sha256": sha256_file(report_path),
        "decisions": decisions,
        "unresolved_conflicts": [],
        "generated_by": "production_main_ai",
        "generated_at": "2026-07-20T00:00:00Z",
    }
    return write_review_adjudication(report_path, document)
