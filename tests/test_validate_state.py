"""通过命令行公共接口验证状态与路线跨文件约束。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import sha256_file
from shumozizi.questions.manifest import create_problem_manifest
from shumozizi.workflow.approval import (
    create_approval_request,
    materialize_route_approval,
)
from shumozizi.workflow.initialization import initialize_run
from tests.knowledge_snapshot_helpers import seed_empty_retrieval_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "codex" / "validate_state.py"


class ValidateStateCliTests(unittest.TestCase):
    """覆盖状态推进前必须阻断的结构和引用错误。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary.name)
        problem = self.repo_root / "problems/sample.md"
        problem.parent.mkdir(parents=True)
        problem.write_text("用于状态校验的测试题面。\n", encoding="utf-8")
        self.run_dir = initialize_run(
            self.repo_root,
            problem,
            "test-run",
            mode="training",
        )
        self.write_json(
            "state.json",
            {
                "schema_name": "workflow_state",
                "schema_version": "2.0",
                "run_schema_version": "2.0",
                "run_id": "test-run",
                "problem_source": "problems/sample.md",
                "mode": "training",
                "status": "ROUTE_LOCKED",
                "revision": 1,
                "completed_stages": ["route"],
                "active_stage": "model_spec",
                "route_locked": True,
                "paper_ready": False,
                "question_progress": {},
                "artifacts": {},
                "last_updated_by": "test",
                "updated_at": "2026-07-19T00:00:00+00:00",
                "history": [
                    {
                        "from_status": "WAITING_HUMAN_ROUTE",
                        "status": "ROUTE_LOCKED",
                        "event": "ROUTE_APPROVED",
                        "timestamp": "2026-07-19T00:00:00+00:00",
                        "actor": {"actor_id": "test", "actor_type": "system"},
                        "artifact_refs": [],
                    }
                ],
            },
        )
        create_problem_manifest(
            self.run_dir,
            [
                {
                    "question_id": "q1",
                    "title": "求解约束优化问题",
                    "required": True,
                    "required_outputs": [
                        {"output_id": "solution", "description": "最优决策", "unit": None}
                    ],
                    "depends_on": [],
                    "source_refs": ["题面"],
                }
            ],
        )
        snapshot_binding = seed_empty_retrieval_snapshot(self.repo_root, self.run_dir)
        self.write_json(
            "brief/route_candidates.json",
            {
                "schema_name": "route_candidates",
                "schema_version": "2.0",
                "run_id": "test-run",
                "run_config_lock_sha256": sha256_file(self.run_dir / "config/RUN_CONFIG_LOCK.json"),
                **snapshot_binding,
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
        request = create_approval_request(
            self.run_dir,
            "route",
            {
                "run_config_lock": self.run_dir / "config/RUN_CONFIG_LOCK.json",
                "route_candidates": self.run_dir / "brief/route_candidates.json",
            },
        )
        self.assertTrue(request.is_file())
        materialize_route_approval(
            self.run_dir,
            raw_user_response="批准路线 A",
            selected_route_id="route_a",
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

    def valid_route_lock(self, selected_route_id: str = "route_a") -> dict:
        """生成完整且已批准的 JSON 路线锁。"""
        value = json.loads((self.run_dir / "brief/ROUTE_LOCK.json").read_text(encoding="utf-8"))
        value["selected_route_id"] = selected_route_id
        return value

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
        self.assertTrue(any("schema_name" in item for item in payload["errors"]))


if __name__ == "__main__":
    unittest.main()
