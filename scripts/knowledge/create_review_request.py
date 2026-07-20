"""为一张 Paper Card v2 创建只读知识审核请求。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.reviews import create_knowledge_review_request


def main() -> int:
    parser = argparse.ArgumentParser(description="创建 Paper Card v2 知识审核请求")
    parser.add_argument("paper_id")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(create_knowledge_review_request(args.repo_root, args.paper_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
