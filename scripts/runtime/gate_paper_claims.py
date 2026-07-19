"""依据 claim evidence 生成论文贡献主张门禁报告。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.gate import gate_paper_claims


def main() -> int:
    """生成 paper claim gate。"""
    parser = argparse.ArgumentParser(description="限制论文贡献主张的证据门禁")
    parser.add_argument("run_dir")
    parser.add_argument("--evidence")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        gate = gate_paper_claims(
            Path(args.run_dir),
            evidence_path=Path(args.evidence) if args.evidence else None,
            output_path=Path(args.output) if args.output else None,
        )
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"gated": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
