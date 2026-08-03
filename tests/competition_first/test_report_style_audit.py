"""验证报告式论文写作检测区分硬错误与人工复核告警。"""

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
    """内部词、重复报账和摘要流水账应形成稳定硬错误。"""
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
    error_codes = {item["code"] for item in report["errors"]}
    warning_codes = {item["code"] for item in report["warnings"]}

    assert report["advisory_only"] is False
    assert error_codes == {"E001"}
    assert {"E002", "E003"} <= warning_codes
    assert "internal_workflow_vocabulary" in warning_codes
    assert "report_phrase_repetition" in warning_codes
    assert "repetitive_question_template" in warning_codes


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
    error_codes = {item["code"] for item in report["errors"]}
    warning_codes = {item["code"] for item in report["warnings"]}

    assert error_codes == set()
    assert report["advisory_only"] is True
    assert "internal_workflow_vocabulary" not in warning_codes
    assert "report_phrase_repetition" not in warning_codes
    assert "abstract_question_enumeration" not in warning_codes
    assert "repetitive_question_template" not in warning_codes


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
    error_codes = {item["code"] for item in report["errors"]}
    warning_codes = {item["code"] for item in report["warnings"]}

    assert not error_codes
    assert {"E004", "E005"} <= warning_codes
    assert "excessive_list_density" in warning_codes
    assert "fragmented_heading_structure" in warning_codes
    assert "core_question_without_derivation" in warning_codes
    assert "core_question_without_mechanism" in warning_codes
    assert "hero_figure_not_in_argument" in warning_codes


def test_report_style_hard_errors_use_conservative_context(tmp_path: Path) -> None:
    """附录术语、带统一主线的摘要和单次自然句式不应触发硬错误。"""
    run_dir = _run(tmp_path, "report-style-context")
    source = run_dir / "paper/sections/main.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section*{摘要}\n"
        "共享容量约束是统一困难。Q1、Q2、Q3 均在联合建模结构下求解，"
        "活跃约束揭示边际收益递减规律。\n"
        "\\section{Q1}\n本问采用解析消元。由此可得唯一驻点，其原因在于目标严格凸。\n"
        "\\appendix\n\\section{附录：运行说明}\n"
        "result_id、fallback_selected 与回执仅用于复现实验。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)
    error_codes = {item["code"] for item in report["errors"]}

    assert "E001" not in error_codes
    assert "E002" not in error_codes
    assert "E003" not in error_codes


def test_figure_argument_chain_closes_e005(tmp_path: Path) -> None:
    """图引用后有正常论文解释时不应要求固定三联句。"""
    run_dir = _run(tmp_path, "figure-argument-chain")
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "figures": [
                {
                    "figure_id": "q2-hero",
                    "presentation_role": "question_hero",
                    "role": "insight",
                    "placement": "body",
                    "latex_label": "fig:q2-hero",
                }
            ]
        },
    )
    source = run_dir / "paper/sections/main.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{Q2}\n"
        "如图\\ref{fig:q2-hero}所示，曲线在容量阈值处呈现明显拐点。"
        "原因在于容量约束开始活跃，因此继续追加同类资源不再改变主结论。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)

    assert "E005" not in {item["code"] for item in report["errors"]}


def test_figure_argument_accepts_natural_explanation_without_ordered_keywords(
    tmp_path: Path,
) -> None:
    """峰值、下降和清零等自然表述可以消费图，而无需机制模板词。"""
    run_dir = _run(tmp_path, "figure-natural-explanation")
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "figures": [
                {
                    "figure_id": "q1-hero",
                    "presentation_role": "question_hero",
                    "role": "insight",
                    "placement": "body",
                    "latex_label": "fig:q1-hero",
                }
            ]
        },
    )
    source = run_dir / "paper/sections/main.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{Q1}\n"
        "如图\\ref{fig:q1-hero}所示，第12日形成明显峰值，库存随后下降并最终清零。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)

    assert "E005" not in {item["code"] for item in report["errors"]}


def test_sparse_paper_still_runs_visual_review(tmp_path: Path) -> None:
    """两张正文图也必须触发稀疏与集中度复核，不能因低于旧阈值被跳过。"""
    run_dir = _run(tmp_path, "sparse-visual-review")
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "units": [
                {"question_id": "Q1", "core_question": True},
                {"question_id": "Q2", "core_question": True},
                {"question_id": "Q3", "core_question": True},
            ],
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "figures": [
                {
                    "figure_id": "q1-boundary",
                    "role": "insight",
                    "placement": "body",
                    "presentation_role": "supporting",
                    "latex_label": "fig:q1-boundary",
                },
                {
                    "figure_id": "q1-mechanism",
                    "role": "decisive_evidence",
                    "placement": "body",
                    "presentation_role": "supporting",
                    "latex_label": "fig:q1-mechanism",
                },
            ]
        },
    )
    source = run_dir / "paper/sections/sparse.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{Q1}\n"
        "如图\\ref{fig:q1-boundary}和图\\ref{fig:q1-mechanism}所示，"
        "容量边界收紧时最优点向可行域内部移动。\n"
        "\\section{Q2}\nQ2 延续共享资源约束。\n"
        "\\section{Q3}\nQ3 验证不同参数下的结果。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)
    warning_codes = {item["code"] for item in report["warnings"]}

    assert "VISUAL_SCARCITY_REVIEW" in warning_codes
    assert "VISUAL_RHYTHM_REVIEW" in warning_codes


def test_nested_question_headings_report_generic_template_repetition(
    tmp_path: Path,
) -> None:
    """总章下的逐问二级标题复用通用功能名时仍应被识别。"""
    run_dir = _run(tmp_path, "nested-question-template")
    source = run_dir / "paper/sections/solutions.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{模型的建立与求解}\n"
        "\\subsection{问题一模型的建立与求解}\n"
        "\\subsubsection{模型求解结果}\n结果显示第一问满足约束。\n"
        "\\subsubsection{结果分析与本问结论}\n原因在于容量约束活跃。\n"
        "\\subsection{问题二模型的建立与求解}\n"
        "\\subsubsection{模型求解结果}\n结果显示第二问满足约束。\n"
        "\\subsubsection{结果分析与本问结论}\n原因在于时间约束活跃。\n"
        "\\subsection{问题三模型的建立与求解}\n"
        "\\subsubsection{模型求解结果}\n结果显示第三问满足约束。\n"
        "\\subsubsection{结果分析与本问结论}\n原因在于共享约束活跃。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)
    warnings = {item["code"]: item for item in report["warnings"]}

    finding = warnings["generic_question_heading_repetition"]
    assert finding["question_ids"] == ["1", "2", "3"]
    assert finding["generic_roles"]["模型建立与求解"] == 3
    assert finding["generic_roles"]["模型求解结果"] == 3
    assert finding["generic_roles"]["结果分析与结论"] == 3


def test_two_question_manuscript_reports_generic_template_repetition(
    tmp_path: Path,
) -> None:
    """两问论文完整复用同一通用标题时也应形成文风告警。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "two-question-template",
        required_questions=["Q1", "Q2"],
        workflow_version="3.2",
    )
    source = run_dir / "paper/sections/solutions.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{问题一}\n"
        "\\subsection{模型建立与求解}\n第一问形成可行解。\n"
        "\\subsection{结果分析与结论}\n第一问由容量边界决定。\n"
        "\\section{问题二}\n"
        "\\subsection{模型建立与求解}\n第二问形成可行解。\n"
        "\\subsection{结果分析与结论}\n第二问由时间边界决定。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)
    warnings = {item["code"]: item for item in report["warnings"]}

    finding = warnings["generic_question_heading_repetition"]
    assert finding["question_ids"] == ["1", "2"]
    assert finding["generic_roles"] == {"模型建立与求解": 2, "结果分析与结论": 2}


def test_single_question_generic_headings_do_not_report_repetition(
    tmp_path: Path,
) -> None:
    """单问中的正常功能标题不是跨问模板复用。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "single-question-headings",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    source = run_dir / "paper/sections/solution.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{问题一}\n"
        "\\subsection{模型建立与求解}\n由约束传播可得可行域。\n"
        "\\subsection{结果分析与结论}\n原因在于容量约束活跃。\n",
        encoding="utf-8",
    )

    report = audit_report_like_manuscript(run_dir)

    assert "generic_question_heading_repetition" not in {
        item["code"] for item in report["warnings"]
    }
