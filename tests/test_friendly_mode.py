"""验证 Friendly Mode 只展示请求，不削弱人工批准协议。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.workflow.friendly import present_route_checkpoint


class FriendlyModeTests(unittest.TestCase):
    """人工提示必须可恢复、可核验且不自动创建回执。"""

    def test_route_prompt_numbers_recommended_option_without_approval(self) -> None:
        """路线提示包含推荐标记和稳定编号，但不会物化 ROUTE_LOCK。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            (run_dir / "brief").mkdir(parents=True)
            atomic_json(
                run_dir / "brief/route_candidates.json",
                {
                    "schema_name": "route_candidates",
                    "schema_version": "2.0",
                    "run_id": "run",
                    "run_config_lock_sha256": "0" * 64,
                    "retrieval_snapshot_path": "knowledge/RETRIEVAL_SNAPSHOT.json",
                    "retrieval_snapshot_sha256": "0" * 64,
                    "problem_summary": "固定题面",
                    "ambiguities": [],
                    "recommended_route_id": "r2",
                    "recommendation_reason": "简单且可复验",
                    "candidates": [
                        {
                            "route_id": "r1",
                            "name": "基线",
                            "problem_interpretation": "固定",
                            "mathematical_nature": "确定性",
                            "baseline": "直接",
                            "primary_model": "直接",
                            "innovation": "无",
                            "validation": "精确",
                            "computational_cost": "低",
                            "risks": ["范围窄"],
                            "fallback": "直接",
                        },
                        {
                            "route_id": "r2",
                            "name": "增强",
                            "problem_interpretation": "固定",
                            "mathematical_nature": "确定性",
                            "baseline": "直接",
                            "primary_model": "增强",
                            "innovation": "可复验",
                            "validation": "交叉",
                            "computational_cost": "中",
                            "risks": ["成本"],
                            "fallback": "基线",
                        },
                    ],
                },
            )
            atomic_json(
                run_dir / "brief/route_approval_request.json",
                {
                    "schema_name": "approval_request",
                    "schema_version": "2.0",
                    "request_id": "run-route-r0",
                    "run_id": "run",
                    "approval_kind": "route",
                    "bindings": {},
                    "state_revision": 1,
                    "warnings": [],
                    "requested_at": "2026-07-19T00:00:00Z",
                },
            )

            prompt = present_route_checkpoint(run_dir)

            self.assertEqual([1, 2], [item["number"] for item in prompt["options"]])
            self.assertTrue(prompt["options"][1]["recommended"])
            self.assertFalse(prompt["receipt_created"])
            self.assertFalse((run_dir / "brief/ROUTE_LOCK.json").exists())
            self.assertIn("选择 1", prompt["message"])


if __name__ == "__main__":
    unittest.main()
