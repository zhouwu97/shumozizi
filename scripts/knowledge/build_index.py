"""从 Markdown 论文卡构建简单索引。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.papers import build_paper_indexes


def main() -> int:
    parser = argparse.ArgumentParser(description="构建隔离的 provisional 与 verified 论文索引")
    parser.add_argument("--cards-dir", type=Path, default=Path("knowledge/cards/papers"))
    parser.add_argument(
        "--review-registry",
        type=Path,
        default=Path("knowledge/reviews/paper_card_review_registry.json"),
    )
    parser.add_argument(
        "--provisional-output",
        type=Path,
        default=Path("knowledge/indexes/papers_provisional.json"),
    )
    parser.add_argument(
        "--verified-output",
        type=Path,
        default=Path("knowledge/indexes/papers_verified.json"),
    )
    args = parser.parse_args()
    documents = build_paper_indexes(
        args.cards_dir,
        args.review_registry,
        args.provisional_output,
        args.verified_output,
    )
    print(f"provisional: {documents['provisional']['paper_count']} 篇")
    print(f"verified: {documents['verified']['paper_count']} 篇")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
