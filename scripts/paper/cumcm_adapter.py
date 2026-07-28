"""生成和复验轻量 CUMCM 论文结构适配产物。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.paper.cumcm_adapter import (
    LAYOUT_AUDIT_PATH,
    STRUCTURE_MAP_PATH,
    cumcm_adapter_required,
    finalize_cumcm_layout_audit,
    require_cumcm_layout_audit,
    require_cumcm_paper_review_audit,
    require_cumcm_structure_map,
    write_cumcm_paper_review_audit,
    write_cumcm_structure_map,
)


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    """读取写入命令的 JSON 输入。"""
    if args.input is None:
        raise ContractError(f"{args.command} 命令必须提供 --input JSON")
    payload = load_json(args.input)
    if not isinstance(payload, dict):
        raise ContractError("--input 必须是 JSON 对象")
    return payload


def _status(run_dir: Path) -> dict[str, Any]:
    """返回两个适配产物的当前复验状态，不写入新文件。"""
    result: dict[str, Any] = {
        "required": cumcm_adapter_required(run_dir),
        "structure_map": {"path": STRUCTURE_MAP_PATH.as_posix(), "valid": False},
        "paper_review": {"path": LAYOUT_AUDIT_PATH.as_posix(), "valid": False},
        "layout": {"path": LAYOUT_AUDIT_PATH.as_posix(), "valid": False},
    }
    if not result["required"]:
        result["structure_map"]["valid"] = True
        result["paper_review"]["valid"] = True
        result["layout"]["valid"] = True
        return result
    for key, validator in (
        ("structure_map", require_cumcm_structure_map),
        ("paper_review", require_cumcm_paper_review_audit),
        ("layout", require_cumcm_layout_audit),
    ):
        try:
            validator(run_dir)
            result[key]["valid"] = True
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            result[key]["reason"] = str(exc)
    return result


def main() -> int:
    """执行结构映射、论文评审、版面闭环或只读状态检查。"""
    parser = argparse.ArgumentParser(description="CUMCM 论文轻量结构适配器")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "command",
        choices=("structure-map", "paper-review", "finalize", "status"),
    )
    parser.add_argument("--input", type=Path, help="待校验并写入的 JSON 对象")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        if args.command == "structure-map":
            output: Any = write_cumcm_structure_map(run_dir, _payload(args))
        elif args.command == "paper-review":
            output = write_cumcm_paper_review_audit(run_dir, _payload(args))
        elif args.command == "finalize":
            output = finalize_cumcm_layout_audit(run_dir, _payload(args))
        else:
            output = _status(run_dir)
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    if isinstance(output, Path):
        print(output)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
