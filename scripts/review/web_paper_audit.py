"""管理网页版 GPT 的受限 PDF 审核与局部修复计划。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许从仓库根目录直接运行脚本，避免依赖开发环境已安装 editable package。
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.knowledge.external_discussion import (
    create_web_paper_audit_prompt,
    record_web_paper_audit,
    validate_web_paper_audit_if_present,
    web_paper_audit_status,
    write_web_paper_audit_failure,
    write_web_paper_repair_plan,
)


def main() -> int:
    """执行一个网页 PDF 审核协议动作。"""
    parser = argparse.ArgumentParser(description="管理网页版 GPT 的只读 PDF 论文审核")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prompt = subparsers.add_parser("prompt", help="生成只附 PDF 的固定审核提示")
    prompt.add_argument("run_dir", type=Path)
    prompt.add_argument("--pdf", default="paper/final.pdf")
    audit = subparsers.add_parser("record", help="导入结构化网页审核报告")
    audit.add_argument("run_dir", type=Path)
    audit.add_argument("--input", type=Path, required=True)
    repair = subparsers.add_parser("repair-plan", help="将审核发现转为局部修复计划")
    repair.add_argument("run_dir", type=Path)
    repair.add_argument("--input", type=Path, required=True)
    failure = subparsers.add_parser("failure-report", help="记录第三轮仍有 P0/P1 时的失败复盘")
    failure.add_argument("run_dir", type=Path)
    failure.add_argument("--input", type=Path, required=True)
    status = subparsers.add_parser("status", help="查看当前 PDF 是否通过网页审核放行")
    status.add_argument("run_dir", type=Path)
    validate = subparsers.add_parser("validate", help="复验现有网页审核绑定和修复计划")
    validate.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prompt":
            document = create_web_paper_audit_prompt(args.run_dir, args.pdf)
        elif args.command == "record":
            document = record_web_paper_audit(args.run_dir, load_json(args.input))
        elif args.command == "repair-plan":
            document = write_web_paper_repair_plan(args.run_dir, load_json(args.input))
        elif args.command == "failure-report":
            document = write_web_paper_audit_failure(args.run_dir, load_json(args.input))
        elif args.command == "status":
            document = web_paper_audit_status(args.run_dir)
        else:
            validate_web_paper_audit_if_present(args.run_dir)
            document = {"status": "valid"}
    except ContractError as exc:
        print(f"invalid: {exc}")
        return 1
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
