"""执行独立科学红队的最小可复验证据脚本。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.review import run_red_team_evidence


def main() -> int:
    """解析受控参数并输出冻结的红队执行收据。"""
    parser = argparse.ArgumentParser(description="执行 Capability-First v3 红队证据脚本")
    parser.add_argument("run_dir")
    parser.add_argument("--id", required=True)
    parser.add_argument(
        "--kind",
        choices=(
            "independent-recompute",
            "counterexample",
            "small-enumeration",
            "alternative-formula",
            "search-challenge",
            "property-test",
            "action-activation-challenge",
            "geometry-continuous-validation",
        ),
        required=True,
    )
    parser.add_argument("--packet", required=True, help="冻结 scientific 审查包 manifest 路径")
    parser.add_argument("--script", required=True, help="review/red_team_artifacts/ 下的受控脚本")
    parser.add_argument("--engine", choices=("python", "matlab", "octave"), default="python")
    parser.add_argument("--output", action="append", required=True, help="脚本写入 outputs/ 下的相对输出名")
    parser.add_argument("--arg", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    try:
        receipt = run_red_team_evidence(
            Path(args.run_dir),
            evidence_id=args.id,
            kind=args.kind,
            packet_manifest=args.packet,
            script_path=args.script,
            output_paths=args.output,
            engine=args.engine,
            arguments=args.arg,
            timeout_seconds=args.timeout_seconds,
        )
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
