"""指标 provenance 物化命令行薄入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import load_json
from shumozizi.results.metrics import materialize_metric


def main() -> int:
    """从定义文件生成不可变指标来源。"""
    parser = argparse.ArgumentParser(description="从已哈希执行输出提取指标")
    parser.add_argument("run_dir")
    parser.add_argument("definition")
    args = parser.parse_args()
    provenance = materialize_metric(Path(args.run_dir), load_json(Path(args.definition)))
    print(json.dumps(provenance, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
