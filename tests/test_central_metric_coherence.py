"""核心量跨章节自洽检查的回归用例：以真实竞赛中出现过的失败形状为基准。

用例覆盖设计约定的四类判定：账本缺失降级、合法舍入/单位换算/区间放行、口径混用
告警、以及伪造/过期核心值阻断；并锁定两处易误报的坑（波数 ``cm^{-1}`` 与百分号）。
数值来自 CUMCM-2025-B 真实运行：q1 峰间距法 8.112μm 与 q2 全谱法 8.0104μm 是两种
方法的合法多值，二者不得被当作矛盾。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.qa.check_central_metric_coherence as coherence_module
from scripts.qa.check_central_metric_coherence import check_central_metric_coherence
from scripts.qa.metric_ledger import seed_ledger_from_answers
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.units import quantity_in_unit


def _result(result_id: str, question_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """构造一条最小但符合结果索引 schema 的 current 结果条目。"""
    return {
        "result_id": result_id,
        "question_id": question_id,
        "kind": "primary",
        "source_script": None,
        "command": "python fixture.py",
        "input_files": [],
        "input_hashes": {},
        "output_files": [],
        "output_hashes": {},
        "metrics": metrics,
        "method_facts": {},
        "metric_sources": {},
        "status": "current",
        "execution_mode": "production",
        "objective_semantics_sha256": "0" * 64,
        "dependency_scope": "question",
        "affected_question_ids": [question_id],
        "execution_valid": True,
        "exit_code": 0,
        "stdout_path": "logs/out.txt",
        "stderr_path": "logs/err.txt",
        "started_at": "2026-07-26T00:00:00Z",
        "finished_at": "2026-07-26T00:00:01Z",
        "duration_seconds": 1.0,
        "error": None,
        "created_at": "2026-07-26T00:00:02Z",
    }


# 两方法多值 + 一个百分比量（用于验证百分号不会被当作长度误比对）。
_INDEX = {
    "schema_version": "1.0",
    "run_id": "regr-central-metric",
    "results": [
        _result("q1-peak-spacing", "Q1", {"d_mean_um": 8.112}),
        _result("q2-full-spectrum", "Q2", {"d_um": 8.0104, "seg_consistency_pct": 0.96}),
        _result("q3-coating", "Q3", {"d_um": 3.43}),
    ],
}

_ANSWER_MAP = {
    "answers": {
        "Q1": {"result_ids": ["q1-peak-spacing"]},
        "Q2": {"result_ids": ["q2-full-spectrum"]},
        "Q3": {"result_ids": ["q3-coating"]},
    }
}

# 中心量：最终推荐厚度，指向 q1 峰间距法 8.112μm（论文 boxed 答案 8.11μm）。
_CENTRAL_LEDGER = {
    "schema_version": "1.0",
    "run_id": "regr-central-metric",
    "metrics": [
        {
            "metric_id": "final_thickness",
            "name": "最终推荐厚度",
            "aliases": ["外延层厚度", "厚度"],
            "source_result_id": "q1-peak-spacing",
            "source_metric": "d_mean_um",
            "unit": "um",
            "central": True,
            "scope": {"question_id": "Q1", "stage": "final"},
        }
    ],
}

# 论文正文骨架：boxed 最终答案 8.11μm（合法舍入自 8.112），另含 95% CI 与 q2 全谱法值。
_GOOD_BODY = (
    "\\section{结果}\n"
    "综合峰间距法，外延层厚度为 $\\boxed{d=8.11\\,\\mu\\mathrm{m}}$。\n"
    "该结果的 $95\\%$ 置信区间宽度约 $0.5\\,\\mu\\mathrm{m}$。\n"
    "作为对照，全谱拟合在 $1200$–$3700\\,\\mathrm{cm^{-1}}$ 波段给出厚度 "
    "$8.01\\,\\mu\\mathrm{m}$，两法一致。\n"
)


def _make_run(tmp_path: Path, *, body: str, ledger: dict[str, Any] | None) -> Path:
    """在 tmp 下搭出最小 v3 运行（结果索引 + 答案图 + 论文 + 可选账本）。"""
    run_dir = tmp_path / "run"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "paper" / "sections").mkdir(parents=True)
    (run_dir / "paper" / "generated").mkdir(parents=True)
    (run_dir / "results" / "index.json").write_text(
        json.dumps(_INDEX, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "paper" / "answer-map.json").write_text(
        json.dumps(_ANSWER_MAP, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "paper" / "main.tex").write_text(
        "\\begin{document}\n\\input{sections/questions}\n\\end{document}\n",
        encoding="utf-8",
    )
    (run_dir / "paper" / "sections" / "questions.tex").write_text(body, encoding="utf-8")
    if ledger is not None:
        (run_dir / "paper" / "generated" / "metric_ledger.json").write_text(
            json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
        )
    return run_dir


def test_absent_ledger_degrades_to_skipped(tmp_path: Path) -> None:
    """未提供账本时整体降级为不阻断的 skipped，既有运行不因新增门禁而失败。"""
    run_dir = _make_run(tmp_path, body=_GOOD_BODY, ledger=None)
    report = check_central_metric_coherence(run_dir)
    assert report["skipped"] is True
    assert report["success"] is True


def test_good_paper_has_no_contradiction(tmp_path: Path) -> None:
    """boxed 8.11μm 与权威 8.112μm 在显示精度容差内一致，好论文不得误报 FAIL。"""
    run_dir = _make_run(tmp_path, body=_GOOD_BODY, ledger=_CENTRAL_LEDGER)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is True
    assert report["contradictions"] == []
    assert "final_thickness" in report["metrics_checked"]


def test_fabricated_central_value_blocks(tmp_path: Path) -> None:
    """核心量别名邻域出现谁都不等的 7.931μm：判为伪造/过期，必须 FAIL。"""
    body = _GOOD_BODY + "\n最终反演得到外延层厚度为 $7.931\\,\\mu\\mathrm{m}$。\n"
    run_dir = _make_run(tmp_path, body=body, ledger=_CENTRAL_LEDGER)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is False
    stated = [item["stated"] for item in report["contradictions"]]
    assert "7.931" in stated
    # 重叠别名（“外延层厚度”含“厚度”）指向同一处数字时只应记一次。
    assert stated.count("7.931") == 1


def test_negative_value_conflict_blocks(tmp_path: Path) -> None:
    """负数不能因旧正则丢失；同一相关系数的负值冲突必须阻断。"""
    ledger = {
        "schema_version": "1.0",
        "run_id": "regr-central-metric",
        "metrics": [{
            "metric_id": "correlation", "aliases": ["相关系数"],
            "source_result_id": "q1-peak-spacing", "source_metric": "d_mean_um",
            "unit": None, "central": True,
        }],
    }
    body = "\\section{结果} 相关系数为 $-1.25$。"
    run_dir = _make_run(tmp_path, body=body, ledger=ledger)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is False
    assert [item["stated"] for item in report["contradictions"]] == ["-1.25"]


def test_scientific_notation_conflict_blocks(tmp_path: Path) -> None:
    """E 记法和 LaTeX 乘十幂都必须作为一个数值进入冲突扫描。"""
    ledger = {
        "schema_version": "1.0",
        "run_id": "regr-central-metric",
        "metrics": [{
            "metric_id": "error", "aliases": ["误差"],
            "source_result_id": "q1-peak-spacing", "source_metric": "d_mean_um",
            "unit": None, "central": True,
        }],
    }
    body = "\\section{结果} 误差为 $1e-3$，另一处误差为 $2.4\\times10^{-5}$。"
    run_dir = _make_run(tmp_path, body=body, ledger=ledger)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is False
    assert {item["stated"] for item in report["contradictions"]} == {"1e-3", "2.4\\times10^{-5}"}


def test_final_pdf_text_is_checked_in_addition_to_sources(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """源文件没有矛盾时，最终 PDF 中实际显示的冲突数值仍必须阻断。"""
    run_dir = _make_run(tmp_path, body=_GOOD_BODY, ledger=_CENTRAL_LEDGER)
    (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nfixture")
    monkeypatch.setattr(
        coherence_module,
        "_pdf_body_text_files",
        lambda _run: [("paper/final.pdf#page-1", "外延层厚度为 7.931 um")],
    )

    report = coherence_module.check_central_metric_coherence(run_dir)

    assert report["success"] is False
    assert report["pdf_text_checked"] is True
    assert any(item["file"] == "paper/final.pdf#page-1" for item in report["contradictions"])


def test_legit_rounding_passes(tmp_path: Path) -> None:
    """1 位小数 8.1μm 在其显示精度容差内可解释为 8.112μm，不得 FAIL。"""
    body = _GOOD_BODY + "\n厚度约为 $8.1\\,\\mu\\mathrm{m}$。\n"
    run_dir = _make_run(tmp_path, body=body, ledger=_CENTRAL_LEDGER)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is True


def test_unit_conversion_passes(tmp_path: Path) -> None:
    """0.00811mm 换算即 8.11μm，落在 8.112μm 容差内，不得 FAIL。"""
    body = _GOOD_BODY + "\n换算后外延层厚度为 $0.00811\\,\\mathrm{mm}$。\n"
    run_dir = _make_run(tmp_path, body=body, ledger=_CENTRAL_LEDGER)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is True


def test_temperature_conversion_uses_offset_aware_quantity() -> None:
    """摄氏度到开尔文必须包含偏移，不能错误使用单一乘法因子。"""
    assert quantity_in_unit(0.0, "°C", "K") == 273.15


def test_other_method_value_warns_not_blocks(tmp_path: Path) -> None:
    """全谱法 8.01μm 等于已登记的 q2 d_um：判口径混用 WARN，不阻断。"""
    body = _GOOD_BODY + "\n全谱法给出的厚度为 $8.01\\,\\mu\\mathrm{m}$。\n"
    run_dir = _make_run(tmp_path, body=body, ledger=_CENTRAL_LEDGER)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is True
    matched = {item.get("matches_other") for item in report["scope_warnings"]}
    assert "q2-full-spectrum.d_um" in matched


def test_wavenumber_not_read_as_length(tmp_path: Path) -> None:
    """``3700 cm^{-1}`` 是波数不是长度，出现在厚度邻域也不得被当作矛盾长度值。"""
    body = (
        "\\section{结果}\n外延层厚度对应的特征吸收出现在 "
        "$3700\\,\\mathrm{cm^{-1}}$ 附近，厚度权威值见上。\n"
        "外延层厚度为 $8.11\\,\\mu\\mathrm{m}$。\n"
    )
    run_dir = _make_run(tmp_path, body=body, ledger=_CENTRAL_LEDGER)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is True
    assert all(item["stated"] != "3700" for item in report["contradictions"])


def test_percentage_near_length_metric_ignored(tmp_path: Path) -> None:
    """百分数与长度不同量纲，厚度邻域的 $95\\%$ 不得被误比为长度而 FAIL。"""
    body = (
        "\\section{结果}\n外延层厚度的 $95\\%$ 置信区间已给出；"
        "外延层厚度为 $8.11\\,\\mu\\mathrm{m}$。\n"
    )
    run_dir = _make_run(tmp_path, body=body, ledger=_CENTRAL_LEDGER)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is True
    assert all(item["stated"] != "95" for item in report["contradictions"])


def test_seeded_draft_activates_central_checks(tmp_path: Path) -> None:
    """播种草稿每题首个量置 central=True：写入账本后核心量自洽检查立即生效。"""
    run_dir = _make_run(tmp_path, body=_GOOD_BODY, ledger=None)
    draft = seed_ledger_from_answers(run_dir)
    assert draft["metrics"], "草稿应至少列出各问直接答案的数值指标"
    # 每题首个量应为 central=True，其余仍为 False。
    by_question: dict[str, list[bool]] = {}
    for m in draft["metrics"]:
        qid = m["scope"]["question_id"]
        by_question.setdefault(qid, []).append(m["central"])
    for qid, flags in by_question.items():
        assert flags[0] is True, f"{qid} 首个量应为 central=True"
        assert all(not f for f in flags[1:]), f"{qid} 后续量应为 central=False"
    # 写入账本后，与正文一致的好论文应通过自洽检查。
    (run_dir / "paper" / "generated" / "metric_ledger.json").write_text(
        json.dumps(draft, ensure_ascii=False), encoding="utf-8"
    )
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is True
    assert report["contradictions"] == []


def test_v32_paper_auto_seeds_with_active_central_metrics(tmp_path: Path) -> None:
    """v3.2 生产论文缺账本时自动播种，播种草稿已含 central=True，检查立即生效。"""
    run_dir = initialize_simple_run(tmp_path, "ledger-v32", workflow_version="3.2")
    index = {**_INDEX, "run_id": "ledger-v32"}
    (run_dir / "results" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (run_dir / "paper" / "answer-map.json").write_text(
        json.dumps(_ANSWER_MAP), encoding="utf-8"
    )
    (run_dir / "paper" / "main.tex").write_text(
        "\\begin{document}\\end{document}", encoding="utf-8"
    )
    state_path = run_dir / "state" / "run.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = "paper"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    report = check_central_metric_coherence(run_dir)

    # 播种草稿已含 central=True，空正文通过自洽检查。
    assert report["auto_seeded"] is True
    assert (run_dir / "paper" / "generated" / "metric_ledger.json").is_file()
    assert report["success"] is True
    ledger = json.loads(
        (run_dir / "paper" / "generated" / "metric_ledger.json").read_text(encoding="utf-8")
    )
    assert any(m["central"] is True for m in ledger["metrics"])


def test_ledger_pointing_at_missing_metric_blocks(tmp_path: Path) -> None:
    """账本指向 current 结果中不存在的 metric：视为账本错误并阻断，避免空指针漏检。"""
    ledger = {
        "schema_version": "1.0",
        "run_id": "regr-central-metric",
        "metrics": [
            {
                "metric_id": "final_thickness",
                "aliases": ["厚度"],
                "source_result_id": "q1-peak-spacing",
                "source_metric": "does_not_exist",
                "unit": "um",
                "central": True,
            }
        ],
    }
    run_dir = _make_run(tmp_path, body=_GOOD_BODY, ledger=ledger)
    report = check_central_metric_coherence(run_dir)
    assert report["success"] is False
    assert any("source_metric" in item.get("reason", "") for item in report["contradictions"])
