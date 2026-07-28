from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shumozizi.knowledge.authoring import (
    verify_argument_map,
    write_argument_map,
    write_paper_blueprint,
)


class KnowledgeAuthoringTests(unittest.TestCase):
    def test_authoring_outputs_allow_inconclusive_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            (run_dir / "config").mkdir(parents=True)
            (run_dir / "claims").mkdir()
            (run_dir / "paper").mkdir()
            (run_dir / "config/RUN_CONFIG_LOCK.json").write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
            blueprint = write_paper_blueprint(run_dir, [{"question_id": "q1", "question": "回答什么"}])
            argument_map = write_argument_map(run_dir, [{"claim_id": "q1-c1", "claim": "未决", "outcome": "inconclusive", "scope": "当前实验"}])
            self.assertIn("inconclusive", argument_map.read_text(encoding="utf-8"))
            self.assertIn("PAPER_BLUEPRINT", blueprint.read_text(encoding="utf-8"))

    def test_blueprint_records_question_progression_and_content_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            (run_dir / "config").mkdir(parents=True)
            (run_dir / "claims").mkdir()
            (run_dir / "paper").mkdir()
            (run_dir / "config/RUN_CONFIG_LOCK.json").write_text(
                json.dumps({"run_id": "x"}), encoding="utf-8"
            )
            blueprint = write_paper_blueprint(
                run_dir,
                [
                    {"question_id": "q1", "question": "建立基础对象"},
                    {
                        "question_id": "q2",
                        "question": "扩展到约束场景",
                        "relationship": "inherits",
                        "inherits_from": ["q1"],
                        "inherited_object": "共享状态与判定器",
                        "new_difficulty": "新增整数约束",
                        "new_mechanism": "可行域递推",
                        "why_previous_insufficient": "基础模型不表达离散线数",
                        "answer_increment": "从局部计算升级为全局布局",
                        "algorithm": "可行构造与局部精化",
                        "algorithm_choice_reason": "响应混合非凸变量",
                    },
                ],
            )
            text = blueprint.read_text(encoding="utf-8")
            for marker in (
                "内容成熟度动作（按需往返，不是状态门）",
                "继承对象：共享状态与判定器",
                "新增困难：新增整数约束",
                "新增数学机制：可行域递推",
                "原模型为何不足：基础模型不表达离散线数",
                "相对前问的答案增量：从局部计算升级为全局布局",
                "算法与选型理由：可行构造与局部精化；响应混合非凸变量",
            ):
                self.assertIn(marker, text)

    def test_argument_map_detects_changed_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            (run_dir / "config").mkdir(parents=True)
            (run_dir / "claims").mkdir()
            (run_dir / "results").mkdir()
            (run_dir / "config/RUN_CONFIG_LOCK.json").write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
            (run_dir / "results/result_registry.json").write_text(json.dumps({"results": []}), encoding="utf-8")
            write_argument_map(run_dir, [])
            self.assertTrue(verify_argument_map(run_dir)["valid"])
            (run_dir / "results/result_registry.json").write_text(json.dumps({"results": [{"status": "accepted", "paper_allowed": True}]}), encoding="utf-8")
            self.assertFalse(verify_argument_map(run_dir)["valid"])


if __name__ == "__main__":
    unittest.main()
