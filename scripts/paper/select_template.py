"""选择并可选实例化 Capability-First v3 论文模板。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.templates import materialize_selected_template, select_paper_template


def main() -> int:
    """选择匹配模板；只有显式选项才复制到论文目录。"""
    parser = argparse.ArgumentParser(description="选择 v3 数学建模论文模板")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--language", choices=("zh", "en"), required=True)
    parser.add_argument(
        "--engine",
        choices=("auto", "typst", "latex"),
        default="auto",
        help="默认优先 LaTeX；仅在 LaTeX 不可用时受控回退 Typst。",
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument("--materialize", action="store_true")
    args = parser.parse_args()
    payload = select_paper_template(
        args.run_dir,
        language=args.language,
        engine=args.engine,
        selection_reason=args.reason,
    )
    if args.materialize:
        payload = materialize_selected_template(args.run_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
