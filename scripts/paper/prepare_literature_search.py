"""生成按需文献检索计划。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.literature import prepare_search_plan  # noqa: E402


def _main() -> int:
    parser = argparse.ArgumentParser(description="生成双语文献检索计划")
    parser.add_argument("run_dir", type=Path, help="当前 v3 运行目录")
    parser.add_argument("--topic", action="append", required=True, help="检索主题，可重复")
    parser.add_argument(
        "--category",
        action="append",
        default=None,
        help="目标引用类别，可重复",
    )
    parser.add_argument("--reason", action="append", default=[], help="要求中文检索的题面理由")
    parser.add_argument(
        "--chinese-required",
        action="store_true",
        help="将中文检索设为必需；仅用于中国本土事实、标准或统计口径",
    )
    parser.add_argument(
        "--institutional-access",
        choices=["none", "manual-browser"],
        default="none",
        help="机构数据库访问模式；manual-browser 仍由用户亲自认证",
    )
    args = parser.parse_args()
    try:
        plan = prepare_search_plan(
            args.run_dir,
            topics=args.topic,
            categories=args.category or ["background", "core_method"],
            reasons=args.reason,
            chinese_required=args.chinese_required,
            institutional_access=args.institutional_access,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 需要把协议错误转成可读输出
        print(f"生成检索计划失败: {exc}", file=sys.stderr)
        return 1
    print(f"已生成双语检索计划: {args.run_dir / 'paper/generated/literature-search-plan.json'}")
    print(f"主题数: {len(plan['topics'])}; 中文检索必需: {plan['search_scope']['chinese_search_required']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
