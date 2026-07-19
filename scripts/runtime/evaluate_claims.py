"""从 accepted results 评估结构化创新主张。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# Windows 默认控制台代码页可能无法编码证据中的中文，CLI 始终输出 UTF-8 JSON。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from shumozizi.claims.evaluator import EVALUATOR_VERSION, evaluate_claims
from shumozizi.core.io import ContractError


def main() -> int:
    """评估 claims，输入变化时标记旧证据 stale。"""
    parser = argparse.ArgumentParser(description="从 accepted results 评估结构化创新主张")
    parser.add_argument("run_dir")
    parser.add_argument("--evaluator-version", default=EVALUATOR_VERSION)
    parser.add_argument("--comparison-output", action="append", default=[])
    parser.add_argument("--output")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="忽略现有 evidence，依据当前输入重新计算",
    )
    args = parser.parse_args()
    try:
        evidence = evaluate_claims(
            Path(args.run_dir),
            evaluator_version=args.evaluator_version,
            comparison_output_paths=[Path(item) for item in args.comparison_output],
            output_path=Path(args.output) if args.output else None,
            refresh=args.refresh,
        )
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"evaluated": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
