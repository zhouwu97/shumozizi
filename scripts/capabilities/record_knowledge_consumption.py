"""读取能力路由选择的本地知识资产并写入消费收据。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.capabilities import record_knowledge_consumption


def main() -> int:
    """解析命令行并输出冻结的知识消费收据。"""
    parser = argparse.ArgumentParser(description="登记 v3 路由选择的本地知识实际读取收据")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        payload = record_knowledge_consumption(args.run_dir)
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
