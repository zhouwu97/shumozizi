"""由当前独立顶层任务领取 Paper Card 知识审核请求。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.reviews import claim_knowledge_review_request


def main() -> int:
    parser = argparse.ArgumentParser(description="领取 Paper Card v2 知识审核请求")
    parser.add_argument("request", type=Path)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--reviewer-identity", required=True)
    args = parser.parse_args()
    print(
        claim_knowledge_review_request(
            args.request,
            thread_id=args.thread_id,
            reviewer_identity=args.reviewer_identity,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
