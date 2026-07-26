"""绑定 Competition-First 科学挑战实际攻击使用的执行结果。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.simple.review_focus import record_scientific_challenge_evidence


def main() -> int:
    """解析 CLI 并保存挑战证据收据。"""
    parser = argparse.ArgumentParser(description="登记科学挑战的实际执行证据")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--result-id", action="append", required=True)
    parser.add_argument("--comparison-result-id", action="append", default=[])
    parser.add_argument("--attack", required=True)
    args = parser.parse_args()
    payload = record_scientific_challenge_evidence(
        args.run_dir.resolve(),
        result_ids=args.result_id,
        comparison_result_ids=args.comparison_result_id,
        attack_description=args.attack,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
