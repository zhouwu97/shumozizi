"""对 Fresh Reviewer finding 执行 Editorial Adjudication 的命令行入口。

Reviewer 只给 ``severity_recommendation``；本命令确认 ``confirmed_severity``
并决定返修路由。confirmed P0/P1 进入硬阻断，confirmed fact failure 不可降级。
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
from shumozizi.paper.adjudication import record_adjudication  # noqa: E402


def main() -> int:
    """读取裁决输入并记录 adjudication。"""
    parser = argparse.ArgumentParser(description="裁决外部稿的 Reviewer finding")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, required=True, help="adjudication.json")
    args = parser.parse_args()
    try:
        decisions = load_json(args.input).get("decisions", [])
        document = record_adjudication(args.run_dir, decisions)
        print(
            json.dumps(
                {
                    "status": "adjudicated",
                    "decision_count": len(document["decisions"]),
                    "confirmed_p0_p1": [
                        d["finding_id"]
                        for d in document["decisions"]
                        if d["confirmed"] and d["confirmed_severity"] in {"P0", "P1"}
                    ],
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
