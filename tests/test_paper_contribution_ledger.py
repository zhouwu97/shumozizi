"""验证论文贡献账本只允许证据支持的题目特定数学贡献。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.paper.contributions import (
    build_contribution_ledger,
    require_math_innovation_allowed,
)


def _write_state(run_dir: Path) -> None:
    """写入贡献账本测试所需的最小 production 状态。"""
    atomic_json(
        run_dir / "state" / "run.json",
        {
            "schema_version": "3.0",
            "run_id": run_dir.name,
            "workflow": "capability-first-v3",
            "phase": "paper",
            "execution_mode": "production",
            "revision": 5,
            "competition": "synthetic",
            "problem_id": "contribution-ledger",
            "required_questions": ["Q1"],
            "current_question": "Q1",
            "completed_questions": ["Q1"],
            "selected_route": "route-a",
            "fallback_route": None,
            "artifacts": {},
            "time_budget": {"total_hours": 1, "remaining_hours": 0.4},
            "token_budget": {"soft_cap": 1000, "used_estimate": 200},
            "updated_at": "2026-07-22T00:00:00Z",
        },
    )


def test_generic_quality_protocol_is_downgraded_not_math_innovation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """通用质量协议即使关联有效结果也不能包装为题目数学创新。"""
    run_dir = tmp_path / "ledger-run"
    _write_state(run_dir)
    monkeypatch.setattr(
        "shumozizi.paper.contributions.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    ledger = build_contribution_ledger(
        run_dir,
        contributions=[
            {
                "contribution_id": "C-Q1-QUALITY",
                "category": "algorithm_design",
                "statement": "使用统一质量协议保证流程可审计。",
                "source_scope": "quality_protocol",
                "evidence_result_ids": ["Q1-R1"],
                "limitations": ["该协议不改变本题的数学模型或求解机制。"],
                "requested_math_innovation": True,
            }
        ],
    )

    entry = ledger["contributions"][0]
    assert entry["status"] == "downgraded_to_method_combination"
    assert not entry["math_innovation_allowed"]
    assert ledger["innovation_disclosure"]["mode"] == "method_combination_engineering"


def test_tampered_generic_entry_cannot_be_read_as_math_innovation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """读取接口必须重新拒绝被篡改的通用流程创新声明。"""
    run_dir = tmp_path / "tampered-ledger-run"
    _write_state(run_dir)
    monkeypatch.setattr(
        "shumozizi.paper.contributions.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )
    ledger = build_contribution_ledger(
        run_dir,
        contributions=[
            {
                "contribution_id": "C-Q1-QUALITY",
                "category": "algorithm_design",
                "statement": "使用统一质量协议保证流程可审计。",
                "source_scope": "quality_protocol",
                "evidence_result_ids": ["Q1-R1"],
                "limitations": ["该协议不改变本题的数学模型或求解机制。"],
                "requested_math_innovation": True,
            }
        ],
    )
    ledger["contributions"][0].update(
        {
            "status": "accepted_problem_specific",
            "math_innovation_allowed": True,
        }
    )

    with pytest.raises(ContractError, match="不得包装为题目数学创新"):
        require_math_innovation_allowed(run_dir, ledger, "C-Q1-QUALITY")


def test_problem_specific_math_innovation_requires_auditable_evidence_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """数学创新声明缺少机制到消融的证据链时必须降级。"""
    run_dir = tmp_path / "missing-innovation-chain"
    _write_state(run_dir)
    monkeypatch.setattr(
        "shumozizi.paper.contributions.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    ledger = build_contribution_ledger(
        run_dir,
        contributions=[
            {
                "contribution_id": "C-Q1-STRUCTURE",
                "category": "structural_discovery",
                "statement": "利用本题耦合结构将原模型拆为两个可验证子问题。",
                "source_scope": "problem_specific",
                "evidence_result_ids": ["Q1-R1"],
                "limitations": ["该结论只在当前数据范围内验证。"],
                "requested_math_innovation": True,
            }
        ],
    )

    entry = ledger["contributions"][0]
    assert entry["status"] == "downgraded_missing_innovation_evidence"
    assert not entry["math_innovation_allowed"]


def test_problem_specific_math_innovation_accepts_current_evidence_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """完整的题目特定机制到消融链可获得有限的创新写作权限。"""
    run_dir = tmp_path / "complete-innovation-chain"
    _write_state(run_dir)
    monkeypatch.setattr(
        "shumozizi.paper.contributions.quality_allows_paper",
        lambda _run_dir, result_id: result_id in {"Q1-BASE", "Q1-NEW", "Q1-ABLATE"},
    )

    ledger = build_contribution_ledger(
        run_dir,
        contributions=[
            {
                "contribution_id": "C-Q1-STRUCTURE",
                "category": "algorithm_design",
                "statement": "针对稀疏转折区域引入局部重采样机制。",
                "source_scope": "problem_specific",
                "evidence_result_ids": ["Q1-BASE", "Q1-NEW", "Q1-ABLATE"],
                "limitations": ["机制只在本题声明的稀疏区域上进行了验证。"],
                "requested_math_innovation": True,
                "innovation_evidence": {
                    "evidence_mode": "distinct_results",
                    "primary_result_id": "Q1-NEW",
                    "mechanism_difference": "只在结构预检识别的稀疏转折区域重采样。",
                    "testable_prediction": "局部重采样应降低转折区域的精确目标误差。",
                    "comparison_metric": "objective_error",
                    "comparison_direction": "lower_is_better",
                    "comparison_improvement": "Q1-NEW 相对 Q1-BASE 在目标误差上改善。",
                    "single_component_ablation": "移除局部重采样后，Q1-ABLATE 的改善消失。",
                    "comparison_result_ids": ["Q1-BASE", "Q1-NEW"],
                    "ablation_result_ids": ["Q1-NEW", "Q1-ABLATE"],
                },
            }
        ],
    )

    entry = require_math_innovation_allowed(run_dir, ledger, "C-Q1-STRUCTURE")
    assert entry["innovation_evidence"]["evidence_valid"]


def test_math_innovation_can_bind_distinct_exact_artifacts_of_current_primary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """同组 registry 只有一个 incumbent 时，可用其精评附属产物表达对照和消融。"""
    run_dir = tmp_path / "artifact-innovation-chain"
    _write_state(run_dir)
    monkeypatch.setattr(
        "shumozizi.paper.contributions.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-PRIMARY",
    )
    monkeypatch.setattr(
        "shumozizi.paper.contributions.read_result_index",
        lambda _run_dir: {
            "results": [
                {
                    "result_id": "Q1-PRIMARY",
                    "output_hashes": {
                        "results/raw/q1-comparison.json": "a" * 64,
                        "results/raw/q1-ablation.json": "b" * 64,
                    },
                }
            ]
        },
    )

    ledger = build_contribution_ledger(
        run_dir,
        contributions=[
            {
                "contribution_id": "C-Q1-ARTIFACT",
                "category": "algorithm_design",
                "statement": "针对稀疏转折区域引入局部重采样机制。",
                "source_scope": "problem_specific",
                "evidence_result_ids": ["Q1-PRIMARY"],
                "limitations": ["只在当前题目声明的稀疏区域上验证。"],
                "requested_math_innovation": True,
                "innovation_evidence": {
                    "evidence_mode": "exact_artifacts",
                    "primary_result_id": "Q1-PRIMARY",
                    "mechanism_difference": "只在结构预检识别的稀疏转折区域重采样。",
                    "testable_prediction": "局部重采样应降低转折区域的精确目标误差。",
                    "comparison_metric": "objective_error",
                    "comparison_direction": "lower_is_better",
                    "comparison_improvement": "受控对照产物记录局部目标误差改善。",
                    "single_component_ablation": "单组件消融产物记录移除重采样后的改善消失。",
                    "comparison_artifact_files": ["results/raw/q1-comparison.json"],
                    "ablation_artifact_files": ["results/raw/q1-ablation.json"],
                },
            }
        ],
    )

    entry = require_math_innovation_allowed(run_dir, ledger, "C-Q1-ARTIFACT")
    assert entry["innovation_evidence"]["evidence_mode"] == "exact_artifacts"


def test_math_innovation_cannot_use_one_result_as_control_and_ablation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """同一结果不能伪装成新机制、对照改善和单组件消融的全部证据。"""
    run_dir = tmp_path / "self-certifying-innovation-chain"
    _write_state(run_dir)
    monkeypatch.setattr(
        "shumozizi.paper.contributions.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    with pytest.raises(ContractError, match="对照.*独立"):
        build_contribution_ledger(
            run_dir,
            contributions=[
                {
                    "contribution_id": "C-Q1-SELF",
                    "category": "algorithm_design",
                    "statement": "声称局部机制改善了本题目标。",
                    "source_scope": "problem_specific",
                    "evidence_result_ids": ["Q1-R1"],
                    "limitations": ["没有其他独立运行。"],
                    "requested_math_innovation": True,
                    "innovation_evidence": {
                        "evidence_mode": "distinct_results",
                        "primary_result_id": "Q1-R1",
                        "mechanism_difference": "增加局部重采样。",
                        "testable_prediction": "目标误差会下降。",
                        "comparison_metric": "objective_error",
                        "comparison_direction": "lower_is_better",
                        "comparison_improvement": "Q1-R1 优于 Q1-R1。",
                        "single_component_ablation": "移除组件后仍引用 Q1-R1。",
                        "comparison_result_ids": ["Q1-R1"],
                        "ablation_result_ids": ["Q1-R1"],
                    },
                }
            ],
        )
