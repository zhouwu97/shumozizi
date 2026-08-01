"""导入外部 Author 草稿并执行导入审计的命令行入口。

外部稿固定隔离到 ``paper/external-author/draft.tex``，不会覆盖 ``main.tex``。
审计存在客观失败（无法编译、未知图、未知引用、越界强主张）或已确认事实错误
时以退出码 1 阻断；否则推进 authoring_status 到 ``draft_imported``。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.paper.import_audit import import_external_draft  # noqa: E402


def main() -> int:
    """导入外部草稿并输出审计与状态。"""
    parser = argparse.ArgumentParser(description="导入 v3.4 外部 Author 草稿")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--draft", type=Path, default=None, help="外部草稿 .tex 路径")
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="跳过真实 LaTeX 编译（仅用于诊断）",
    )
    args = parser.parse_args()
    try:
        receipt = import_external_draft(
            args.run_dir,
            draft_source=args.draft,
            compile_draft=not args.no_compile,
        )
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "objective_failures": receipt["audit"].get("objective_failures", []),
                    "confirmed_fact_failures": [
                        item["finding_id"] for item in receipt["confirmed_fact_failures"]
                    ],
                    "findings_count": len(receipt["audit"].get("findings", [])),
                    "compiled": receipt["audit"].get("compiled"),
                    "handoff_fresh": receipt["handoff_fresh"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if receipt["status"] in {"draft_imported", "needs_rebase"} else 1
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
