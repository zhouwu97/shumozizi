"""统一实验执行器的命令行薄入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError
from shumozizi.runtime.execution import execute


def main() -> int:
    """解析参数、执行实验并输出 JSON 摘要。"""
    parser = argparse.ArgumentParser(description="执行 Schema v2 实验清单")
    parser.add_argument("run_dir")
    parser.add_argument("manifest")
    args = parser.parse_args()
    try:
        payload = execute(Path(args.run_dir), Path(args.manifest))
    except (ContractError, OSError) as exc:
        payload = {"success": False, "errors": [str(exc)]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
