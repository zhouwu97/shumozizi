"""验证模型原生视觉计划与 MATLAB 生产执行合同。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.figures import audit_figure_information_value, write_figure_plan
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.matlab import run_matlab_analysis
from shumozizi.simple.results import read_result_index


def _run(tmp_path: Path, name: str) -> Path:
    """创建一个允许登记生产结果的最小 v3.2 运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q2"],
        workflow_version="3.2",
    )


def _figure(visual_archetype: str) -> dict[str, object]:
    """构造一张 FIGURE_PLAN 2.2 正文图。"""
    return {
        "figure_id": "q2-main",
        "preferred": "skills/mathmodel-figure-templates",
        "fallback": "skills/3coding-visual",
        "selected_skill": "skills/mathmodel-figure-templates",
        "template_id": "rf-tpe-surface",
        "selection_reason": "该图需要同时呈现策略权衡、边界与最终方案。",
        "question_id": "Q2",
        "role": "insight",
        "claim": "最终方案位于可靠性与时点的折中拐点。",
        "source_result_ids": ["q2-primary"],
        "script": "code/figures/q2.py",
        "output": "figures/current/q2-main.pdf",
        "paper_section": "paper/sections/q2.tex",
        "caption": "可靠性与推荐时点的 Pareto 前沿",
        "latex_label": "fig:q2-main",
        "explanation_anchor": "拐点由可靠性约束开始激活形成",
        "required": True,
        "visual_archetype": visual_archetype,
        "renderer": "matlab",
        "visual_question": "哪个方案在可靠性与时点之间形成最佳折中？",
        "expected_observation": "最终方案位于 Pareto 拐点且通过最坏组约束。",
        "decision_consequence": "选择该方案作为 Q2 的正式推荐规则。",
    }


def test_figure_plan_22_requires_model_native_visual_semantics(tmp_path: Path) -> None:
    """2.2 图计划不能退回只有文件路径和图注的登记表。"""
    run_dir = _run(tmp_path, "figure-native-semantics")
    figure = _figure("pareto_feasible_region")
    del figure["visual_question"]

    with pytest.raises(ContractError, match="visual_question"):
        write_figure_plan(
            run_dir,
            {
                "schema_name": "figure_plan",
                "schema_version": "2.2",
                "run_id": run_dir.name,
                "visual_decisions": [
                    {
                        "question_id": "Q2",
                        "status": "required",
                        "reason": "多目标折中必须展示可行域、约束和最终决策。",
                    }
                ],
                "figures": [figure],
            },
        )


def test_visual_value_audit_distinguishes_structure_from_route_bars(tmp_path: Path) -> None:
    """视觉审核按信息价值区分模型结构图和普通路线柱形图。"""
    run_dir = _run(tmp_path, "figure-value")
    plan = {
        "schema_name": "figure_plan",
        "schema_version": "2.2",
        "run_id": run_dir.name,
        "visual_decisions": [
            {
                "question_id": "Q2",
                "status": "required",
                "reason": "多目标折中必须展示可行域、约束和最终决策。",
            }
        ],
        "figures": [
            _figure("pareto_feasible_region"),
            {**_figure("route_score_comparison"), "figure_id": "q2-routes"},
        ],
    }

    report = audit_figure_information_value(plan)

    scores = {item["figure_id"]: item["total_score"] for item in report["figures"]}
    assert scores["q2-main"] >= 8
    assert scores["q2-routes"] < 6
    assert report["advisory_only"] is True
    assert any(item["figure_id"] == "q2-routes" for item in report["needs_revision"])


def _write_matlab_entrypoint(run_dir: Path) -> None:
    """写入由伪进程测试使用的 MATLAB 入口和原始输入。"""
    (run_dir / "code/matlab").mkdir(parents=True)
    (run_dir / "code/matlab/run_analysis.m").write_text(
        "% 测试入口由受控 runner 调用。\ndisp('ok');\n",
        encoding="utf-8",
    )
    (run_dir / "problem/input.csv").write_text("x,y\n1,2\n", encoding="utf-8")


def _fake_outputs(run_dir: Path) -> None:
    """模拟 MATLAB 新鲜生成四类必需产物。"""
    output_dir = run_dir / "results/matlab"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_text(
        json.dumps({"metrics": {"objective": 1.25}}), encoding="utf-8"
    )
    (output_dir / "result.csv").write_text("x,objective\n1,1.25\n", encoding="utf-8")
    figure_dir = run_dir / "figures/current"
    (figure_dir / "matlab-smoke.pdf").write_bytes(b"%PDF-1.7\n% smoke\n")
    (figure_dir / "matlab-smoke.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"smoke"
    )


def test_matlab_runner_writes_manifest_and_registers_production_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功执行必须同时留下 manifest、四类产物和 current 结果。"""
    run_dir = _run(tmp_path, "matlab-production")
    _write_matlab_entrypoint(run_dir)

    monkeypatch.setattr(
        "shumozizi.simple.matlab.detect_engine",
        lambda _engine: {
            "available": True,
            "engine": "matlab",
            "command": "matlab",
            "version": "24.1",
        },
    )

    def fake_run(*_args: object, **_kwargs: object) -> object:
        _fake_outputs(run_dir)
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "MATLAB smoke ok\n", "stderr": ""},
        )()

    monkeypatch.setattr("shumozizi.simple.matlab.subprocess.run", fake_run)

    receipt = run_matlab_analysis(
        run_dir,
        entrypoint="code/matlab/run_analysis.m",
        question_id="Q2",
        result_id="q2-matlab-challenger",
        role="optimizer_challenger",
        input_files=["problem/input.csv"],
        output_files=[
            "results/matlab/result.json",
            "results/matlab/result.csv",
            "figures/current/matlab-smoke.pdf",
            "figures/current/matlab-smoke.png",
        ],
        metric_sources={
            "objective": {
                "file": "results/matlab/result.json",
                "json_path": "metrics.objective",
            }
        },
        objective_semantics_sha256="a" * 64,
    )

    manifest = load_json(run_dir / "results/matlab/manifest.json")
    assert receipt["execution_valid"] is True
    assert manifest["entrypoint"] == "code/matlab/run_analysis.m"
    assert manifest["matlab_version"] == "24.1"
    assert manifest["role"] == "optimizer_challenger"
    assert manifest["exit_status"] == 0
    result = read_result_index(run_dir)["results"][-1]
    assert result["result_id"] == "q2-matlab-challenger"
    assert result["status"] == "current"
    assert "results/matlab/manifest.json" in result["output_files"]


def test_matlab_runner_records_unavailable_without_fake_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺少引擎时只记录 unavailable，不能制造结果或成功回执。"""
    run_dir = _run(tmp_path, "matlab-unavailable")
    _write_matlab_entrypoint(run_dir)
    monkeypatch.setattr(
        "shumozizi.simple.matlab.detect_engine",
        lambda _engine: {
            "available": False,
            "engine": "matlab",
            "command": None,
            "version": None,
        },
    )

    receipt = run_matlab_analysis(
        run_dir,
        entrypoint="code/matlab/run_analysis.m",
        question_id="Q2",
        result_id="q2-matlab-unavailable",
        role="independent_oracle",
        input_files=["problem/input.csv"],
        output_files=[
            "results/matlab/result.json",
            "results/matlab/result.csv",
            "figures/current/matlab-smoke.pdf",
            "figures/current/matlab-smoke.png",
        ],
        metric_sources={},
        objective_semantics_sha256="b" * 64,
    )

    assert receipt["execution_valid"] is False
    assert receipt["availability"] == "unavailable"
    assert not (run_dir / "results/matlab/result.json").exists()
    result = read_result_index(run_dir)["results"][-1]
    assert result["status"] == "failed"
    assert result["execution_valid"] is False


def test_independent_oracle_only_requires_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """独立复算不应被迫导出 CSV 或生成与任务无关的论文图。"""
    run_dir = _run(tmp_path, "matlab-oracle-json-only")
    _write_matlab_entrypoint(run_dir)
    monkeypatch.setattr(
        "shumozizi.simple.matlab.detect_engine",
        lambda _engine: {
            "available": True,
            "engine": "matlab",
            "command": "matlab",
            "version": "24.1",
        },
    )

    def fake_run(*_args: object, **_kwargs: object) -> object:
        output = run_dir / "results/matlab/oracle.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"agreement": True}), encoding="utf-8")
        return type("Completed", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()

    monkeypatch.setattr("shumozizi.simple.matlab.subprocess.run", fake_run)
    receipt = run_matlab_analysis(
        run_dir,
        entrypoint="code/matlab/run_analysis.m",
        question_id="Q2",
        result_id="q2-matlab-oracle",
        role="independent_oracle",
        input_files=["problem/input.csv"],
        output_files=["results/matlab/oracle.json"],
        metric_sources={},
        objective_semantics_sha256="c" * 64,
    )

    assert receipt["execution_valid"] is True
    result = read_result_index(run_dir)["results"][-1]
    assert result["method_facts"]["uses_independent_oracle"] is True
    assert result["method_facts"]["generates_scientific_visualization"] is False
