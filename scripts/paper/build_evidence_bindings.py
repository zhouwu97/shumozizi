"""生成或校验正式论文的方法学和不确定性证据绑定。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import atomic_json, load_json  # noqa: E402
from shumozizi.paper.evidence_contracts import (  # noqa: E402
    PUBLICATION_EVIDENCE_BINDINGS_PATH,
    evidence_binding_template,
    publication_evidence_binding_errors,
    write_publication_evidence_bindings,
)


def main() -> int:
    """输出模板、写入人工完成的绑定，或只执行校验。"""
    parser = argparse.ArgumentParser(
        description="把方法学和不确定性生产结果绑定到正式论文源码"
    )
    parser.add_argument("run_dir", type=Path)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--write-template",
        action="store_true",
        help="写入待填写的 paper/EVIDENCE_BINDINGS.json 模板",
    )
    actions.add_argument(
        "--validate",
        action="store_true",
        help="校验现有绑定，不改文件",
    )
    actions.add_argument(
        "--from-json",
        type=Path,
        help="读取已完成 JSON，校验后原子写入正式绑定",
    )
    args = parser.parse_args()
    root = args.run_dir.resolve()
    if args.write_template:
        payload = evidence_binding_template(root)
        atomic_json(root / PUBLICATION_EVIDENCE_BINDINGS_PATH, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.from_json is not None:
        payload = load_json(args.from_json)
        write_publication_evidence_bindings(root, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    errors = publication_evidence_binding_errors(root)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
