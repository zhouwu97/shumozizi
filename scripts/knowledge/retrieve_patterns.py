"""为单次运行生成路线前的知识检索产物。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.papers import write_retrieval_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="检索仓内论文卡并生成迁移计划")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--index", type=Path, default=Path("knowledge/indexes/papers_verified.json")
    )
    parser.add_argument("--problem-type", required=True)
    parser.add_argument("--data-structure", required=True)
    parser.add_argument("--task-type", action="append", default=[])
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--structural-tag", action="append", default=[])
    parser.add_argument("--question", action="append", default=[])
    parser.add_argument("--data-constraint", action="append", default=[])
    parser.add_argument("--canonical-problem-id", required=True)
    parser.add_argument("--problem-asset-sha256", required=True)
    args = parser.parse_args()
    outputs = write_retrieval_artifacts(
        args.run_dir,
        args.index,
        {
            "problem_type": args.problem_type,
            "data_structure": args.data_structure,
            "task_types": args.task_type,
            "keywords": args.keyword,
            "structural_tags": args.structural_tag,
            "question_chain": args.question,
            "data_constraints": args.data_constraint,
            "canonical_problem_id": args.canonical_problem_id,
            "problem_asset_sha256": args.problem_asset_sha256,
        },
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
