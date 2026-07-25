"""维护网页版讨论的延迟揭示与实现总结收据。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许从仓库根目录直接运行脚本，避免依赖开发环境已安装 editable package。
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.knowledge.external_discussion import (
    create_implementation_synthesis,
    record_external_discussion_comparison,
    record_external_discussion_launch,
    validate_external_discussion_protocol_if_present,
    write_local_route_snapshot,
)


def main() -> int:
    """执行一个明确的网页讨论协议动作。"""
    parser = argparse.ArgumentParser(description="管理网页 GPT 的本地先行讨论协议")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("freeze-local", "冻结只基于 problem/ 的本地路线"),
        ("launch", "登记不披露本地路线且延迟阅读的网页讨论"),
        ("compare", "记录本地路线与网页建议的差异和验证动作"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("run_dir", type=Path)
        command.add_argument("--input", type=Path, required=True)
    synthesis = subparsers.add_parser("synthesis", help="生成只能交给全新网页对话的实现总结提示")
    synthesis.add_argument("run_dir", type=Path)
    validate = subparsers.add_parser("validate", help="校验已有的可选网页讨论协议")
    validate.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "freeze-local":
            document = write_local_route_snapshot(args.run_dir, load_json(args.input))
        elif args.command == "launch":
            document = record_external_discussion_launch(args.run_dir, load_json(args.input))
        elif args.command == "compare":
            document = record_external_discussion_comparison(args.run_dir, load_json(args.input))
        elif args.command == "synthesis":
            document = create_implementation_synthesis(args.run_dir)
        else:
            validate_external_discussion_protocol_if_present(args.run_dir)
            document = {"status": "valid"}
    except ContractError as exc:
        print(f"invalid: {exc}")
        return 1
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
