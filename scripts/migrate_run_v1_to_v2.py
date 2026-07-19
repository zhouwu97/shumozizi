"""v1 到 v2 事务式迁移命令行薄入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.core.io import ContractError
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.migrations.v1_to_v2 import migrate_run


def main() -> int:
    """迁移一个允许升级的 v1 运行。"""
    parser = argparse.ArgumentParser(description="事务式迁移 shumozizi v1 运行")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    try:
        payload = migrate_run(resolve_repo_root(), Path(args.run_dir))
    except (ContractError, OSError, KeyError) as exc:
        payload = {"migrated": False, "errors": [str(exc)]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("migrated") else 1


if __name__ == "__main__":
    raise SystemExit(main())
