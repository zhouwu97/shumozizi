"""算法模板实例化命令行薄入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.runtime.templates import instantiate_template


def main() -> int:
    """实例化模板并输出目标目录。"""
    parser = argparse.ArgumentParser(description="实例化受控算法模板")
    parser.add_argument("run_dir")
    parser.add_argument("template_id")
    parser.add_argument("question_id")
    parser.add_argument("instance_id")
    parser.add_argument("--parameters", default="{}", help="JSON 对象")
    args = parser.parse_args()
    root = resolve_repo_root()
    destination = instantiate_template(
        root,
        Path(args.run_dir),
        args.template_id,
        args.question_id,
        args.instance_id,
        json.loads(args.parameters),
    )
    print(json.dumps({"instance_dir": str(destination)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
