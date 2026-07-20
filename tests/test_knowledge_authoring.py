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
