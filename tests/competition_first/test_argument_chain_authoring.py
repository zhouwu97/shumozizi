"""验证 v3.4 论证链与决策建议：warrant 投影与决策合同渲染。

这些测试验证四件事：
1. ``RESEARCH_PACKAGE`` 在存在建模单元时渲染"逐问论证链与决策建议"节，
   把 insight.mechanism 投影为 warrant、把不可行域决策合同投影为决策建议；
2. Writer 面向的包仍然不含 result_id/sha256 等控制字段；
3. ``AUTHOR_BRIEF`` 明确论证义务（为什么证据支持结论）但不开新清单；
4. 后台 ``paper/generated/argument_map.json`` 不再是退化注册表，而是携带
   warrant 候选与决策建议的论证地图。

不覆盖：authoring 状态机、导入审计与新鲜度（见 test_writer_handoff.py）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import atomic_json, load_json
from shumozizi.paper.author_pass import prepare_longform_author
from shumozizi.paper.readiness import build_argument_map_from_current_artifacts
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review_focus import record_scientific_challenge_evidence

MECHANISM_TEXT = (
    "风险随干预时长单调下降，达标时间是风险曲线首次穿过阈值的时刻，"
    "继续等待只增加时延而不改变已满足的可靠性约束。"
)
STRICT_RESULT = "10–25 周内不存在满足 0.90 可靠性的可行时点。"
FALLBACK_DECISION = "报告第 25 周实际可达可靠度并建议复检。"
FALLBACK_ATTAINED = "第 25 周可靠度 0.83（未达 0.90）。"
RETEST_STRATEGY = "高风险组每 2 周复检一次。"
SENSITIVITY = "可靠性阈值降至 0.85 时第 21 周即可行；本推荐不适用于更高阈值。"


def _units() -> list[dict[str, object]]:
    """一个核心决策问：带机制 insight 与不可行域决策合同。"""
    return [
        {
            "unit_id": "q1",
            "question_id": "Q1",
            "core_question": True,
            "answer_contract": {
                "infeasible_policy": {
                    "strict_result": STRICT_RESULT,
                    "fallback_decision": FALLBACK_DECISION,
                    "fallback_attained_reliability": FALLBACK_ATTAINED,
                    "retest_strategy": RETEST_STRATEGY,
                    "reliability_sensitivity": SENSITIVITY,
                }
            },
            "actual": {
                "insights": [
                    {
                        "insight_id": "ins-q1",
                        "kind": "mechanism",
                        "observation": "低风险组第 19 周是首个满足可靠性阈值的时点。",
                        "mechanism": MECHANISM_TEXT,
                        "boundary": "仅适用于题面可靠性阈值与数据覆盖区间。",
                        "evidence_result_ids": ["r-q1"],
                    }
                ]
            },
        }
    ]


@pytest.fixture
def chain_run(tmp_path: Path) -> Path:
    """构造带建模单元、正式答案与科学挑战的 Author Pass 运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "argument-chain",
        required_questions=["Q1"],
        workflow_version="3.2",
        competition="cumcm",
    )
    index = load_json(run_dir / "results/index.json")
    index["results"].append(
        {
            "result_id": "r-q1",
            "question_id": "Q1",
            "kind": "test",
            "source_script": None,
            "command": "test",
            "input_files": [],
            "input_hashes": {},
            "output_files": [],
            "output_hashes": {},
            "metric_sources": {},
            "method_facts": {},
            "status": "current",
            "execution_mode": "production",
            "execution_valid": True,
            "exit_code": 0,
            "stdout_path": "results/test.stdout.log",
            "stderr_path": "results/test.stderr.log",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "duration_seconds": 1.0,
            "error": None,
            "created_at": "2026-01-01T00:00:01Z",
            "objective_semantics_sha256": "0" * 64,
            "dependency_scope": "question",
            "affected_question_ids": ["Q1"],
            "metrics": {"objective": 19.0, "feasible": True},
        }
    )
    atomic_json(run_dir / "results/index.json", index)
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": "r-q1",
                    "result_ids": ["r-q1"],
                    "direct_answer_location": "问题一结尾",
                    "objective_answer": {
                        "result_id": "r-q1",
                        "claim_level": "best_found",
                        "answer": "低风险组推荐第 19 周作为检测时点。",
                    },
                }
            }
        },
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {"schema_version": "1.4", "units": _units()},
    )
    record_scientific_challenge_evidence(
        run_dir,
        result_ids=["r-q1"],
        attack_description="独立复核 Q1 正式结果、约束与主张边界。",
        findings=[],
    )
    return run_dir


def test_research_package_renders_argument_chain_and_decision_advice(
    chain_run: Path,
) -> None:
    """RESEARCH_PACKAGE 必须把 warrant 与决策建议渲染给 Author。"""
    manifest = prepare_longform_author(chain_run, require_template=False)
    package = (chain_run / manifest["research_package"]["path"]).read_text(
        encoding="utf-8"
    )
    assert "## 逐问论证链与决策建议" in package
    assert "论证理由（为什么这些证据支持上述正式答案）" in package
    assert MECHANISM_TEXT in package
    assert "支持强度" in package
    assert "决策建议（该问为决策题）" in package
    assert STRICT_RESULT in package
    assert "备用决策" in package and FALLBACK_ATTAINED in package
    assert RETEST_STRATEGY in package
    assert SENSITIVITY in package


def test_writer_facing_package_still_free_of_control_fields(chain_run: Path) -> None:
    """新增论证内容不得把机器控制字段泄漏进 Writer 人读文件。"""
    manifest = prepare_longform_author(chain_run, require_template=False)
    package = (chain_run / manifest["research_package"]["path"]).read_text(
        encoding="utf-8"
    )
    assert "result_id" not in package
    assert "sha256" not in package


def test_author_brief_states_warrant_obligation_without_new_checklist(
    chain_run: Path,
) -> None:
    """AUTHOR_BRIEF 必须说明论证义务，但表述为判断改写而非槽位填空。"""
    manifest = prepare_longform_author(chain_run, require_template=False)
    brief = (chain_run / manifest["author_brief"]["path"]).read_text(encoding="utf-8")
    assert "为什么这些证据支持这个结论" in brief
    assert "判断、改写与补全" in brief
    assert "决策类问题必须给出推荐" in brief
    assert "不能把'无可行时点'写成推荐一个不满足可靠性的时点" in brief


def test_generated_argument_map_carries_warrant_candidates_and_decision_advice(
    chain_run: Path,
) -> None:
    """后台论证地图不再只是 claim→result 注册表。"""
    document = build_argument_map_from_current_artifacts(chain_run)
    (claim,) = document["claims"]
    assert claim["question_id"] == "Q1"
    assert claim["warrant_candidates"] == [MECHANISM_TEXT]
    assert claim["decision_advice"]["strict_result"] == STRICT_RESULT
    assert claim["decision_advice"]["reliability_sensitivity"] == SENSITIVITY
    generated = load_json(chain_run / "paper/generated/argument_map.json")
    assert generated["claims"][0]["warrant_candidates"] == [MECHANISM_TEXT]
