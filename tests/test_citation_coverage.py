"""验证论文引用覆盖报告的键、计划、方法类别和位置语义。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.citations import (
    build_citation_coverage,
    citation_coverage_errors,
    citation_coverage_warnings,
)
from shumozizi.simple.initialization import initialize_simple_run


def _new_run(tmp_path: Path, run_id: str) -> Path:
    """创建带新版引用计划的最小运行。"""
    return initialize_simple_run(tmp_path, run_id, workflow_version="3.2")


def _write_bibliography(run_dir: Path, *keys: str) -> None:
    """写入含指定键的最小 BibTeX 文献库。"""
    body = "\n".join(
        f"@article{{{key},\n  title = {{{key} source}},\n  year = {{2024}}\n}}" for key in keys
    )
    (run_dir / "paper/references.bib").write_text(body + "\n", encoding="utf-8")


def _write_plan(run_dir: Path, rows: list[tuple[str, str]]) -> None:
    """写入新版类别化引用计划。"""
    table = "\n".join(
        f"| {key} | {category} | 可核验来源 | 第 3 节 | 支持具体判断 |"
        for key, category in rows
    )
    (run_dir / "paper/CITATION_PLAN.md").write_text(
        "# CITATION_PLAN\n\n## 正文绑定表\n\n"
        "| citation key | 类别 | 来源与可核验信息 | 正文位置 | 支持的具体判断 |\n"
        "|---|---|---|---|---|\n"
        f"{table}\n",
        encoding="utf-8",
    )


def test_plain_numeric_bracket_is_not_a_citation(tmp_path: Path) -> None:
    """普通编号不得被误判为来源引用。"""
    run_dir = _new_run(tmp_path, "numeric-bracket")
    _write_bibliography(run_dir, "method")
    (run_dir / "paper/main.tex").write_text(
        "\\section{模型建立}\n步骤[1]先计算目标函数。\n",
        encoding="utf-8",
    )

    report = build_citation_coverage(run_dir)

    assert report["cited_keys"] == []
    assert report["undefined_keys"] == []
    assert report["unused_bibliography_keys"] == ["method"]


def test_typst_local_label_is_not_a_citation(tmp_path: Path) -> None:
    """Typst 图表标签引用不得进入文献 key 检查。"""
    run_dir = _new_run(tmp_path, "typst-label")
    (run_dir / "paper/main.typ").write_text(
        "= 模型建立\n#figure(rect(width: 2cm)) <fig-route>\n见 @fig-route。\n",
        encoding="utf-8",
    )

    report = build_citation_coverage(run_dir)

    assert report["cited_keys"] == []
    assert report["undefined_keys"] == []


def test_undefined_body_key_is_a_hard_error(tmp_path: Path) -> None:
    """正文显式引用必须能解析到文献定义。"""
    run_dir = _new_run(tmp_path, "undefined-key")
    (run_dir / "paper/main.tex").write_text(
        "\\section{模型建立}\n采用已有方法\\cite{missing2024}。\n",
        encoding="utf-8",
    )

    report = build_citation_coverage(run_dir)

    assert report["undefined_keys"] == ["missing2024"]
    assert any("missing2024" in item for item in citation_coverage_errors(report))


def test_plan_key_must_exist_and_be_cited_in_body(tmp_path: Path) -> None:
    """计划中的真实行必须同时闭合文献定义与正文使用。"""
    run_dir = _new_run(tmp_path, "unrealized-plan")
    _write_bibliography(run_dir, "planned")
    _write_plan(run_dir, [("planned", "core_method"), ("absent", "validation")])
    (run_dir / "paper/main.tex").write_text("\\section{模型建立}\n无引用。\n", encoding="utf-8")

    report = build_citation_coverage(run_dir)
    errors = citation_coverage_errors(report)

    assert report["undefined_plan_keys"] == ["absent"]
    assert report["unrealized_plan_keys"] == ["absent", "planned"]
    assert any("参考文献中定义" in item for item in errors)
    assert any("正文未实际引用" in item for item in errors)


def test_new_plan_rejects_invalid_category_and_placeholder_claim(tmp_path: Path) -> None:
    """新版计划必须使用受支持类别并给出非占位的具体判断。"""
    run_dir = _new_run(tmp_path, "invalid-plan-row")
    _write_bibliography(run_dir, "method", "validation")
    _write_plan(run_dir, [("method", "algorithm"), ("validation", "validation")])
    plan_path = run_dir / "paper/CITATION_PLAN.md"
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "| validation | validation | 可核验来源 | 第 3 节 | 支持具体判断 |",
            "| validation | validation | 可核验来源 | 第 4 节 | 待填写 |",
        ),
        encoding="utf-8",
    )
    (run_dir / "paper/main.tex").write_text(
        "\\section{模型建立}\\cite{method,validation}\n",
        encoding="utf-8",
    )

    report = build_citation_coverage(run_dir)
    errors = citation_coverage_errors(report)

    assert report["invalid_plan_categories"] == ["algorithm"]
    assert report["incomplete_plan_keys"] == ["validation"]
    assert any("未支持的类别" in item for item in errors)
    assert any("未填写完整" in item for item in errors)


def test_detected_external_method_requires_realized_category(tmp_path: Path) -> None:
    """结构化合同中的外部方法必须由已引用的对应类别来源覆盖。"""
    run_dir = _new_run(tmp_path, "method-category")
    _write_bibliography(run_dir, "background")
    _write_plan(run_dir, [("background", "background")])
    (run_dir / "paper/main.tex").write_text(
        "\\section{模型建立}\n背景见\\cite{background}。\n",
        encoding="utf-8",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "question_id": "Q1",
                    "primary_method": {"method_id": "particle swarm optimization"},
                    "validation": {"uncertainty": "bootstrap confidence interval"},
                }
            ],
        },
    )

    report = build_citation_coverage(run_dir)
    errors = citation_coverage_errors(report)

    assert report["missing_method_categories"] == ["core_method", "uncertainty"]
    assert any("core_method, uncertainty" in item for item in errors)


def test_unused_intro_only_and_single_source_diversity_are_warnings(tmp_path: Path) -> None:
    """来源位置与多样性不足应提示，但不冒充确定性引用错误。"""
    run_dir = _new_run(tmp_path, "citation-advice")
    _write_bibliography(run_dir, "shared", "unused")
    _write_plan(run_dir, [("shared", "background"), ("shared", "core_method")])
    (run_dir / "paper/main.tex").write_text(
        "\\section{引言}\n背景和方法均见\\citep{shared}。\n"
        "\\section{模型建立}\n本文给出推导。\n",
        encoding="utf-8",
    )

    report = build_citation_coverage(run_dir)
    warnings = citation_coverage_warnings(report)

    assert citation_coverage_errors(report) == []
    assert report["introduction_only_keys"] == ["shared"]
    assert any("未被正文使用" in item and "unused" in item for item in warnings)
    assert any("全部引用只出现在" in item for item in warnings)
    assert any("只使用一个不同来源" in item for item in warnings)
    assert any("单独承担多个引用类别" in item for item in warnings)


def test_old_four_column_plan_remains_compatible(tmp_path: Path) -> None:
    """旧运行缺类别列时只提示升级，不新增类别硬门。"""
    run_dir = _new_run(tmp_path, "legacy-plan")
    _write_bibliography(run_dir, "method")
    (run_dir / "paper/CITATION_PLAN.md").write_text(
        "# CITATION_PLAN\n\n## 正文绑定表\n\n"
        "| citation key | 来源与可核验信息 | 正文位置 | 支持的具体判断 |\n"
        "|---|---|---|---|\n"
        "| method | 可核验来源 | 第 3 节 | 支持方法 |\n",
        encoding="utf-8",
    )
    (run_dir / "paper/main.tex").write_text(
        "\\section{模型建立}\n采用粒子群算法\\cite{method}。\n",
        encoding="utf-8",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {"question_id": "Q1", "primary_method": {"method_id": "particle swarm"}}
            ],
        },
    )

    report = build_citation_coverage(run_dir)

    assert citation_coverage_errors(report) == []
    assert any("旧四列表格" in item for item in citation_coverage_warnings(report))
