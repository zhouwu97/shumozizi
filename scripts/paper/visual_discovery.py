"""生成、记录并复验开放式论文视觉发现审查。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.paper.visual_discovery import (  # noqa: E402
    build_visual_discovery_prompt,
    record_visual_discovery,
    validate_visual_discovery_closure,
)


def _parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser(description="开放式论文视觉缺口审查")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prompt = subparsers.add_parser("prompt", help="输出 frozen-PDF-only 审查提示")
    prompt.add_argument("run_dir", type=Path)
    prompt.add_argument("--pdf", dest="pdf_path")

    record = subparsers.add_parser("record", help="导入独立审核者返回的 JSON")
    record.add_argument("run_dir", type=Path)
    record.add_argument("payload", type=Path)
    record.add_argument("--reviewer-context-id", required=True)
    record.add_argument("--pdf", dest="pdf_path")

    status = subparsers.add_parser("status", help="复验审查新鲜度和高影响 finding")
    status.add_argument("run_dir", type=Path)
    return parser


def _main() -> int:
    """执行开放式视觉审查 CLI。"""
    args = _parser().parse_args()
    try:
        if args.command == "prompt":
            print(build_visual_discovery_prompt(args.run_dir, args.pdf_path))
            return 0
        if args.command == "record":
            payload = json.loads(args.payload.read_text(encoding="utf-8"))
            record = record_visual_discovery(
                args.run_dir,
                payload,
                reviewer_context_id=args.reviewer_context_id,
                pdf_path=args.pdf_path,
            )
            print(json.dumps(record, ensure_ascii=False, indent=2))
            return 0
        errors = validate_visual_discovery_closure(args.run_dir)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("[OK] 开放式视觉发现审查有效且无未关闭高影响 finding")
        return 0
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
