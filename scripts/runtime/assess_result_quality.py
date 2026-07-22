"""将实验输出中的机器生成质量结论写入独立质量层。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.quality import assess_result_quality


def main() -> int:
    """读取评估 JSON，派生 paper_allowed 并写入 quality.json。"""
    parser = argparse.ArgumentParser(description="评估 v3 搜索结果质量")
    parser.add_argument("run_dir")
    parser.add_argument("--result-id", required=True)
    parser.add_argument("--assessment", required=True)
    args = parser.parse_args()
    try:
        document = load_json(Path(args.assessment))
        assessment = document.get("quality_assessment", document)
        payload = assess_result_quality(
            Path(args.run_dir), result_id=args.result_id, assessment=assessment
        )
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        payload = {"success": False, "error": str(exc)}
    else:
        payload["success"] = True
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
