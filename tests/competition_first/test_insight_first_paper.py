"""验证图表以洞察为主、源码不侵占正文的 Competition-First 约束。

这些规则针对的是一个具体失分模式：论文正文被数值稳定性图和整篇源码占满，
而机制、阈值和权衡这些真正提高竞争力的内容被挤到边缘。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shumozizi.core.io import ContractError
from shumozizi.paper.readiness import check_paper_readiness
from shumozizi.simple.competition import write_answer_map
from shumozizi.simple.figures import read_figure_index, register_insight_figure
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.results import register_result
from shumozizi.simple.state import utc_now


def _run(tmp_path: Path, name: str) -> Path:
    """创建一个最小 Competition-First 运行目录。"""
    return initialize_simple_run(tmp_path, name, required_questions=["Q1"])


def _register(run_dir: Path) -> None:
    """登记一个可供图表绑定的真实当前结果。"""
    (run_dir / "code" / "q1.py").write_text("print('ok')\n", encoding="utf-8")
    (run_dir / "results" / "raw" / "q1.json").write_text(
        json.dumps({"metrics": {"objective": 1.0}}), encoding="utf-8"
    )
    now = utc_now()
    register_result(
        run_dir,
        result_id="q1-primary",
        question_id="Q1",
        kind="primary",
        command="python code/q1.py",
        source_script="code/q1.py",
        input_files=["code/q1.py"],
        output_files=["results/raw/q1.json"],
        metrics={"objective": 1.0},
        metric_sources={
            "objective": {"file": "results/raw/q1.json", "json_path": "metrics.objective"}
        },
        exit_code=0,
        stdout_path="results/q1.stdout.log",
        stderr_path="results/q1.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=1.0,
        objective_semantics_sha256="a" * 64,
    )


def _render(run_dir: Path, figure_id: str) -> dict[str, Any]:
    """生成绘图脚本与占位输出文件。"""
    script = f"code/plot_{figure_id}.py"
    (run_dir / script).write_text("print('plot')\n", encoding="utf-8")
    output_dir = run_dir / "figures" / "current"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{figure_id}.pdf").write_bytes(b"%PDF-1.7\n%stub\n")
    return {
        "renderer_script": script,
        "outputs": [f"figures/current/{figure_id}.pdf"],
    }


def test_stability_figure_cannot_take_a_body_slot(tmp_path: Path) -> None:
    """舍入与采样稳定性图不得声明为正文图。"""
    run_dir = _run(tmp_path, "stability-body")
    _register(run_dir)
    rendered = _render(run_dir, "rounding")

    with pytest.raises(ContractError, match="默认进入附录"):
        register_insight_figure(
            run_dir,
            figure_id="rounding",
            result_id="q1-primary",
            input_result="results/raw/q1.json",
            question="10.452 秒在不同采样设置下是否都高于 10.45 秒？",
            takeaway="不同采样下结论一致，可显示为 10.5 秒。",
            role="stability",
            placement="body",
            **rendered,
        )


def test_stability_figure_is_recorded_as_appendix_by_default(tmp_path: Path) -> None:
    """稳定性图默认落到附录，不需要作者额外声明。"""
    run_dir = _run(tmp_path, "stability-appendix")
    _register(run_dir)
    rendered = _render(run_dir, "sampling")

    register_insight_figure(
        run_dir,
        figure_id="sampling",
        result_id="q1-primary",
        input_result="results/raw/q1.json",
        question="采样层级是否影响结论？",
        takeaway="三档采样给出一致排序。",
        role="stability",
        **rendered,
    )

    entry = read_figure_index(run_dir)["figures"][-1]
    assert entry["role"] == "stability"
    assert entry["placement"] == "appendix"


def test_insight_figure_keeps_its_declared_body_placement(tmp_path: Path) -> None:
    """洞察图可以正常占据正文位置。"""
    run_dir = _run(tmp_path, "insight-body")
    _register(run_dir)
    rendered = _render(run_dir, "marginal")

    entry = register_insight_figure(
        run_dir,
        figure_id="marginal",
        result_id="q1-primary",
        input_result="results/raw/q1.json",
        question="第二、第三个动作各自贡献多少？",
        takeaway="第三个动作的边际收益接近零。",
        role="insight",
        placement="body",
        **rendered,
    )

    assert entry["role"] == "insight"
    assert entry["placement"] == "body"


def test_unknown_figure_role_is_rejected(tmp_path: Path) -> None:
    """未知 role 不能静默通过，避免角色标签失去意义。"""
    run_dir = _run(tmp_path, "bad-role")
    _register(run_dir)
    rendered = _render(run_dir, "weird")

    with pytest.raises(ContractError, match="figure role"):
        register_insight_figure(
            run_dir,
            figure_id="weird",
            result_id="q1-primary",
            input_result="results/raw/q1.json",
            question="这张图回答什么？",
            takeaway="不确定。",
            role="audit",
            **rendered,
        )


def _answer_map(run_dir: Path) -> None:
    """写入最小逐问答案映射。"""
    write_answer_map(
        run_dir,
        {"Q1": {"result_ids": ["q1-primary"], "direct_answer_location": "paper/sections/q1.tex"}},
    )


def _blueprint(run_dir: Path, appendix: dict[str, Any]) -> None:
    """写入只含源码附录策略的内容蓝图。"""
    (run_dir / "paper").mkdir(parents=True, exist_ok=True)
    (run_dir / "paper" / "content_blueprint.json").write_text(
        json.dumps({"source_code_appendix": appendix}, ensure_ascii=False), encoding="utf-8"
    )


def test_pdf_source_appendix_beyond_one_page_blocks_readiness(tmp_path: Path) -> None:
    """PDF 内源码超过一页默认阻断，逼迫把完整代码移入附件。"""
    run_dir = _run(tmp_path, "appendix-too-long")
    _register(run_dir)
    _answer_map(run_dir)
    _blueprint(run_dir, {"mode": "pdf", "included_roles": ["solver"], "pdf_page_budget": 5})

    status = check_paper_readiness(run_dir)

    assert not status["ready"]
    assert any("pdf_page_budget" in error for error in status["errors"]), status["errors"]


def test_missing_page_budget_is_reported_instead_of_silently_allowed(tmp_path: Path) -> None:
    """未声明页数预算时不静默放行，因为默认行为是塞入完整源码。"""
    run_dir = _run(tmp_path, "appendix-no-budget")
    _register(run_dir)
    _answer_map(run_dir)
    _blueprint(run_dir, {"mode": "pdf", "included_roles": ["solver"]})

    status = check_paper_readiness(run_dir)

    assert not status["ready"]
    assert any("pdf_page_budget" in error for error in status["errors"]), status["errors"]


def test_attachment_only_source_delivery_needs_no_page_budget(tmp_path: Path) -> None:
    """完整源码走附件时不需要页数预算，也不产生阻断。"""
    run_dir = _run(tmp_path, "appendix-attachment")
    _register(run_dir)
    _answer_map(run_dir)
    _blueprint(run_dir, {"mode": "attachment", "included_roles": ["solver", "scorer"]})

    status = check_paper_readiness(run_dir)

    assert status["ready"], status


def test_explicit_competition_requirement_allows_full_source_in_pdf(tmp_path: Path) -> None:
    """赛事明确要求整篇源码时允许放开，但必须写明依据。"""
    run_dir = _run(tmp_path, "appendix-full")
    _register(run_dir)
    _answer_map(run_dir)
    _blueprint(
        run_dir,
        {
            "mode": "pdf",
            "included_roles": ["solver"],
            "competition_requires_full": True,
            "full_source_reason": "赛事章程要求论文正文附完整源码。",
        },
    )

    status = check_paper_readiness(run_dir)

    assert status["ready"], status


def test_v32_figure_must_declare_a_role(tmp_path: Path) -> None:
    """v3.2 不允许省略 role：省略即可绕过附录约束。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-role-required",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    _register(run_dir)
    rendered = _render(run_dir, "unlabelled")

    with pytest.raises(ContractError, match="必须声明 role"):
        register_insight_figure(
            run_dir,
            figure_id="unlabelled",
            result_id="q1-primary",
            input_result="results/raw/q1.json",
            question="这张图回答什么？",
            takeaway="未声明角色。",
            **rendered,
        )


def test_evidence_only_figure_set_warns_about_missing_insight_figures(tmp_path: Path) -> None:
    """图表全是证据或稳定性图时给出警告，但不阻断正确回答。"""
    run_dir = _run(tmp_path, "no-insight-figure")
    _register(run_dir)
    _answer_map(run_dir)
    rendered = _render(run_dir, "rounding")
    register_insight_figure(
        run_dir,
        figure_id="rounding",
        result_id="q1-primary",
        input_result="results/raw/q1.json",
        question="舍入阈值是否稳定？",
        takeaway="不同采样下一致。",
        role="stability",
        **rendered,
    )

    status = check_paper_readiness(run_dir)

    assert status["ready"], status
    assert any("洞察图" in warning for warning in status["warnings"]), status["warnings"]
