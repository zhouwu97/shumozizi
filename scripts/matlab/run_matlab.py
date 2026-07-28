"""命令行运行并登记 Competition-First MATLAB 分析。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shumozizi.core.io import load_json  # noqa: E402
from shumozizi.simple.matlab import run_matlab_analysis  # noqa: E402


def main() -> None:
    """从 JSON 配置读取路径与结果合同并执行 MATLAB。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = load_json(args.config)
    manifest = run_matlab_analysis(args.run_dir, **config)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

