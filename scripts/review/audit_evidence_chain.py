"""输出论文图/方法名与 production 结果的证据链一致性审计。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.evidence_chain_audit import (  # noqa: E402
    audit_evidence_chain,
)


def main() -> int:
    """解析运行目录并打印证据链审计结果。"""
    parser = argparse.ArgumentParser(
        description="检查论文图/方法名是否绑定 production 结果"
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = audit_evidence_chain(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
