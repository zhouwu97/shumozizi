"""审计文献检索计划和候选来源。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.literature import audit_search  # noqa: E402


def _main() -> int:
    parser = argparse.ArgumentParser(description="审计双语文献检索记录")
    parser.add_argument("run_dir", type=Path, help="当前 v3 运行目录")
    args = parser.parse_args()
    try:
        report = audit_search(args.run_dir)
    except Exception as exc:  # noqa: BLE001 - CLI 需要把协议错误转成可读输出
        print(f"文献检索审计失败: {exc}", file=sys.stderr)
        return 1
    print(f"检索审计状态: {report['audit']['status']}")
    for item in report["audit"]["errors"]:
        print(f"ERROR: {item}", file=sys.stderr)
    for item in report["audit"]["warnings"]:
        print(f"WARNING: {item}")
    return 1 if report["audit"]["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(_main())
