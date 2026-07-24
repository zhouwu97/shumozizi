"""为已完成的独立审核任务创建可复验回执。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.core.io import load_json
from shumozizi.simple.review_tasks import create_review_task_receipt


def main() -> int:
    """解析任务元数据并写入 review/tasks/<task_id>/receipt.json。"""
    parser = argparse.ArgumentParser(description="创建独立审核任务回执")
    parser.add_argument("run_dir")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--prompt-sha256", required=True)
    parser.add_argument("--input-bindings", required=True, help="输入绑定 JSON 文件")
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--parent-task-id")
    args = parser.parse_args()
    path = create_review_task_receipt(
        Path(args.run_dir).resolve(),
        task_id=args.task_id,
        task_type=args.task_type,
        thread_id=args.thread_id,
        model_id=args.model_id,
        prompt_sha256=args.prompt_sha256,
        input_bindings=load_json(Path(args.input_bindings).resolve()),
        report_file=args.report_file,
        parent_task_id=args.parent_task_id,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
