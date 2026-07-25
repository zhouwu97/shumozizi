"""在全面审核冻结后生成结构化查漏报告。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.simple.review_gaps import verify_review_gap_completion


def _next_round(directory: Path) -> Path:
    """返回下一个未占用的 ``round-N.json`` 路径。"""
    directory.mkdir(parents=True, exist_ok=True)
    numbers: list[int] = []
    for path in directory.glob("round-*.json"):
        try:
            numbers.append(int(path.stem.removeprefix("round-")))
        except ValueError:
            continue
    return directory / f"round-{max(numbers, default=0) + 1}.json"


def main() -> int:
    """读取结构化提取结果，绑定当前全面报告、事实与强断言后写入 gap。"""
    parser = argparse.ArgumentParser(description="生成全面审核后的结构化查漏报告")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--scope", choices=("scientific", "paper"), required=True)
    parser.add_argument("--review-file", required=True)
    parser.add_argument("--review-task-receipt", required=True)
    parser.add_argument(
        "--assessment",
        required=True,
        help="独立查漏提取的 JSON，必须含 risks、findings、closures；不从关键词自动判 covered。",
    )
    parser.add_argument(
        "--method-facts",
        required=True,
        help="当前实验显式/联合推断的 method_facts.json。",
    )
    parser.add_argument(
        "--strong-claims",
        required=True,
        help="全面报告冻结后提取的强断言 JSON；这是硬要求而非可选开关。",
    )
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    report = resolve_inside(run_dir, args.review_file, must_exist=True)
    task = resolve_inside(run_dir, args.review_task_receipt, must_exist=True)
    method_facts = resolve_inside(run_dir, args.method_facts, must_exist=True)
    strong_claims = resolve_inside(run_dir, args.strong_claims, must_exist=True)
    assessment = load_json(Path(args.assessment).resolve())
    if not isinstance(assessment, dict) or any(
        not isinstance(assessment.get(name), list)
        for name in ("risks", "findings", "closures")
    ):
        raise ContractError("assessment 必须是含 risks、findings、closures 三个数组的对象")
    task_payload = load_json(task)
    payload = {
        "schema_name": "review_gap_report",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "scope": args.scope,
        "review_file": relative_inside(run_dir, report).as_posix(),
        "review_sha256": sha256_file(report),
        "method_facts_file": relative_inside(run_dir, method_facts).as_posix(),
        "method_facts_sha256": sha256_file(method_facts),
        "strong_claims_file": relative_inside(run_dir, strong_claims).as_posix(),
        "strong_claims_sha256": sha256_file(strong_claims),
        "risks": assessment["risks"],
        "findings": assessment["findings"],
        "closures": assessment["closures"],
    }
    target = _next_round(run_dir / "review" / "gaps")
    atomic_json(target, payload)
    status = verify_review_gap_completion(
        run_dir,
        scope=args.scope,
        review_report={
            "report": {"file": payload["review_file"]},
            "task_receipt": {
                "file": relative_inside(run_dir, task).as_posix(),
                "task_id": task_payload.get("task_id"),
            },
            "reviewer": {"thread_id": task_payload.get("thread_id")},
        },
    )
    print(json.dumps({"gap_file": relative_inside(run_dir, target).as_posix(), **status}, ensure_ascii=False, indent=2))
    return 0 if status["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
