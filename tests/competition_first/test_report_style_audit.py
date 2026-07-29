"""验证报告式论文写作检测保持 advisory 且能识别高价值模式。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.style_audit import audit_report_like_manuscript
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, name: str) -> Path:
    """创建三问 Competition-First 运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )


def test_report_style_audit_detects_template_repetition_and_internal_terms(
    tmp_path: Path,
) -> None:
    """重复问答模板、内部词和摘要流水账应形成非阻断告警。"""
    run_dir = _run(tmp_path, "report-style-patterns")
    source = run_dir / "paper/sections/questions.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for question_id in ("Q1", "Q2", "Q3"):
        blocks.append(
            rf"""
\section{{{question_id}}}
\subsection{{问题分析}}
本问采用内部 scorer，并把 production result 晋级为 fallback。
\subsection{{模型建立}}
参数设置如下：
\begin{{itemize}}
\item 参数一；\item 参数二；\item 参数三。
\end{{itemize}}
\subsection{{结果分析}}
结果见表，由表可知结果较好。
"""
        )
    source.write_text(
        "\\section*{摘要}\nQ1 完成评价，Q2 完成优化，Q3 完成检验。\n"
        + "\n".join(blocks),
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)
    codes = {item["code"] for item in report["warnings"]}

    assert report["advisory_only"] is True
    assert "internal_workflow_vocabulary" in codes
    assert "report_phrase_repetition" in codes
    assert "abstract_question_enumeration" in codes
    assert "repetitive_question_template" in codes


def test_argument_driven_manuscript_avoids_report_style_false_positive(
    tmp_path: Path,
) -> None:
    """共享模型、推导和机制主线不应被误判为逐问工作报告。"""
    run_dir = _run(tmp_path, "argument-driven-style")
    source = run_dir / "paper/sections/main.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section*{摘要}\n"
        "共享资源约束使独立最优失效。本文先定义联合可行域，再由活跃约束解释"
        "最优解的同步结构，并给出不外推到其他资源上限的边界。\n"
        "\\section{统一数学对象与判据}\n"
        "\\begin{equation}J(x)=\\sum_i c_i x_i\\end{equation}\n"
        "由约束传播可推出候选集合的嵌套关系，因此联合求解不是简单拼接。\n"
        "\\section{共享约束下的决策机制}\n"
        "结果的拐点原因在于容量约束开始活跃，意味着继续增加同类资源只能获得"
        "递减的边际收益。该判断仅适用于当前时间窗。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)
    codes = {item["code"] for item in report["warnings"]}

    assert "internal_workflow_vocabulary" not in codes
    assert "report_phrase_repetition" not in codes
    assert "abstract_question_enumeration" not in codes
    assert "repetitive_question_template" not in codes


def test_report_style_audit_covers_depth_density_and_hero_binding(
    tmp_path: Path,
) -> None:
    """核心问深度、清单密度和主图论证绑定应分别给出可解释告警。"""
    run_dir = _run(tmp_path, "report-style-depth")
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "units": [{"question_id": "Q1", "core_question": True}],
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "figures": [
                {
                    "figure_id": "q1-hero",
                    "presentation_role": "question_hero",
                    "latex_label": "fig:q1-hero",
                }
            ]
        },
    )
    source = run_dir / "paper/sections/checklist.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{Q1}\n"
        + "\n".join(
            f"\\subsection{{步骤 {index}}}\n\\begin{{itemize}}\\item 值 {index}\\end{{itemize}}"
            for index in range(1, 13)
        ),
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)
    codes = {item["code"] for item in report["warnings"]}

    assert "excessive_list_density" in codes
    assert "fragmented_heading_structure" in codes
    assert "core_question_without_derivation" in codes
    assert "core_question_without_mechanism" in codes
    assert "hero_figure_not_in_argument" in codes
