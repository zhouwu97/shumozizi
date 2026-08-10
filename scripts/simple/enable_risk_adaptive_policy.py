"""为尚未正式求解的 v3.2 运行启用风险自适应执行策略。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.simple.state import enable_risk_adaptive_execution_policy


def main() -> int:
    """解析运行目录并执行安全迁移。"""
    parser = argparse.ArgumentParser(description="启用 v3.2 风险自适应执行策略")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    state = enable_risk_adaptive_execution_policy(Path(args.run_dir).resolve())
    print(
        json.dumps(
            {
                "run_id": state["run_id"],
                "execution_mode": state["execution_mode"],
                "execution_policy": state["execution_policy"],
                "revision": state["revision"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
