"""输出启动全新顶层 PDF 盲审任务所需的固定提示词。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.review import (
    paper_blind_review_prompt,
    paper_blind_review_prompt_sha256,
)


def main() -> int:
    """读取冻结包并输出可直接交给新任务的提示词。"""
    parser = argparse.ArgumentParser(description="输出 Competition-First v3.1 PDF 盲审提示词")
    parser.add_argument("run_dir")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--json", action="store_true", help="同时输出提示词哈希")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    try:
        prompt = paper_blind_review_prompt(run_dir, args.manifest)
        if args.json:
            print(
                json.dumps(
                    {
                        "prompt": prompt,
                        "prompt_sha256": paper_blind_review_prompt_sha256(
                            run_dir, args.manifest
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(prompt)
        return 0
    except (ContractError, OSError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
