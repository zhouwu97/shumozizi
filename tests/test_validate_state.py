"""通过命令行公共接口验证状态与路线跨文件约束。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "codex" / "validate_state.py"


class ValidateStateCliTests(unittest.TestCase):
    """覆盖状态推进前必须阻断的结构和引用错误。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temporary.name) / "test-run"
        for name in ("brief", "results", "code", "paper", "executions/manifests"):
            (self.run_dir / name).mkdir(parents=True, exist_ok=True)
        self.write_json(
            "state.json",
            {
                "schema_version": "1.0",
                "run_id": "test-run",
                "problem_source": "problems/sample.md",
                "mode": "training",
                "status": "ROUTE_LOCKED",
                "completed_stages": ["route"],
                "active_stage": "model_spec",
                "route_locked": True,
                "paper_ready": False,
                "question_progress": {},
                "artifacts": {},
                "last_updated_by": "test",
                "updated_at": "2026-07-19T00:00:00+00:00",
                "history": [],
            },
        )
        self.write_json(
            "brief/route_candidates.json",
            {
                "run_id": "test-run",
                "problem_summary": "这是一个用于验证路线锁运行时行为的最小数学建模问题摘要。",
                "ambiguities": [],
                "recommended_route_id": "route_a",
                "recommendation_reason": "路线 A 计算成本较低且能够提供可解释的基线。",
                "candidates": [
                    self.candidate("route_a", "路线 A"),
                    self.candidate("route_b", "路线 B"),
                ],
            },
        )
        self.write_json(
            "results/result_registry.json",
            {"schema_version": "1.0", "run_id": "test-run", "results": []},
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def candidate(route_id: str, name: str) -> dict:
        """生成满足候选路线 Schema 的最小记录。"""
        return {
            "route_id": route_id,
            "name": name,
            "problem_interpretation": "根据输入数据建立可复现的优化与验证模型。",
            "mathematical_nature": "约束优化",
            "baseline": "线性基线模型",
            "primary_model": "稳健优化模型",
            "innovation": "加入不确定性集合",
            "validation": "敏感性和消融验证",
            "computational_cost": "低至中等",
            "risks": ["数据规模不足"],
            "fallback": "退回线性模型",
        }

    def write_json(self, relative_path: str, payload: dict) -> None:
        """写入测试运行目录中的 JSON。"""
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def valid_route_lock(selected_route_id: str = "route_a") -> dict:
        """生成完整且已批准的 JSON 路线锁。"""
        return {
            "approved": True,
            "selected_route_id": selected_route_id,
            "problem_interpretation": "根据输入数据建立可复现的优化与验证模型。",
            "primary_route": "稳健优化模型",
            "fallback_route": "线性基线模型",
            "required_baselines": ["线性基线模型"],
            "innovation": {"major_per_question": 1, "minor_per_question": 1, "claims": []},
            "validation": ["敏感性分析"],
            "resource_limits": {
                "max_main_experiment_cycles_per_question": 3,
                "max_web_searches": 5,
                "max_full_self_reviews": 1,
                "route_drift_budget_ratio": 0.3,
            },
            "approved_by": "human",
            "approved_at": "2026-07-19T00:00:00+00:00",
        }

    def run_validator(self) -> tuple[subprocess.CompletedProcess[str], dict]:
        """调用与桌面任务相同的状态校验入口。"""
        completed = subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.run_dir)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return completed, json.loads(completed.stdout)

    def test_rejects_route_lock_with_invalid_nested_resource_limits(self) -> None:
        """嵌套资源限制类型错误时不得进入 ROUTE_LOCKED。"""
        route_lock = self.valid_route_lock()
        route_lock["resource_limits"]["max_main_experiment_cycles_per_question"] = "three"
        self.write_json("brief/ROUTE_LOCK.json", route_lock)

        completed, payload = self.run_validator()

        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("route_lock.schema.json" in item for item in payload["errors"]))

    def test_rejects_recommended_route_id_missing_from_candidates(self) -> None:
        """推荐路线必须真实存在于候选路线集合。"""
        path = self.run_dir / "brief/route_candidates.json"
        candidates = json.loads(path.read_text(encoding="utf-8"))
        candidates["recommended_route_id"] = "route_missing"
        self.write_json("brief/route_candidates.json", candidates)
        self.write_json("brief/ROUTE_LOCK.json", self.valid_route_lock())

        completed, payload = self.run_validator()

        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("recommended_route_id" in item for item in payload["errors"]))

    def test_rejects_duplicate_candidate_route_ids(self) -> None:
        """候选路线 ID 必须唯一。"""
        path = self.run_dir / "brief/route_candidates.json"
        candidates = json.loads(path.read_text(encoding="utf-8"))
        candidates["candidates"][1]["route_id"] = "route_a"
        self.write_json("brief/route_candidates.json", candidates)
        self.write_json("brief/ROUTE_LOCK.json", self.valid_route_lock())

        completed, payload = self.run_validator()

        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("route_id 重复" in item for item in payload["errors"]))

    def test_rejects_selected_route_id_missing_from_candidates(self) -> None:
        """人工选择只能锁定已生成的候选路线。"""
        self.write_json("brief/ROUTE_LOCK.json", self.valid_route_lock("route_missing"))

        completed, payload = self.run_validator()

        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("selected_route_id" in item for item in payload["errors"]))

    def test_rejects_invalid_nested_candidate_structure_via_schema(self) -> None:
        """候选路线嵌套字段损坏时由正式 Schema 阻断。"""
        path = self.run_dir / "brief/route_candidates.json"
        candidates = json.loads(path.read_text(encoding="utf-8"))
        candidates["candidates"][0]["risks"] = "不是数组"
        self.write_json("brief/route_candidates.json", candidates)
        self.write_json("brief/ROUTE_LOCK.json", self.valid_route_lock())

        completed, payload = self.run_validator()

        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("risks" in item for item in payload["errors"]))

    def test_rejects_accepted_result_without_execution_contract(self) -> None:
        """旧式 accepted 结果不得绕过新的执行证据合同。"""
        self.write_json("brief/ROUTE_LOCK.json", self.valid_route_lock())
        self.write_json(
            "results/result_registry.json",
            {
                "schema_version": "1.0",
                "run_id": "test-run",
                "results": [
                    {
                        "result_id": "legacy",
                        "question_id": "q1",
                        "cycle": "baseline",
                        "status": "accepted",
                        "paper_allowed": True,
                        "source_script": "code/q1.py",
                        "metrics": {},
                    }
                ],
            },
        )

        completed, payload = self.run_validator()

        self.assertEqual(1, completed.returncode)
        self.assertTrue(any("result_registry.schema.json" in item for item in payload["errors"]))


if __name__ == "__main__":
    unittest.main()
