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


def _apply_repair_routes(run_dir: Path, ledger: dict) -> list[dict]:
    """把裁决后的修复指令真正执行（路由从标签升级为命令）。

    experiment/analysis 的 fulfill 会把顶层 phase 沿合法迁移图切回对应阶段；
    执行失败的入口门禁（如实验计划不完整）会让 CLI 以 blocked 退出，而不是
    只在台账里标一行 rework_requested 就宣称"已路由返修"。
    """
    from shumozizi.paper.repair_loop import apply_repair_route

    applied: list[dict] = []
    for decision in ledger["decisions"]:
        if (
            decision.get("route") not in {"experiment", "analysis"}
            or decision.get("decision") != "fulfill"
        ):
            continue
        directive_id = f"req-{decision['gap_id']}"
        entry = apply_repair_route(run_dir, directive_id)
        applied.append({"gap_id": decision["gap_id"], "route": entry["route"]})
    return applied


def main() -> int:
    """读取决策文件，记录作者请求裁决并执行修复路由。"""
    parser = argparse.ArgumentParser(description="裁决外部 Author 材料请求")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, required=True, help="decisions.json")
    args = parser.parse_args()
    try:
        decisions_input = load_json(args.input).get("decisions", [])
        ledger = decide_author_request(args.run_dir, decisions_input)
        applied = _apply_repair_routes(args.run_dir, ledger)
        print(
            json.dumps(
                {
                    "status": "resolved",
                    "request_count": len(read_author_requests(args.run_dir)),
                    "decisions": ledger["decisions"],
                    "applied_repair_routes": applied,
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
