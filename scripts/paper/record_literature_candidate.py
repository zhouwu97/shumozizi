"""登记一个人工选择的文献候选或标记语言检索已执行。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.literature import record_candidate  # noqa: E402


def _main() -> int:
    parser = argparse.ArgumentParser(description="登记文献候选，不接受凭据字段")
    parser.add_argument("run_dir", type=Path, help="当前 v3 运行目录")
    parser.add_argument("--input", type=Path, help="候选来源 JSON")
    parser.add_argument(
        "--mark-language",
        action="append",
        choices=["zh", "en"],
        default=[],
        help="标记该语言检索已执行，可重复；没有候选时也可单独使用",
    )
    args = parser.parse_args()
    if args.input is None and not args.mark_language:
        parser.error("至少提供 --input 或 --mark-language")
    candidate = None
    if args.input is not None:
        try:
            candidate = json.loads(args.input.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"候选 JSON 无法读取: {exc}", file=sys.stderr)
            return 1
        if not isinstance(candidate, dict):
            print("候选 JSON 根节点必须是对象", file=sys.stderr)
            return 1
    try:
        report = record_candidate(args.run_dir, candidate, mark_languages=args.mark_language)
    except Exception as exc:  # noqa: BLE001 - CLI 需要把协议错误转成可读输出
        print(f"登记文献候选失败: {exc}", file=sys.stderr)
        return 1
    print(f"已更新文献检索报告，候选数: {len(report['candidates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
