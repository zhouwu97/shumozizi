"""验证红队覆盖声明不是 general-coverage 自报，而是动态风险差集 + 追问闭环。

覆盖 review 计划要求的七个失败场景：
- general-coverage 不能放行；
- 缺少动态风险不能放行；
- 虚构 heading/行号不能放行；
- insufficient 但无 follow-up 不能放行；
- follow-up 未关闭不能放行；
- 所有专项关闭后可以放行；
- 自由报告中发现未预设的新风险仍可保留为 additional finding。

覆盖门与路由派生解耦：required_risks 的派生逻辑单独由 _derive_required_risks
单元测试覆盖；本文件在 orchestrator 测试中 patch _route_required_risks，
以隔离 schema 校验、报告 SHA 绑定、位置真实性与追问闭环逻辑。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from shumozizi.core.io import ContractError
from shumozizi.simple.review import (
    _derive_required_risks,
    require_coverage_declaration_valid,
)

_REPORT = "# 搜索稳定性\n\n多种子分析显示解稳定。\n\n## 代理与精确\n\n一致。\n"


class RequiredRiskDerivationTests(unittest.TestCase):
    """动态派生：题型 + 工具链 + decision_space → 必答风险集。"""

    def test_optimization_family_requires_multiseed(self) -> None:
        risks = _derive_required_risks(
            {"problem_families": ["optimization"], "toolchain": {"production_engine": "python"}},
            None,
        )
        self.assertIn("optimization-multiseed", risks)
        self.assertNotIn("optimization-proxy-exact", risks)

    def test_matlab_optimization_adds_proxy_exact(self) -> None:
        risks = _derive_required_risks(
            {"problem_families": ["optimization"], "toolchain": {"production_engine": "matlab"}},
            None,
        )
        self.assertIn("optimization-proxy-exact", risks)

    def test_geometry_and_variable_action(self) -> None:
        risks = _derive_required_risks(
            {"problem_families": ["geometry_kinematics"], "toolchain": {}},
            {"questions": [{"question_id": "Q5", "decision_space": {"action_cardinality": "variable"}}]},
        )
        self.assertIn("geometry-continuous-boundary", risks)
        self.assertIn("geometry-finite-segment", risks)
        self.assertIn("action-activation-Q5", risks)

    def test_other_family_has_no_required_risk(self) -> None:
        risks = _derive_required_risks(
            {"problem_families": ["other"], "toolchain": {"production_engine": "python"}},
            None,
        )
        self.assertEqual({}, risks)


class CoverageGateOrchestratorTests(unittest.TestCase):
    """require_coverage_declaration_valid 的 schema/SHA/位置/闭环端到端行为。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "cov-run"
        (self.run_dir / "review").mkdir(parents=True)
        self.report = self.run_dir / "review" / "SCIENTIFIC_RED_TEAM.md"
        self.report.write_text(_REPORT, encoding="utf-8")
        self.report_sha = hashlib.sha256(self.report.read_bytes()).hexdigest()

    def _write_declaration(self, **overrides: Any) -> None:
        declaration: dict[str, Any] = {
            "schema_name": "red_team_coverage_declaration",
            "schema_version": "2.0",
            "run_id": self.run_dir.name,
            "review_file": "review/SCIENTIFIC_RED_TEAM.md",
            "report_sha256": self.report_sha,
            "covered_risks": [],
        }
        declaration.update(overrides)
        (self.run_dir / "review" / "red_team_coverage.json").write_text(
            json.dumps(declaration, ensure_ascii=False), encoding="utf-8"
        )

    def _touch(self, relative: str) -> str:
        path = self.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("专项追问产物\n", encoding="utf-8")
        return relative

    def _validate(self, required: dict[str, str]) -> None:
        with patch(
            "shumozizi.simple.review._route_required_risks", return_value=required
        ):
            require_coverage_declaration_valid(self.run_dir)

    def test_general_coverage_cannot_release(self) -> None:
        """general-coverage 占位 ID 不能替代具体动态风险。"""
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
            self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_missing_dynamic_risk_cannot_release(self) -> None:
        """动态派生的风险完全未覆盖时阻断。"""
        self._write_declaration(covered_risks=[])
        with self.assertRaisesRegex(ContractError, "未被充分覆盖|optimization-multiseed"):
            self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_fabricated_heading_cannot_release(self) -> None:
        """evidence_location 指向不存在的标题时阻断。"""
        self._write_declaration(
            covered_risks=[
                {
                    "risk_id": "optimization-multiseed",
                    "conclusion": "sufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#根本不存在的标题",
                }
            ]
        )
        with self.assertRaisesRegex(ContractError, "evidence_location"):
            self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_fabricated_line_range_cannot_release(self) -> None:
        """evidence_location 指向超出报告行数的行范围时阻断。"""
        self._write_declaration(
            covered_risks=[
                {
                    "risk_id": "optimization-multiseed",
                    "conclusion": "sufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md:L900-L999",
                }
            ]
        )
        with self.assertRaisesRegex(ContractError, "evidence_location"):
            self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_stale_report_sha_cannot_release(self) -> None:
        """报告内容变化使覆盖声明失效。"""
        self._write_declaration(
            report_sha256="0" * 64,
            covered_risks=[
                {
                    "risk_id": "optimization-multiseed",
                    "conclusion": "sufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#搜索稳定性",
                }
            ],
        )
        with self.assertRaisesRegex(ContractError, "report_sha256"):
            self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_insufficient_without_follow_up_cannot_release(self) -> None:
        """insufficient 风险缺少专项 follow-up 时阻断。"""
        self._write_declaration(
            covered_risks=[
                {
                    "risk_id": "optimization-multiseed",
                    "conclusion": "insufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#搜索稳定性",
                }
            ]
        )
        with self.assertRaisesRegex(ContractError, "follow_up"):
            self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_unclosed_follow_up_cannot_release(self) -> None:
        """follow-up 存在但未关闭时阻断。"""
        self._write_declaration(
            covered_risks=[
                {
                    "risk_id": "optimization-multiseed",
                    "conclusion": "insufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#搜索稳定性",
                }
            ],
            follow_ups=[
                {
                    "risk_id": "optimization-multiseed",
                    "task_receipt": self._touch("review/followups/ms-receipt.json"),
                    "report_file": self._touch("review/followups/ms-report.md"),
                    "status": "open",
                }
            ],
        )
        with self.assertRaisesRegex(ContractError, "未关闭|follow_up"):
            self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_all_follow_ups_closed_releases(self) -> None:
        """所有专项追问关闭且位置真实后放行。"""
        self._write_declaration(
            covered_risks=[
                {
                    "risk_id": "optimization-multiseed",
                    "conclusion": "insufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#搜索稳定性",
                }
            ],
            follow_ups=[
                {
                    "risk_id": "optimization-multiseed",
                    "task_receipt": self._touch("review/followups/ms-receipt.json"),
                    "report_file": self._touch("review/followups/ms-report.md"),
                    "status": "closed",
                }
            ],
        )
        # 不抛异常即通过
        self._validate({"optimization-multiseed": "多种子稳定性"})

    def test_additional_finding_is_preserved_and_allowed(self) -> None:
        """自由报告中发现的未预设新风险作为 additional finding 保留，不阻止放行。"""
        self._write_declaration(
            covered_risks=[
                {
                    "risk_id": "optimization-multiseed",
                    "conclusion": "sufficient",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#搜索稳定性",
                }
            ],
            additional_findings=[
                {
                    "risk_id": "unexpected-numerical-instability",
                    "note": "报告发现了预设集之外的数值不稳定现象，建议后续关注。",
                    "evidence_location": "review/SCIENTIFIC_RED_TEAM.md#代理与精确",
                }
            ],
        )
        declaration = None
        with patch(
            "shumozizi.simple.review._route_required_risks",
            return_value={"optimization-multiseed": "多种子稳定性"},
        ):
            declaration = require_coverage_declaration_valid(self.run_dir)
        self.assertEqual(
            "unexpected-numerical-instability",
            declaration["additional_findings"][0]["risk_id"],
        )


if __name__ == "__main__":
    unittest.main()

