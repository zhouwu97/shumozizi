"""验证论文贡献表述必须服从 claim evidence 状态和 stale 门禁。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shumozizi.claims.evaluator import EVALUATOR_VERSION
from shumozizi.core.schema import validate_document
from shumozizi.paper.gate import (
    gate_contribution_claims,
    gate_paper_claims,
    require_paper_claim_allowed,
)
from tests.test_semantic_schemas import claim_evidence


class PaperClaimGateTests(unittest.TestCase):
    """覆盖四种 claim 状态、无主张和 stale。"""

    def test_supported_allows_deterministic_contribution(self) -> None:
        gate = gate_contribution_claims(claim_evidence("supported"))

        claim = require_paper_claim_allowed(gate, "IC-Q1-01", use="contribution")

        self.assertEqual("full", claim["contribution_mode"])
        self.assertIn("results", claim["allowed_uses"])

    def test_partially_supported_only_allows_limited_contribution(self) -> None:
        gate = gate_contribution_claims(claim_evidence("partially_supported"))

        with self.assertRaisesRegex(ValueError, "不允许用于 contribution"):
            require_paper_claim_allowed(gate, "IC-Q1-01", use="contribution")
        claim = require_paper_claim_allowed(gate, "IC-Q1-01", use="limited_contribution")
        self.assertEqual("limited", claim["contribution_mode"])

    def test_rejected_allows_results_and_failure_analysis_only(self) -> None:
        gate = gate_contribution_claims(claim_evidence("rejected"))

        with self.assertRaisesRegex(ValueError, "不允许用于 contribution"):
            require_paper_claim_allowed(gate, "IC-Q1-01", use="contribution")
        require_paper_claim_allowed(gate, "IC-Q1-01", use="results")
        require_paper_claim_allowed(gate, "IC-Q1-01", use="failure_analysis")

    def test_inconclusive_forbids_deterministic_contribution(self) -> None:
        gate = gate_contribution_claims(claim_evidence("inconclusive"))

        with self.assertRaisesRegex(ValueError, "不允许用于 contribution"):
            require_paper_claim_allowed(gate, "IC-Q1-01", use="contribution")
        require_paper_claim_allowed(gate, "IC-Q1-01", use="inconclusive_discussion")

    def test_stale_claim_evidence_forbids_every_reference(self) -> None:
        evidence = claim_evidence("supported")
        evidence["stale"] = True
        evidence["stale_reason"] = "evaluator_version 已变化"
        gate = gate_contribution_claims(evidence)

        self.assertFalse(gate["claims"][0]["reference_allowed"])
        self.assertEqual([], gate["claims"][0]["allowed_uses"])
        with self.assertRaisesRegex(ValueError, "已 stale"):
            require_paper_claim_allowed(gate, "IC-Q1-01", use="results")

    def test_claimability_none_has_no_contribution_claims(self) -> None:
        evidence = claim_evidence()
        evidence["claimability"] = "none"
        evidence["claimability_reason"] = "本问题不声明方法创新"
        evidence["claims"] = []

        gate = gate_contribution_claims(evidence)

        self.assertEqual("none", gate["claimability"])
        self.assertEqual([], gate["claims"])

    def test_filesystem_gate_binds_evidence_hash_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evidence_path = run_dir / "claims/claim_evidence.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps(claim_evidence("supported"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = evidence_path.read_bytes()

            gate = gate_paper_claims(run_dir)

            self.assertEqual([], validate_document(gate, "paper_claim_gate"))
            self.assertEqual(before, evidence_path.read_bytes())
            self.assertEqual(EVALUATOR_VERSION, gate["evaluator_version"])
            self.assertTrue((run_dir / "paper/claim_gate.json").is_file())


if __name__ == "__main__":
    unittest.main()
