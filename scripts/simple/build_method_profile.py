"""在首轮真实实验后写入并验证方法画像。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.method_profile import (
    METHOD_PROFILE_PATH,
    build_method_profile_bindings,
    require_method_profile,
)
from shumozizi.simple.state import utc_now


def main() -> int:
    """从问题方法条目 JSON 构建当前运行的方法画像。"""
    parser = argparse.ArgumentParser(description="在真实实验后生成 method_profile")
    parser.add_argument("run_dir")
    parser.add_argument("questions_file", help="包含 questions 数组或数组本身的 JSON")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    source = load_json(Path(args.questions_file).resolve())
    questions = source.get("questions") if isinstance(source, dict) else source
    if not isinstance(questions, list):
        raise ContractError("questions_file 必须是数组或包含 questions 数组")
    payload = {
        "schema_name": "simple_method_profile",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "bindings": build_method_profile_bindings(run_dir),
        "questions": questions,
        "generated_at": utc_now(),
    }
    atomic_json(run_dir / METHOD_PROFILE_PATH, payload)
    validated = require_method_profile(run_dir)
    print(json.dumps(validated, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
