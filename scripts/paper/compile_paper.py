"""按已选择的 v3 模板受控编译论文。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.compiler import compile_paper


def main() -> int:
    """编译论文并输出冻结回执。"""
    parser = argparse.ArgumentParser(description="编译 Capability-First v3 论文并写入回执")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    try:
        payload = compile_paper(args.run_dir, timeout_seconds=args.timeout)
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
