"""更新或检查 science-first 运行的薄层科学检查点。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.simple.science_checkpoint import (
    science_checkpoint_status,
    update_science_checkpoint,
)


def main() -> int:
    """执行 status 或 update 子命令。"""
    parser = argparse.ArgumentParser(description="管理 science-first 科学检查点")
    parser.add_argument("command", choices=("status", "update"))
    parser.add_argument("run_dir")
    parser.add_argument("--input", help="包含 semantic_contract/routes/falsification 的 JSON")
    parser.add_argument("--status", choices=("draft", "ready"))
    args = parser.parse_args()
    root = Path(args.run_dir)
    if args.command == "status":
        print(json.dumps(science_checkpoint_status(root), ensure_ascii=False, indent=2))
        return 0
    patch = {}
    if args.input:
        patch = json.loads(Path(args.input).read_text(encoding="utf-8"))
    payload = update_science_checkpoint(root, patch, status=args.status)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
