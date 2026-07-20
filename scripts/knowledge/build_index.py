"""从 Markdown 论文卡构建简单索引。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.papers import build_paper_index


def main() -> int:
    parser = argparse.ArgumentParser(description="构建仓内优秀论文索引")
    parser.add_argument("--cards-dir", type=Path, default=Path("knowledge/cards/papers"))
    parser.add_argument("--output", type=Path, default=Path("knowledge/indexes/papers.json"))
    args = parser.parse_args()
    document = build_paper_index(args.cards_dir, args.output)
    print(f"已索引 {document['paper_count']} 篇论文: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
