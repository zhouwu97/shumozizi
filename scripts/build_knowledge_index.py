"""校验外部来源与知识卡并重建知识索引。"""

from __future__ import annotations

import json

from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.knowledge.selector import build_knowledge_index


def main() -> int:
    """重建知识索引并输出卡片数量。"""
    root = resolve_repo_root()
    index = build_knowledge_index(root)
    print(json.dumps({"card_count": len(index["cards"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
