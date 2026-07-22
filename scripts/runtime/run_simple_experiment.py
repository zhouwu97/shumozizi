"""Capability-First v3 实验执行器命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.execution import execute_simple_experiment


def _metric(value: str) -> tuple[str, Any]:
    """解析 ``KEY=VALUE`` 形式的命令行指标。

    Args:
        value: 原始指标参数。

    Returns:
        指标键和 JSON 兼容值。

    Raises:
        argparse.ArgumentTypeError: 参数不含键或等号。
    """
    if "=" not in value:
        raise argparse.ArgumentTypeError("指标必须为 KEY=VALUE")
    key, raw = value.split("=", 1)
    if not key.strip():
        raise argparse.ArgumentTypeError("指标名不能为空")
    try:
        return key.strip(), json.loads(raw)
    except json.JSONDecodeError:
        return key.strip(), raw


def main() -> int:
    """执行实验、记录日志和结果索引。

    Returns:
        执行与输出均成功时为零。
    """
    parser = argparse.ArgumentParser(description="执行 Capability-First v3 实验")
    parser.add_argument("run_dir")
    parser.add_argument("--question", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--result-id")
    parser.add_argument("--command", required=True)
    parser.add_argument("--expect", action="append", required=True)
    parser.add_argument("--input", dest="inputs", action="append", default=[])
    parser.add_argument("--metric", type=_metric, action="append", default=[])
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args()
    result_id = args.result_id or f"{args.question.lower()}_{args.kind}"
    try:
        payload = execute_simple_experiment(
            Path(args.run_dir),
            result_id=result_id,
            question_id=args.question,
            kind=args.kind,
            command=args.command,
            expected_outputs=args.expect,
            input_files=args.inputs,
            metrics=dict(args.metric),
            timeout_seconds=args.timeout,
        )
    except (ContractError, OSError) as exc:
        payload = {"success": False, "error": str(exc), "result": None}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
