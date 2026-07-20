"""独立审核协议测试的阶段材料与 session 夹具。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, sha256_file
from shumozizi.workflow.review_policy import get_review_stage_policy
from shumozizi.workflow.review_sessions import claim_review_request


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
