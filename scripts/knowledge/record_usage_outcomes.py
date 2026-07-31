"""按当前生产结果回填已采用知识模式的兑现状态。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.knowledge.usage import record_knowledge_usage_outcomes


def main() -> int:
    """读取 outcome JSON 并原子更新知识采用记录。"""
    parser = argparse.ArgumentParser(description="回填 adopted knowledge 的实验兑现状态")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    payload = load_json(args.input)
    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, list):
        parser.error("输入 JSON 必须包含 outcomes 数组")
    try:
        path = record_knowledge_usage_outcomes(args.run_dir, outcomes)
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "recorded", "path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
