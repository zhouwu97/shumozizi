"""生成 v3.4 Writer Handoff Package 的命令行入口。

材料不充分时输出 blocked 与具体原因（退出码 1），充分时输出
``WRITER_HANDOFF_READY`` 并把 authoring_status 置为 ``waiting_external_author``。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.paper.handoff import (  # noqa: E402
    build_writer_handoff,
    mark_waiting_external_author,
    writer_handoff_readiness,
)


def main() -> int:
    """构建交接包，并在成功后进入等待外部 Author 状态。"""
    parser = argparse.ArgumentParser(description="准备 v3.4 External Author Handoff")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        readiness = writer_handoff_readiness(args.run_dir)
        if not readiness["ready"]:
            print(
                json.dumps(
                    {"status": "blocked", "reasons": readiness["reasons"]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        receipt = build_writer_handoff(args.run_dir)
        mark_waiting_external_author(args.run_dir)
        print(
            json.dumps(
                {
                    "status": "WRITER_HANDOFF_READY",
                    "authoring_status": "waiting_external_author",
                    **receipt,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
