"""将已被新生产结果或新语义 scorer 替代的 current 条目标记为历史条目。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import atomic_json
from shumozizi.simple.results import read_result_index, require_result_index


def main() -> int:
    """按明确白名单关闭失效的 current 结果，不删除任何原始文件。"""
    parser = argparse.ArgumentParser(description="关闭失效的 current 结果条目")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--result-id", action="append", required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    index = read_result_index(run_dir)
    targets = set(args.result_id)
    changed: list[str] = []
    missing: list[str] = []
    for item in index["results"]:
        if item["result_id"] not in targets:
            continue
        if item["status"] == "current":
            item["status"] = "superseded"
            item["selection_status"] = "candidate"
            changed.append(item["result_id"])
        else:
            missing.append(item["result_id"])
    found = {item["result_id"] for item in index["results"]}
    missing.extend(sorted(targets - found))
    require_result_index(index)
    atomic_json(run_dir / "results" / "index.json", index)
    print(json.dumps({"changed": changed, "already_noncurrent_or_missing": missing}, ensure_ascii=False, indent=2))
    return 0 if not (targets - found) else 1


if __name__ == "__main__":
    raise SystemExit(main())
