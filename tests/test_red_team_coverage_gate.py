"""验证动态风险派生、开放报告覆盖和专项追问的真实回执边界。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.simple.review import (
    derive_required_review_risks,
    require_coverage_declaration_valid,
)
from shumozizi.simple.review_tasks import create_review_task_receipt

_REPORT = "# 搜索稳定性\n\n多种子分析显示解稳定。\n\n## 代理与精确\n\n一致。\n"
_RISK_ID = "optimization.multiseed.Q1"


def _profile(**solver_properties: bool) -> dict[str, Any]:
    """构造只描述实际求解属性的方法画像。"""
    return {
        "questions": [
            {
                "question_id": "Q1",
                "model_families": ["other"],
                "solver_properties": solver_properties,
            }
        ]
    }


class RequiredRiskDerivationTests(unittest.TestCase):
    """风险由实际方法属性触发，而不是由题型或引擎名称猜测。"""

    def test_only_stochastic_triggers_multiseed(self) -> None:
        route = {"problem_families": ["optimization"], "toolchain": {}}
        stochastic = derive_required_review_risks(
            route, None, _profile(stochastic=True), None, []
        )
        deterministic = derive_required_review_risks(
            route, None, _profile(local_search=True), None, []
        )

        self.assertIn("optimization.multiseed.Q1", stochastic)
        self.assertNotIn("optimization.multiseed.Q1", deterministic)

    def test_only_proxy_property_triggers_proxy_exact(self) -> None:
        route = {
            "problem_families": ["optimization"],
            "toolchain": {"production_engine": "matlab"},
        }
        matlab_only = derive_required_review_risks(route, None, _profile(), None, [])
        proxy = derive_required_review_risks(
            route,
            None,
            _profile(uses_proxy_objective=True),
            None,
            [{"question_id": "Q1", "metrics": {"proxy_score": 1, "exact_score": 1}}],
        )

        self.assertNotIn("optimization.proxy_exact.Q1", matlab_only)
        self.assertNotIn("optimization.multiseed.Q1", matlab_only)
        self.assertIn("optimization.proxy_exact.Q1", proxy)

    def test_geometry_and_decision_risks_come_from_structured_facts(self) -> None:
        profile = _profile()
        profile["questions"][0]["mathematical_properties"] = {
            "continuous_geometry": True,
            "finite_segment_logic": True,
        }
        risks = derive_required_review_risks(
            {"problem_families": ["geometry_kinematics"], "toolchain": {}},
            {
                "questions": [
                    {
                        "question_id": "Q1",
                        "decision_space": {"action_cardinality": "variable"},
                    }
                ]
            },
            profile,
            None,
            [],
        )

        self.assertIn("geometry.continuous_boundary.Q1", risks)
        self.assertIn("geometry.finite_segment_endpoint.Q1", risks)
        self.assertIn("decision_space.activation.Q1", risks)

    def test_proxy_receipt_integrity_uses_execution_receipts(self) -> None:
        risks = derive_required_review_risks(
            {"problem_families": ["optimization"], "toolchain": {}},
            None,
            _profile(uses_proxy_objective=True),
            None,
            [{"question_id": "Q1", "metrics": {"objective": 1}}],
        )

        self.assertIn("optimization.proxy_receipt_integrity.Q1", risks)


class CoverageGateOrchestratorTests(unittest.TestCase):
    """覆盖声明必须具备报告、风险和真实任务的完整绑定。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "cov-run"
        (self.run_dir / "review").mkdir(parents=True)
        self.report = self.run_dir / "review" / "SCIENTIFIC_RED_TEAM.md"
        self.report.write_text(_REPORT, encoding="utf-8")
        atomic_json(
            self.run_dir / "review" / "required_risks.json",
            {
                "schema_name": "required_review_risks",
                "schema_version": "1.0",
                "run_id": self.run_dir.name,
                "source_bindings": {},
                "risks": [{"risk_id": _RISK_ID, "reason": "多种子稳定性"}],
                "generated_at": "2026-07-24T00:00:00Z",
            },
        )

    def _follow_up(self, *, status: str = "closed") -> dict[str, Any]:
        """创建绑定 coverage 父任务的真实专项报告与任务回执。"""
        report_file = "review/followups/multiseed.md"
        report = self.run_dir / report_file
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# 多种子专项\n\n已复现实验并关闭风险。\n", encoding="utf-8")
        receipt = create_review_task_receipt(
            self.run_dir,
            task_id="multiseed-follow-up",
            task_type="scientific_follow_up",
            thread_id="follow-up-thread",
            model_id="fixture-model",
            prompt_sha256="3" * 64,
            input_bindings={
                **self._coverage_inputs(),
                "risk_id": _RISK_ID,
            },
            report_file=report_file,
            parent_task_id="coverage-task",
        )
        return {
            "risk_id": _RISK_ID,
            "task_receipt": receipt.relative_to(self.run_dir).as_posix(),
            "report_file": report_file,
            "report_sha256": sha256_file(report),
            "status": status,
            "resolution": "独立多种子实验未发现结论翻转。",
            "closed_at": "2026-07-24T00:00:00Z",
        }

    def _coverage_inputs(self) -> dict[str, dict[str, str]]:
        """返回 coverage 提取器必须冻结的两项输入。"""
        return {
            "report": {
                "file": "review/SCIENTIFIC_RED_TEAM.md",
                "sha256": sha256_file(self.report),
            },
            "required_risks": {
                "file": "review/required_risks.json",
                "sha256": sha256_file(self.run_dir / "review" / "required_risks.json"),
            },
        }

    def _write_declaration(self, **overrides: Any) -> None:
        """写入 v3 声明，再创建绑定该声明的独立 coverage 回执。"""
        declaration: dict[str, Any] = {
            "schema_name": "red_team_coverage_declaration",
            "schema_version": "3.0",
            "run_id": self.run_dir.name,
            "review_file": "review/SCIENTIFIC_RED_TEAM.md",
            "report_sha256": sha256_file(self.report),
            "required_risks_file": "review/required_risks.json",
            "required_risks_sha256": sha256_file(
                self.run_dir / "review" / "required_risks.json"
            ),
            "coverage_task_receipt": "review/tasks/coverage-task/receipt.json",
            "covered_risks": [],
            "follow_ups": [],
            "additional_findings": [],
            "generated_at": "2026-07-24T00:00:00Z",
        }
        declaration.update(overrides)
        declaration_path = self.run_dir / "review" / "coverage" / "scientific.json"
        atomic_json(declaration_path, declaration)
        create_review_task_receipt(
            self.run_dir,
            task_id="coverage-task",
            task_type="coverage_extract",
            thread_id="coverage-thread",
            model_id="fixture-model",
            prompt_sha256="2" * 64,
            input_bindings=self._coverage_inputs(),
            report_file="review/coverage/scientific.json",
            parent_task_id="scientific-open",
        )

    def _validate(self) -> dict[str, Any]:
        """用固定风险集运行协调层差集校验。"""
        with patch(
            "shumozizi.simple.review._route_required_risks",
            return_value={_RISK_ID: "多种子稳定性"},
        ):
            return require_coverage_declaration_valid(
                self.run_dir,
                expected_parent_task_id="scientific-open",
            )

    @staticmethod
    def _covered(
        conclusion: str = "sufficient",
        location: str = "review/SCIENTIFIC_RED_TEAM.md#搜索稳定性",
    ) -> list[dict[str, str]]:
        """返回一条实际报告锚点覆盖。"""
        return [
            {
                "risk_id": _RISK_ID,
                "conclusion": conclusion,
                "evidence_location": location,
            }
        ]

    def test_unknown_or_missing_risk_cannot_release(self) -> None:
        self._write_declaration(
            covered_risks=[
                {
                    "risk_id": "general-coverage",
                    "conclusion": "sufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#搜索稳定性",
                }
            ]
        )
        with self.assertRaisesRegex(ContractError, "general-coverage|未派生"):
            self._validate()

    def test_fabricated_location_cannot_release(self) -> None:
        self._write_declaration(
            covered_risks=self._covered(
                location="review/SCIENTIFIC_RED_TEAM.md#不存在的标题"
            )
        )
        with self.assertRaisesRegex(ContractError, "evidence_location"):
            self._validate()

    def test_stale_report_or_risk_hash_cannot_release(self) -> None:
        self._write_declaration(
            report_sha256="0" * 64,
            covered_risks=self._covered(),
        )
        with self.assertRaisesRegex(ContractError, "report_sha256"):
            self._validate()

    def test_follow_up_requires_real_receipt_report_and_closed_resolution(self) -> None:
        follow_up = self._follow_up(status="open")
        self._write_declaration(
            covered_risks=self._covered("insufficient"),
            follow_ups=[follow_up],
        )
        with self.assertRaisesRegex(ContractError, "未关闭|closed|follow_up"):
            self._validate()

        follow_up = self._follow_up(status="closed")
        self._write_declaration(
            covered_risks=self._covered("insufficient"),
            follow_ups=[follow_up],
        )
        self.assertEqual("closed", self._validate()["follow_ups"][0]["status"])

    def test_additional_findings_respect_severity_and_disposition(self) -> None:
        finding = {
            "finding_id": "unexpected-instability",
            "severity": "P1",
            "question_ids": ["Q1"],
            "summary": "发现未预设的数值不稳定。",
            "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#代理与精确",
            "disposition": "blocking",
        }
        self._write_declaration(
            covered_risks=self._covered(), additional_findings=[finding]
        )
        with self.assertRaisesRegex(ContractError, "P1|必须阻断"):
            self._validate()

        finding["severity"] = "P2"
        with self.assertRaisesRegex(ContractError, "blocking|必须阻断"):
            self._write_declaration(
                covered_risks=self._covered(), additional_findings=[finding]
            )
            self._validate()

        finding["disposition"] = "advisory"
        self._write_declaration(
            covered_risks=self._covered(), additional_findings=[finding]
        )
        self.assertEqual("P2", self._validate()["additional_findings"][0]["severity"])


if __name__ == "__main__":
    unittest.main()
