"""创建供新 Codex 对话使用的冻结科学或 PDF 盲审包。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.review import build_review_packet


def main() -> int:
    """解析命令行并输出审查包清单位置。"""
    parser = argparse.ArgumentParser(description="创建 Capability-First v3 独立审查包")
    parser.add_argument("run_dir")
    parser.add_argument(
        "--kind", choices=("scientific", "paper-blind", "final-audit"), required=True
    )
    args = parser.parse_args()
    try:
        packet = build_review_packet(Path(args.run_dir), kind=args.kind)
        print(json.dumps(packet, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
