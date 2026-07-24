"""验证编译前论文硬门 (shumozizi.paper.readiness) 真实阻断未就绪的运行。

这些测试直接调用 check_paper_readiness / require_paper_readiness，不走完整
科学审查与编译子进程，因此很快；编译器接线由
test_independent_review_workflow 中的端到端测试覆盖。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError
from shumozizi.core.schema import validate_document
from shumozizi.paper.readiness import (
    argument_map_bindings,
    check_paper_readiness,
    require_paper_readiness,
)
from shumozizi.simple.critical_claims import read_critical_claims
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import assess_result_quality
from tests.capability_flow_helpers import prepare_minimal_capability_route
from tests.quality_protocol_helpers import (
    _ensure_scientific_review_contracts,
    adapter_backed_assessment,
    run_synthetic_verification_protocol,
)


def _valid_argument_map(
    run_dir: Path,
    *,
    result_ids: list[str] | None = None,
    figure_ids: list[str] | None = None,
    question_id: str = "Q1",
) -> dict[str, Any]:
    """构造符合 argument_map schema 的最小结构化论证地图。"""
    critical = next(
        item
        for item in read_critical_claims(run_dir)["claims"]
        if item["question_id"] == question_id
    )
    return {
        "schema_name": "argument_map",
        "schema_version": "3.0",
        "run_id": run_dir.name,
        **argument_map_bindings(run_dir),
        "status": "current",
        "claims": [
            {
                "claim_id": critical["claim_id"],
                "question_id": question_id,
                "claim": "主张文本",
                "motivation": "动机",
                "baseline_limitation": "基线局限",
                "model_support": "模型支撑",
                "result_ids": (
                    result_ids
                    if result_ids is not None
                    else list(critical["result_ids"])
                ),
                "comparison_evidence": [],
                "validation_evidence": [],
                "figure_ids": figure_ids if figure_ids is not None else [],
                "boundary": "边界",
                "outcome": "supported",
                "paper_location": "正文第 3 节",
            }
        ],
    }


def _write_content_blueprint(run_dir: Path, appendix: Any) -> None:
    """写入含指定 source_code_appendix 值的内容蓝图。"""
    (run_dir / "paper").mkdir(parents=True, exist_ok=True)
    (run_dir / "paper" / "content_blueprint.json").write_text(
        json.dumps({"source_code_appendix": appendix}, ensure_ascii=False),
        encoding="utf-8",
    )


class PaperReadinessGateTests(unittest.TestCase):
    """覆盖 argument_map 结构、结果绑定、图表、附录策略等编译前提。"""

    def _init(self, name: str, questions: list[str] | None = None) -> Path:
        required_questions = questions or ["Q1"]
        run_dir = initialize_simple_run(
            Path(self._tmp.name), name, required_questions=required_questions
        )
        prepare_minimal_capability_route(run_dir)
        for index, question_id in enumerate(required_questions, start=1):
            protocol = run_synthetic_verification_protocol(
                run_dir,
                result_id=f"result-{question_id}",
                question_id=question_id,
                objective=float(index),
            )
            assess_result_quality(
                run_dir,
                result_id=f"result-{question_id}",
                assessment=adapter_backed_assessment(protocol),
            )
        _ensure_scientific_review_contracts(run_dir)
        (run_dir / "paper").mkdir(parents=True, exist_ok=True)
        return run_dir

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_markdown_outline_cannot_bypass_argument_map(self) -> None:
        """仅有 argument-outline.md 时生产模式硬门必须阻断。"""
        run_dir = self._init("markdown-only")
        (run_dir / "paper" / "argument-outline.md").write_text(
            "# 论文提纲\n\n准备撰写论文。\n", encoding="utf-8"
        )
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("argument_map.json" in err for err in status["errors"]),
            status["errors"],
        )
        with self.assertRaisesRegex(ContractError, "argument_map.json"):
            require_paper_readiness(run_dir)

    def test_argument_map_missing_required_question_blocks(self) -> None:
        """论证地图未覆盖某必答问题时阻断。"""
        run_dir = self._init("missing-question", questions=["Q1", "Q2"])
        (run_dir / "paper" / "argument_map.json").write_text(
            json.dumps(_valid_argument_map(run_dir, question_id="Q1")),
            encoding="utf-8",
        )
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("必答问题" in err and "Q2" in err for err in status["errors"]),
            status["errors"],
        )

    def test_superseded_argument_map_is_valid_but_cannot_release_paper(self) -> None:
        """级联失效后的 v3 地图保持合同合法，但不能继续用于成文。"""
        run_dir = self._init("superseded-argument-map")
        argument_map = _valid_argument_map(run_dir)
        argument_map["status"] = "superseded"
        argument_map["superseded_reason"] = "independent_evidence:counterexample"

        self.assertEqual([], validate_document(argument_map, "argument_map"))
        (run_dir / "paper" / "argument_map.json").write_text(
            json.dumps(argument_map), encoding="utf-8"
        )
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("superseded" in err or "已失效" in err for err in status["errors"]),
            status["errors"],
        )

        argument_map.pop("superseded_reason")
        self.assertTrue(validate_document(argument_map, "argument_map"))

    def test_claim_bound_to_noncurrent_result_blocks(self) -> None:
        """主张绑定的 result_id 不是当前 production 结果时阻断。"""
        run_dir = self._init("stale-result")
        (run_dir / "paper" / "argument_map.json").write_text(
            json.dumps(_valid_argument_map(run_dir, result_ids=["R-ghost"])),
            encoding="utf-8",
        )
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("R-ghost" in err for err in status["errors"]), status["errors"]
        )

    def test_figure_plan_does_not_satisfy_real_figures(self) -> None:
        """主张引用的图只在 figure_plan 中、无当前图时仍阻断。"""
        run_dir = self._init("figure-plan-only")
        (run_dir / "paper" / "argument_map.json").write_text(
            json.dumps(
                _valid_argument_map(run_dir, figure_ids=["F-critical"])
            ),
            encoding="utf-8",
        )
        # figure_plan 声称要用 F-critical，但没有 figures/index.json 中的当前图
        (run_dir / "paper" / "figure_plan.json").write_text(
            json.dumps(
                {"bindings": {"figures_used": [{"figure_id": "F-critical"}]}}
            ),
            encoding="utf-8",
        )
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("F-critical" in err or "图表" in err for err in status["errors"]),
            status["errors"],
        )

    def test_empty_source_appendix_strategy_blocks(self) -> None:
        """source_code_appendix 为 null 时不算有策略，必须阻断。"""
        run_dir = self._init("null-appendix")
        (run_dir / "paper" / "argument_map.json").write_text(
            json.dumps(_valid_argument_map(run_dir)), encoding="utf-8"
        )
        _write_content_blueprint(run_dir, None)
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("source_code_appendix" in err for err in status["errors"]), status["errors"]
        )

    def test_appendix_needs_mode_and_roles(self) -> None:
        """source_code_appendix 缺 mode 或 included_roles 时阻断。"""
        run_dir = self._init("appendix-shape")
        (run_dir / "paper" / "argument_map.json").write_text(
            json.dumps(_valid_argument_map(run_dir)), encoding="utf-8"
        )
        _write_content_blueprint(run_dir, {"mode": "pdf", "included_roles": []})
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("source_code_appendix" in err for err in status["errors"]), status["errors"]
        )


if __name__ == "__main__":
    unittest.main()
