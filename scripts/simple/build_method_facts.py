"""从当前真实生产结果生成 Competition-First 方法事实。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.simple.method_facts import method_fact_advice, write_method_facts


def main() -> int:
    """生成方法事实及其非阻断验证建议。"""
    parser = argparse.ArgumentParser(description="生成 Competition-First method_facts")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    payload = write_method_facts(run_dir)
    print(json.dumps({"facts": payload, "advice": method_fact_advice(run_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
