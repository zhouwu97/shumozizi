"""结果准入与 RFC 8785 封存的命令行薄入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.results.sealing import admit_candidate


def main() -> int:
    """复验候选结果并封存。"""
    parser = argparse.ArgumentParser(description="接受并封存 Schema v2 候选结果")
    parser.add_argument("run_dir")
    parser.add_argument("--result-id", required=True)
    parser.add_argument("--candidate")
    parser.add_argument("--accepted-by", default="codex-desktop")
    parser.add_argument("--paper-allowed", action="store_true")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    candidate_path = (
        Path(args.candidate)
        if args.candidate
        else run_dir / "results" / "candidates" / f"{args.result_id}.json"
    )
    try:
        sealed = admit_candidate(
            run_dir,
            load_json(candidate_path),
            accepted_by=args.accepted_by,
            paper_allowed=args.paper_allowed,
        )
        payload = {"accepted": True, "result_id": sealed["result_id"]}
    except (ContractError, OSError, KeyError, ValueError) as exc:
        payload = {"accepted": False, "errors": [str(exc)]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
