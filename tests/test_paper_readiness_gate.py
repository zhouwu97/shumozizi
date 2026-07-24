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
from shumozizi.paper.readiness import check_paper_readiness, require_paper_readiness
from shumozizi.simple.initialization import initialize_simple_run

_ZERO_SHA = "0" * 64


def _valid_argument_map(
    run_id: str,
    *,
    result_ids: list[str] | None = None,
    figure_ids: list[str] | None = None,
    question_id: str = "Q1",
) -> dict[str, Any]:
    """构造符合 argument_map schema 的最小结构化论证地图。"""
    return {
        "schema_name": "argument_map",
        "schema_version": "2.0",
        "run_id": run_id,
        "run_config_lock_sha256": _ZERO_SHA,
        "paper_index_sha256": _ZERO_SHA,
        "task_fingerprint_sha256": _ZERO_SHA,
        "pattern_transfer_plan_sha256": _ZERO_SHA,
        "route_lock_sha256": _ZERO_SHA,
        "accepted_results_digest": "digest",
        "claim_evidence_digest": "digest",
        "claims": [
            {
                "claim_id": f"{question_id}-main",
                "question_id": question_id,
                "claim": "主张文本",
                "motivation": "动机",
                "baseline_limitation": "基线局限",
                "model_support": "模型支撑",
                "result_ids": result_ids if result_ids is not None else ["R-1"],
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
        run_dir = initialize_simple_run(
            Path(self._tmp.name), name, required_questions=questions or ["Q1"]
        )
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
            json.dumps(_valid_argument_map(run_dir.name, question_id="Q1")),
            encoding="utf-8",
        )
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("必答问题" in err and "Q2" in err for err in status["errors"]),
            status["errors"],
        )

    def test_claim_bound_to_noncurrent_result_blocks(self) -> None:
        """主张绑定的 result_id 不是当前 production 结果时阻断。"""
        run_dir = self._init("stale-result")
        (run_dir / "paper" / "argument_map.json").write_text(
            json.dumps(_valid_argument_map(run_dir.name, result_ids=["R-ghost"])),
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
                _valid_argument_map(run_dir.name, figure_ids=["F-critical"])
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
            json.dumps(_valid_argument_map(run_dir.name)), encoding="utf-8"
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
            json.dumps(_valid_argument_map(run_dir.name)), encoding="utf-8"
        )
        _write_content_blueprint(run_dir, {"mode": "pdf", "included_roles": []})
        status = check_paper_readiness(run_dir)
        self.assertFalse(status["ready"])
        self.assertTrue(
            any("source_code_appendix" in err for err in status["errors"]), status["errors"]
        )


if __name__ == "__main__":
    unittest.main()

