"""覆盖 Competition-First v3.1 的核心门禁收缩与事实保留。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.paper.readiness import (
    build_argument_map_from_current_artifacts,
    check_paper_readiness,
)
from shumozizi.simple.competition import (
    validate_next_experiments,
    validate_route_competition,
    write_answer_map,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.objective_semantics import (
    objective_semantics_for_question,
    objective_semantics_review_required,
)
from shumozizi.simple.results import register_result
from shumozizi.simple.review_focus import (
    record_scientific_challenge_evidence,
    verify_scientific_challenge_evidence,
    write_focused_followup,
)
from shumozizi.simple.state import read_simple_state, update_simple_state, utc_now


def _run_dir(tmp_path: Path, run_id: str = "competition-first") -> Path:
    """创建一个最小 v3.1 运行目录。"""
    return initialize_simple_run(tmp_path, run_id, required_questions=["Q1"])


def _register_current_result(run_dir: Path) -> None:
    """登记一个可供 answer map 使用的真实当前结果。"""
    source = run_dir / "code" / "q1.py"
    output = run_dir / "results" / "raw" / "q1.json"
    source.write_text("print('ok')\n", encoding="utf-8")
    output.write_text(json.dumps({"metrics": {"objective": 1.0}}), encoding="utf-8")
    now = utc_now()
    register_result(
        run_dir,
        result_id="q1_primary",
        question_id="Q1",
        kind="primary",
        command="python code/q1.py",
        source_script="code/q1.py",
        input_files=["code/q1.py"],
        output_files=["results/raw/q1.json"],
        metrics={"objective": 1.0},
        metric_sources={
            "objective": {
                "file": "results/raw/q1.json",
                "json_path": "metrics.objective",
            }
        },
        exit_code=0,
        stdout_path="results/q1.stdout.log",
        stderr_path="results/q1.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=0.1,
        objective_semantics_sha256="a" * 64,
    )


def test_new_run_uses_reduced_phase_set(tmp_path: Path) -> None:
    """新运行不再需要 capability route 才能进入实验。"""
    run_dir = _run_dir(tmp_path)

    state = update_simple_state(run_dir, phase="experiment")

    assert state["schema_version"] == "3.1"
    assert state["workflow"] == "competition-first-v3.1"
    assert state["phase"] == "experiment"


def test_old_phase_maps_in_memory_and_migrates_on_write(tmp_path: Path) -> None:
    """旧 v3 状态可读，不在读取时改写文件。"""
    run_dir = _run_dir(tmp_path, "legacy-run")
    state_path = run_dir / "state" / "run.json"
    old = json.loads(state_path.read_text(encoding="utf-8"))
    old["schema_version"] = "3.0"
    old["phase"] = "scientific_review"
    atomic_json(state_path, old)

    mapped = read_simple_state(run_dir)

    assert mapped["phase"] == "experiment"
    assert mapped["legacy_phase"] == "scientific_review"
    assert json.loads(state_path.read_text(encoding="utf-8"))["phase"] == "scientific_review"

    update_simple_state(run_dir, current_question="Q1")

    written = json.loads(state_path.read_text(encoding="utf-8"))
    migration = json.loads((run_dir / "state" / "migrations.json").read_text(encoding="utf-8"))
    assert written["schema_version"] == "3.1"
    assert migration["original_phase"] == "scientific_review"


def test_objective_review_is_conditional(tmp_path: Path) -> None:
    """普通措辞差异不触发，未决高影响歧义才触发。"""
    run_dir = _run_dir(tmp_path)
    path = run_dir / "analysis" / "objective-ambiguities.json"
    atomic_json(
        path,
        {
            "ambiguities": [
                {
                    "question_id": "Q1",
                    "candidate_interpretations": ["逐对象求和"],
                    "can_change_primary_result": False,
                    "resolved_by_problem_text": True,
                    "resolution": "题面公式",
                }
            ]
        },
    )
    assert not objective_semantics_review_required(run_dir)

    atomic_json(
        path,
        {
            "ambiguities": [
                {
                    "question_id": "Q1",
                    "candidate_interpretations": ["逐对象求和", "时间并集"],
                    "can_change_primary_result": True,
                    "resolved_by_problem_text": False,
                    "resolution": None,
                }
            ]
        },
    )
    assert objective_semantics_review_required(run_dir)


def test_unambiguous_formal_problem_can_bind_production_result(tmp_path: Path) -> None:
    """正式题面不再因为没有无关的目标语义审核而阻断实验。"""
    run_dir = _run_dir(tmp_path)
    (run_dir / "problem" / "statement.md").write_text("目标为最小化成本。", encoding="utf-8")

    digest = objective_semantics_for_question(run_dir, "Q1")

    assert len(digest) == 64


def test_route_tournament_rejects_solver_variants_only() -> None:
    """同一数学结构的不同求解器不能伪装成路线竞争。"""
    payload = {
        "baseline": {"mathematical_structure": "固定目标的整数规划"},
        "candidates": [
            {"mathematical_structure": "固定目标的整数规划", "probe": "更换遗传算法"}
        ],
    }

    assert validate_route_competition(payload)
    assert validate_next_experiments({"experiments": [{"name": "装饰性图"}]})


def test_paper_readiness_uses_answer_map_not_manual_argument_map(tmp_path: Path) -> None:
    """v3.1 从当前答案和结果自动生成后台 argument map。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)
    write_answer_map(
        run_dir,
        {
            "Q1": {
                "result_ids": ["q1_primary"],
                "direct_answer_location": "paper/sections/q1.tex",
            }
        },
    )

    status = check_paper_readiness(run_dir)
    generated = build_argument_map_from_current_artifacts(run_dir)

    assert status["ready"], status
    assert generated["claims"][0]["result_ids"] == ["q1_primary"]
    assert (run_dir / "paper" / "generated" / "argument_map.json").is_file()


def test_scientific_challenge_requires_real_current_execution(tmp_path: Path) -> None:
    """自由挑战必须绑定实际执行结果，不能只由报告文字放行。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)

    record_scientific_challenge_evidence(
        run_dir,
        result_ids=["q1_primary"],
        attack_description="用独立小规模实例攻击当前目标排序。",
    )

    assert verify_scientific_challenge_evidence(run_dir)["valid"]


def test_scientific_followup_is_limited_to_one(tmp_path: Path) -> None:
    """集中挑战只允许一个决定性专项追问。"""
    run_dir = _run_dir(tmp_path)
    write_focused_followup(
        run_dir,
        "# 决定性追问\n\n执行独立小规模枚举，确认当前排序是否翻转，并记录可复现输入、输出和结论。",
    )

    with pytest.raises(ContractError, match="最多允许一个"):
        write_focused_followup(run_dir, "# 第二次追问\n\n这不应被允许，因为同一轮已经存在专项追问。")
