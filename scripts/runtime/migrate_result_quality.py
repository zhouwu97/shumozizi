"""把旧 v3 执行索引中的质量字段迁移到独立质量层。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.quality import migrate_legacy_result_quality


def main() -> int:
    """执行一次幂等迁移并打印迁移结果。"""
    parser = argparse.ArgumentParser(description="迁移 v3 结果质量层")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    try:
        payload = migrate_legacy_result_quality(Path(args.run_dir))
    except (ContractError, OSError, ValueError) as exc:
        payload = {"success": False, "error": str(exc)}
    else:
        payload["success"] = True
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
