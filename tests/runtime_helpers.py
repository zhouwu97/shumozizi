"""为运行时公共接口测试提供最小运行目录构造器。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from shumozizi.results.metrics import materialize_metric
from shumozizi.runtime.execution import verify_execution_record

REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = REPO_ROOT / "scripts" / "runtime" / "execute_experiment.py"
ACCEPTOR = REPO_ROOT / "scripts" / "runtime" / "accept_result.py"


class RuntimeFixture:
    """构造隔离运行目录，并只通过公开命令调用运行时。"""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temporary.name) / "runtime-test"
        for relative in ("code", "results", "executions/manifests"):
            (self.run_dir / relative).mkdir(parents=True, exist_ok=True)
        (self.run_dir / "results/candidates").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "results/metric_specs").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "results/sealed").mkdir(parents=True, exist_ok=True)
        self.write_json(
            "results/result_registry.json",
            {
                "schema_name": "result_registry",
                "schema_version": "2.0",
                "run_id": "runtime-test",
                "results": [],
            },
        )

    def close(self) -> None:
        """释放临时目录。"""
        self.temporary.cleanup()

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> Path:
        """写入格式稳定的 JSON。"""
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def write_script(self, name: str, body: str) -> Path:
        """写入运行目录内的 Python 实验脚本。"""
        path = self.run_dir / "code" / name
        path.write_text(body, encoding="utf-8")
        return path

    def manifest(
        self,
        execution_id: str,
        script_name: str,
        output_name: str,
        *,
        timeout_seconds: int = 10,
        cwd: str = ".",
    ) -> Path:
        """生成最小合法执行清单。"""
        return self.write_json(
            f"executions/manifests/{execution_id}.json",
            {
                "schema_name": "execution_manifest",
                "schema_version": "2.0",
                "execution_id": execution_id,
                "program": "python",
                "args": [f"code/{script_name}", f"results/{output_name}"],
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "input_files": [f"code/{script_name}"],
                "expected_outputs": [f"results/{output_name}"],
                "random_seed": 42,
            },
        )

    def candidate(
        self,
        result_id: str,
        execution_id: str,
        *,
        cycle: str = "baseline",
        baseline_result_id: str | None = None,
        innovation_claim_ids: list[str] | None = None,
        innovation_evidence: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """生成可交给准入器的候选结果。"""
        metric_id = f"{result_id}-value"
        report = verify_execution_record(self.run_dir, execution_id)
        if report["valid"]:
            record = json.loads(
                (self.run_dir / f"executions/{execution_id}/execution_record.json").read_text(
                    encoding="utf-8"
                )
            )
            output = record["output_files"][0]
            materialize_metric(
                self.run_dir,
                {
                    "metric_spec_id": metric_id,
                    "execution_record_id": execution_id,
                    "output_artifact": {
                        "path": output["path"],
                        "sha256": output["sha256"],
                    },
                    "extractor": {"id": "json-pointer", "selector": "/value"},
                    "raw_unit": "dimensionless",
                    "transform": None,
                    "final_unit": "dimensionless",
                },
            )
        claims = []
        for claim_id in innovation_claim_ids or []:
            evidence = [
                {
                    "result_id": item["evidence_result_id"],
                    "metric_spec_ids": [metric_id],
                    "relation": "supports",
                }
                for item in (innovation_evidence or [])
                if item["claim_id"] == claim_id
            ]
            claims.append(
                {
                    "claim_id": claim_id,
                    "claim": "测试创新主张",
                    "evidence": evidence,
                    "status": "keep",
                }
            )
        return {
            "result_id": result_id,
            "question_id": "q1",
            "cycle": cycle,
            "execution_record_id": execution_id,
            "metrics": [
                {
                    "name": "value",
                    "metric_spec_id": metric_id,
                    "value": 1,
                    "unit": "dimensionless",
                }
            ],
            "conclusion": "实验完成并产生可复验结果。",
            "constraint_checks": [
                {"check_id": "finite", "passed": True, "details": "输出均为有限值"}
            ],
            "validation_checks": [
                {"check_id": "shape", "passed": True, "details": "输出结构符合约定"}
            ],
            "baseline_result_id": baseline_result_id,
            "innovation_claims": claims,
        }

    def set_results(self, results: list[dict[str, Any]]) -> None:
        """替换注册表中的结果集合。"""
        accepted = [item for item in results if item.get("status") == "accepted"]
        for item in results:
            if item.get("status") != "accepted":
                self.write_json(f"results/candidates/{item['result_id']}.json", item)
        self.write_json(
            "results/result_registry.json",
            {
                "schema_name": "result_registry",
                "schema_version": "2.0",
                "run_id": "runtime-test",
                "results": accepted,
            },
        )

    def run_executor(self, manifest: Path) -> subprocess.CompletedProcess[str]:
        """调用统一执行器。"""
        return self._run([sys.executable, str(EXECUTOR), str(self.run_dir), str(manifest)])

    def run_acceptor(self, result_id: str) -> subprocess.CompletedProcess[str]:
        """调用唯一结果准入入口。"""
        return self._run(
            [
                sys.executable,
                str(ACCEPTOR),
                str(self.run_dir),
                "--result-id",
                result_id,
                "--paper-allowed",
            ]
        )

    @staticmethod
    def payload(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        """解析公共命令的 JSON 标准输出。"""
        return json.loads(completed.stdout)

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        """以 UTF-8 环境运行子进程。"""
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
