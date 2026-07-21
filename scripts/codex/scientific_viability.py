"""创建或复验轻量科学存活检查与补充证据包。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.workflow.viability import (
    create_minimum_scientific_contract,
    create_scientific_viability,
    freeze_supplemental_evidence,
    r5_review_mode_for_changes,
    verify_minimum_scientific_contract,
    verify_scientific_viability,
)


def _material(value: str) -> tuple[str, Path]:
    evidence_id, separator, path = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("材料格式必须为 evidence_id=path")
    return evidence_id, Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="科学存活检查轻量 helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="创建 SCIENTIFIC_VIABILITY.md")
    init.add_argument("run_dir", type=Path)
    init.add_argument("--question", action="append", required=True)
    init.add_argument("--source", action="append", type=Path, default=[])

    verify = subparsers.add_parser("verify", help="复验 SCIENTIFIC_VIABILITY.md")
    verify.add_argument("run_dir", type=Path)
    verify.add_argument("--path", type=Path)
    verify.add_argument("--allow-pending", action="store_true")
    verify.add_argument("--paper-entry", action="store_true")

    init_contract = subparsers.add_parser(
        "init-contract", help="创建 MINIMUM_SCIENTIFIC_CONTRACT.md"
    )
    init_contract.add_argument("run_dir", type=Path)
    init_contract.add_argument("--source", action="append", type=Path, default=[])

    verify_contract = subparsers.add_parser(
        "verify-contract", help="复验 MINIMUM_SCIENTIFIC_CONTRACT.md"
    )
    verify_contract.add_argument("run_dir", type=Path)
    verify_contract.add_argument("--path", type=Path)

    freeze = subparsers.add_parser("freeze-supplemental", help="冻结审核补充证据")
    freeze.add_argument("run_dir", type=Path)
    freeze.add_argument("bundle_id")
    freeze.add_argument("stage")
    freeze.add_argument("issue")
    freeze.add_argument("--question-id")
    freeze.add_argument("--source-version")
    freeze.add_argument("--material", action="append", type=_material, required=True)

    scope = subparsers.add_parser("r5-scope", help="判断 R5 复核范围")
    scope.add_argument("--change", action="append", default=[])

    args = parser.parse_args()
    if args.command == "init":
        path = create_scientific_viability(
            args.run_dir,
            question_scope=args.question,
            source_paths=args.source,
        )
        print(path)
        return 0
    if args.command == "verify":
        report = verify_scientific_viability(
            args.run_dir,
            args.path,
            require_decision=not args.allow_pending,
            require_paper_eligibility=args.paper_entry,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 1
    if args.command == "freeze-supplemental":
        path = freeze_supplemental_evidence(
            args.run_dir,
            bundle_id=args.bundle_id,
            stage=args.stage,
            issue=args.issue,
            materials=dict(args.material),
            question_id=args.question_id,
            source_version=args.source_version,
        )
        print(path)
        return 0
    if args.command == "init-contract":
        path = create_minimum_scientific_contract(
            args.run_dir,
            source_paths=args.source,
        )
        print(path)
        return 0
    if args.command == "verify-contract":
        report = verify_minimum_scientific_contract(args.run_dir, args.path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 1
    print(r5_review_mode_for_changes(args.change))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
