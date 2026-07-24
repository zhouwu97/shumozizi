"""编译前轻量硬门检查（CLI 包装）。

硬门核心已迁入 ``shumozizi.paper.readiness``，供编译器直接调用；本脚本只是
命令行入口，便于人工在编译前手动预检。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.readiness import check_paper_readiness  # noqa: E402

_EXIT_OK = 0
_EXIT_BLOCKED = 1


def _main() -> int:
    parser = argparse.ArgumentParser(description="编译前轻量硬门检查")
    parser.add_argument("run_dir", type=Path, help="v3 运行目录")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查不阻断（返回码 0 但报告问题）",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        print(f"运行目录不存在: {run_dir}", file=sys.stderr)
        return _EXIT_BLOCKED

    status = check_paper_readiness(run_dir)

    if status["ready"]:
        print("✅ 论文编译前提检查通过")
        return _EXIT_OK

    print("❌ 论文编译前提未满足:", file=sys.stderr)
    for error in status["errors"]:
        print(f"  - {error}", file=sys.stderr)

    if args.check_only:
        print("\n--check-only 模式：不阻断流程", file=sys.stderr)
        return _EXIT_OK

    return _EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(_main())
