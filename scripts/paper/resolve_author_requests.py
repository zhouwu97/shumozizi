"""处理外部 Author 材料请求的命令行入口。

读取作者请求与决策输入（fulfill/substitute/waive/reject + route），把结果写入
``review/author-request-decisions.json``。请求永远不会自动变成实验任务。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, load_json  # noqa: E402
from shumozizi.paper.external_author import (  # noqa: E402
    decide_author_request,
    read_author_requests,
)


def main() -> int:
    """读取决策文件并记录作者请求裁决。"""
    parser = argparse.ArgumentParser(description="裁决外部 Author 材料请求")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, required=True, help="decisions.json")
    args = parser.parse_args()
    try:
        decisions_input = load_json(args.input).get("decisions", [])
        ledger = decide_author_request(args.run_dir, decisions_input)
        print(
            json.dumps(
                {
                    "status": "resolved",
                    "request_count": len(read_author_requests(args.run_dir)),
                    "decisions": ledger["decisions"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
