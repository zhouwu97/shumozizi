"""生成 Typst 论文证据值的命令行薄入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.evidence.validator import generate_paper_evidence


def main() -> int:
    """生成并输出 claim 展示值。"""
    parser = argparse.ArgumentParser(description="从 sealed result 生成 Typst 证据值")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    values = generate_paper_evidence(Path(args.run_dir))
    print(json.dumps(values, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
