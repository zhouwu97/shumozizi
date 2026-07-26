"""在全面审核报告冻结后登记其需额外证明的强断言。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)


def main() -> int:
    """绑定当前报告和独立提取的强断言列表。"""
    parser = argparse.ArgumentParser(description="登记全面审核后的强断言")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--scope", choices=("scientific", "paper"), required=True)
    parser.add_argument("--review-file", required=True)
    parser.add_argument(
        "--claims",
        required=True,
        help="后置提取的 JSON 文件，顶层必须为 claim 数组；不得在首轮审核输入中预置。",
    )
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    report = resolve_inside(run_dir, args.review_file, must_exist=True)
    claims = load_json(Path(args.claims).resolve())
    if not isinstance(claims, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("claim_id"), str)
        or not isinstance(item.get("claim_type"), str)
        or not isinstance(item.get("statement"), str)
        for item in claims
    ):
        raise ContractError("强断言提取必须是含 claim_id、claim_type、statement 的对象数组")
    target = run_dir / "review" / "strong_claims" / f"{args.scope}.json"
    payload = {
            "schema_name": "review_strong_claims",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "scope": args.scope,
            "review_file": relative_inside(run_dir, report).as_posix(),
            "review_sha256": sha256_file(report),
            "claims": claims,
    }
    if args.scope == "paper":
        pdf = resolve_inside(run_dir, "paper/final.pdf", must_exist=True)
        payload["paper_pdf_file"] = "paper/final.pdf"
        payload["paper_pdf_sha256"] = sha256_file(pdf)
    atomic_json(target, payload)
    print(json.dumps({"strong_claims_file": relative_inside(run_dir, target).as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
