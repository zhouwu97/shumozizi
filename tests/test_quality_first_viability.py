"""验证质量优先试点会改变路线行动，而不扩展状态机。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shumozizi.core.io import ContractError, load_json
from shumozizi.workflow.review_policy import (
    get_review_stage_policy,
    review_material_role_allowed,
)
from shumozizi.workflow.review_sessions import claim_review_request
from shumozizi.workflow.reviews import create_review_request
from shumozizi.workflow.viability import (
    create_minimum_scientific_contract,
    create_scientific_viability,
    freeze_supplemental_evidence,
    r5_review_mode_for_changes,
    verify_minimum_scientific_contract,
    verify_scientific_viability,
    verify_supplemental_bindings,
    verify_supplemental_evidence,
)
from tests.test_review_contracts import _r1_request


def _front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    marker = text.find("\n---\n", 4)
    return yaml.safe_load(text[4:marker]), text[marker + 5 :]


def _write_front_matter(path: Path, metadata: dict, body: str) -> None:
    header = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    path.write_text(f"---\n{header}\n---\n{body}", encoding="utf-8", newline="\n")


def _complete_decision(metadata: dict, *, verdict: str = "VIABLE") -> dict:
    metadata.update(
        {
            "verdict": verdict,
            "failure_origin": "route" if verdict == "ROUTE_FAILED" else None,
            "evaluated_at": "2026-07-21T00:00:00Z",
            "threshold_basis": "题目要求的绝对误差与冻结 baseline",
            "highest_risk": "当前路线可能无法恢复题目要求的核心输出",
            "counterexample": "已知真值正例无法在容许误差内恢复",
            "falsification_experiment": "运行冻结合成正例并与 baseline 同口径比较",
            "experiment_result": "真实运行记录显示 primary 已通过最低恢复阈值",
            "baseline_fallback_comparison": "primary 优于 baseline，fallback 暂不启动",
            "decision_reason": "直接答案、信息量和正控制证据均支持继续",
            "next_action": "继续 primary 并执行稳健性实验",
            "action_status": "completed" if verdict != "ROUTE_AT_RISK" else "pending",
            "remaining_time_minutes": 600,
            "investment_limit_minutes": 120,
        }
    )
    return metadata


def test_scientific_viability_template_is_valid_but_pending(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    run_dir.mkdir()

    path = create_scientific_viability(run_dir, question_scope=["Q1", "Q2"])

    pending = verify_scientific_viability(run_dir, path, require_decision=False)
    final = verify_scientific_viability(run_dir, path)
    assert pending == {
        "valid": True,
        "errors": [],
        "verdict": "PENDING",
        "action": "complete_assessment",
        "paper_eligible": False,
    }
    assert final["valid"] is False
    assert "尚未形成结论" in final["errors"][0]


def test_decision_source_hash_change_invalidates_viability(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    source = run_dir / "results/minimum-falsification.txt"
    source.parent.mkdir(parents=True)
    source.write_text("positive control passed\n", encoding="utf-8")
    path = create_scientific_viability(
        run_dir,
        question_scope=["Q1"],
        source_paths=[source],
    )
    metadata, body = _front_matter(path)
    _complete_decision(metadata)
    _write_front_matter(path, metadata, body)

    assert verify_scientific_viability(run_dir, path)["valid"] is True
    source.write_text("changed\n", encoding="utf-8")
    report = verify_scientific_viability(run_dir, path)
    assert report["valid"] is False
    assert "来源哈希已变化" in report["errors"][0]


def test_v2_checkbox_contract_is_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    source = run_dir / "result.txt"
    run_dir.mkdir()
    source.write_text("failed positive control\n", encoding="utf-8")
    path = create_scientific_viability(
        run_dir, question_scope=["Q1"], source_paths=[source]
    )
    metadata, body = _front_matter(path)
    _complete_decision(metadata)
    metadata["checks"] = {
        "direct_answer": {"status": "PASS"},
        "information_value": {"status": "PASS"},
        "positive_control_capability": {"status": "PASS"},
        "repairability": {"status": "PASS"},
    }
    _write_front_matter(path, metadata, body)

    report = verify_scientific_viability(run_dir, path)
    assert report["valid"] is False
    assert "v2 打勾字段" in report["errors"][0]


def test_route_failed_requires_failure_origin(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    source = run_dir / "result.txt"
    run_dir.mkdir()
    source.write_text("positive control failed\n", encoding="utf-8")
    path = create_scientific_viability(
        run_dir, question_scope=["Q1"], source_paths=[source]
    )
    metadata, body = _front_matter(path)
    _complete_decision(metadata, verdict="ROUTE_FAILED")
    metadata["failure_origin"] = None
    _write_front_matter(path, metadata, body)

    report = verify_scientific_viability(run_dir, path)

    assert report["valid"] is False
    assert "failure_origin" in report["errors"][0]


def test_route_at_risk_cannot_enter_formal_paper(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    source = run_dir / "result.txt"
    run_dir.mkdir()
    source.write_text("fallback comparison pending\n", encoding="utf-8")
    path = create_scientific_viability(
        run_dir, question_scope=["Q1"], source_paths=[source]
    )
    metadata, body = _front_matter(path)
    _complete_decision(metadata, verdict="ROUTE_AT_RISK")
    metadata["experiment_result"] = "正控制结果不稳定，尚不能区分路线"
    metadata["baseline_fallback_comparison"] = "baseline 已完成，fallback 最小比较尚待执行"
    metadata["decision_reason"] = "当前路线与 fallback 优劣尚未明确"
    metadata["next_action"] = "并行执行最小 fallback 比较，完成前禁止正式全文"
    _write_front_matter(path, metadata, body)

    research_report = verify_scientific_viability(run_dir, path)
    paper_report = verify_scientific_viability(
        run_dir, path, require_paper_eligibility=True
    )

    assert research_report["valid"] is True
    assert research_report["paper_eligible"] is False
    assert paper_report["valid"] is False
    assert "正式全文组装条件" in paper_report["errors"][0]


def test_minimum_scientific_contract_freezes_all_core_fields(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    source = run_dir / "brief/model_spec.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}\n", encoding="utf-8")
    path = create_minimum_scientific_contract(
        run_dir,
        source_paths=[source],
        values={
            "required_outputs": ["Q1 厚度估计与不确定区间"],
            "core_objective": "最小化冻结验证集的厚度恢复误差",
            "hard_constraints": ["厚度必须为正且满足题目单位"],
            "baseline": "峰间距解析估计",
            "primary_model_family": "有界非线性反演",
            "data_split": "按样本编号冻结训练与验证划分",
            "primary_metrics": ["绝对厚度误差", "区间覆盖率"],
            "positive_control": "已知真值合成谱恢复",
            "route_failure_criterion": "正控制无法在题目容许误差内恢复",
            "fallback_trigger": "首次正控制失败即启动峰间距 fallback",
            "experiment_budget": "最多 120 分钟、20 次拟合、2000 次优化评估",
        },
    )

    assert verify_minimum_scientific_contract(run_dir, path)["valid"] is True
    source.write_text('{"changed": true}\n', encoding="utf-8")
    report = verify_minimum_scientific_contract(run_dir, path)
    assert report["valid"] is False
    assert "来源哈希已变化" in report["errors"][0]


def test_cumcm_replay_stops_route_before_paper() -> None:
    run_dir = Path("benchmarks/cumcm-2025-b/quality-first-replay")

    report = verify_scientific_viability(run_dir, run_dir / "SCIENTIFIC_VIABILITY.md")

    assert report == {
        "valid": True,
        "errors": [],
        "verdict": "ROUTE_FAILED",
        "action": "stop_and_reopen_route",
        "paper_eligible": False,
    }
    replay = (run_dir / "REPLAY_RESULT.md").read_text(encoding="utf-8")
    assert "正式论文章节生成前" in replay
    assert "Q1" in replay and "Q2" in replay and "Q3" in replay
    assert "正控制" in replay and "fallback" in replay.lower()


def test_supplemental_evidence_is_scoped_and_hash_frozen(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    material = run_dir / "results/q2-positive-control.json"
    material.parent.mkdir(parents=True)
    material.write_text('{"sensitivity": 0.8}\n', encoding="utf-8")
    bundle = freeze_supplemental_evidence(
        run_dir,
        bundle_id="q2-positive-control",
        stage="R2_EXPERIMENT",
        question_id="Q2",
        issue="核对 Q2 正控制检出能力",
        materials={"positive-control": material},
        source_version="execution-q2-r3",
    )
    bindings = {
        "supplemental_evidence_manifest": bundle,
        "supplemental_evidence:positive-control": material,
    }

    assert verify_supplemental_evidence(
        run_dir, bundle, stage="R2_EXPERIMENT", question_id="Q2"
    )["valid"] is True
    verify_supplemental_bindings(
        run_dir,
        stage="R2_EXPERIMENT",
        question_id="Q2",
        bindings=bindings,
    )
    material.write_text('{"sensitivity": 0.0}\n', encoding="utf-8")
    with pytest.raises(ContractError, match="清单复验失败"):
        verify_supplemental_bindings(
            run_dir,
            stage="R2_EXPERIMENT",
            question_id="Q2",
            bindings=bindings,
        )


def test_supplemental_material_cannot_bypass_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot-run"
    material = run_dir / "result.txt"
    run_dir.mkdir()
    material.write_text("evidence\n", encoding="utf-8")

    with pytest.raises(ContractError, match="同时绑定 manifest"):
        verify_supplemental_bindings(
            run_dir,
            stage="R1_MODELING",
            question_id=None,
            bindings={"supplemental_evidence:result": material},
        )


def test_review_request_accepts_exact_frozen_supplemental_bundle(
    tmp_path: Path,
) -> None:
    run_dir, seed_request = _r1_request(
        tmp_path, run_id="supplemental-review", round_id="seed"
    )
    seed = load_json(seed_request)
    bindings = {
        role: run_dir / relative
        for role, relative in seed["binding_paths"].items()
    }
    material = run_dir / "review-inputs/positive-control.txt"
    material.parent.mkdir(parents=True, exist_ok=True)
    material.write_text("known truth recovered\n", encoding="utf-8")
    bundle = freeze_supplemental_evidence(
        run_dir,
        bundle_id="r1-positive-control",
        stage="R1_MODELING",
        issue="核对最低正控制设计",
        materials={"positive-control": material},
    )
    bindings.update(
        {
            "supplemental_evidence_manifest": bundle,
            "supplemental_evidence:positive-control": material,
        }
    )

    request = create_review_request(
        run_dir,
        "R1_MODELING",
        bindings,
        review_round_id="with-supplemental",
    )
    request_doc = load_json(request)

    assert request_doc["binding_paths"]["supplemental_evidence_manifest"].endswith(
        "SUPPLEMENTAL_EVIDENCE.md"
    )
    assert "supplemental_evidence:positive-control" in request_doc["bindings"]
    assert claim_review_request(
        request, thread_id="thread-supplemental-review"
    ).is_file()


def test_review_policy_allows_only_frozen_supplemental_role_shape() -> None:
    policy = get_review_stage_policy("R2_EXPERIMENT")

    assert review_material_role_allowed("supplemental_evidence:synthetic", policy)
    assert review_material_role_allowed("supplemental_evidence_manifest", policy)
    assert not review_material_role_allowed("author_explanation", policy)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (["core_model"], "full_scientific"),
        (["typography", "pagination"], "scoped_recheck"),
        ([], "none"),
        (["typography", "p0_p1_reopened"], "full_scientific"),
    ],
)
def test_r5_scope_depends_on_substantive_change(
    changes: list[str], expected: str
) -> None:
    assert r5_review_mode_for_changes(changes) == expected


def test_quality_first_skill_contracts_are_explicit() -> None:
    root = Path(".agents/skills")
    r1 = (root / "mathmodel-review-r1-modeling/SKILL.md").read_text(encoding="utf-8")
    r2 = (root / "mathmodel-review-r2-experiment/SKILL.md").read_text(encoding="utf-8")
    r3 = (root / "mathmodel-review-r3-paper-logic/SKILL.md").read_text(encoding="utf-8")
    r4 = (root / "mathmodel-review-r4-format-visual/SKILL.md").read_text(encoding="utf-8")
    r5 = (root / "mathmodel-review-r5-comprehensive/SKILL.md").read_text(encoding="utf-8")

    assert "最低成本" in r1 and "正控制" in r1 and "fallback" in r1
    assert all(verdict in r2 for verdict in ("VIABLE", "ROUTE_AT_RISK", "ROUTE_FAILED"))
    assert "先自由诊断" in r3 and "评价指标" in r3
    assert "FORMAT_HARD_COMPLIANCE" in r4 and "PRESENTATION_QUALITY" in r4
    assert "核心模型" in r5 and "scoped recheck" in r5
