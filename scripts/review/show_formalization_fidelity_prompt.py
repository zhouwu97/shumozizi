"""输出冷启动目标忠实度审查提示（正式路线比较前执行）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.paper.formalization_fidelity import formalization_fidelity_prompt  # noqa: E402


def main() -> int:
    """解析运行目录并输出冷启动目标忠实度审查提示。"""
    parser = argparse.ArgumentParser(
        description="生成冷启动目标忠实度审查提示（路线比较前）"
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        prompt = formalization_fidelity_prompt(args.run_dir)
    except (ContractError, OSError, ValueError) as exc:
        print(f"invalid: {exc}")
        return 1
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
