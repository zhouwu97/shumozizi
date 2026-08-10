"""在现有 MODELING_UNITS 中管理前置风险包与双速实验路由。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.modeling_units import MODELING_UNITS_PATH, write_modeling_units
from shumozizi.simple.results import read_result_index
from shumozizi.simple.risk_routing import (
    default_risk_package,
    validate_risk_assessment,
    validate_risk_package,
)


def _document(run_dir: Path) -> dict[str, Any]:
    """读取当前建模单元文档。

    Args:
        run_dir: 当前运行目录。

    Returns:
        建模单元 JSON 对象。

    Raises:
        ContractError: 建模单元文件不存在或格式不合法。
    """
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        raise ContractError("缺少 analysis/MODELING_UNITS.json，不能登记风险包")
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ContractError("MODELING_UNITS 顶层必须是对象")
    return payload


def _unit(document: dict[str, Any], question_id: str) -> dict[str, Any]:
    """定位一个必答问题的唯一建模单元。

    Args:
        document: 已读取建模单元文档。
        question_id: 目标问题 ID。

    Returns:
        可原地更新的单元对象。

    Raises:
        ContractError: 问题不存在或重复。
    """
    units = [
        item
        for item in document.get("units", [])
        if isinstance(item, dict) and item.get("question_id") == question_id
    ]
    if len(units) != 1:
        raise ContractError(f"MODELING_UNITS 中必须恰有一个 {question_id} 单元")
    return units[0]


def _signals(unit: dict[str, Any]) -> set[str]:
    """提取已有问题差分中的语义风险信号。"""
    delta = unit.get("question_delta")
    raw = delta.get("semantic_risk_signals", []) if isinstance(delta, dict) else []
    return {item for item in raw if isinstance(item, str)}


def _unit_kind(unit: dict[str, Any]) -> str:
    """兼容 v1.4 与旧建模单元的题型字段。"""
    value = unit.get("unit_kind", unit.get("mode", "evaluation"))
    return str(value)


def _input_payload(path: Path) -> dict[str, Any]:
    """读取命令行输入，并允许一层语义字段包装。"""
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ContractError("--input 必须是 JSON 对象")
    return payload


def _risk_package_from_input(payload: dict[str, Any]) -> dict[str, Any]:
    """抽取 ``risk_package`` 包装，兼容直接传入风险包。"""
    wrapped = payload.get("risk_package")
    if wrapped is not None:
        if not isinstance(wrapped, dict):
            raise ContractError("risk_package 必须是对象")
        return wrapped
    return payload


def _risk_assessment_from_input(payload: dict[str, Any]) -> dict[str, Any]:
    """抽取 ``risk_assessment`` 包装，兼容直接传入实际结论。"""
    wrapped = payload.get("risk_assessment")
    if wrapped is not None:
        if not isinstance(wrapped, dict):
            raise ContractError("risk_assessment 必须是对象")
        return wrapped
    return payload


def _validated_package(unit: dict[str, Any]) -> dict[str, Any]:
    """复用生产验证器校验并标准化风险包。"""
    package = validate_risk_package(
        unit.get("risk_package"),
        label=f"{unit.get('unit_id', unit['question_id'])}.risk_package",
        core_question=unit.get("core_question") is True,
        unit_kind=_unit_kind(unit),
        semantic_risk_signals=_signals(unit),
    )
    if package is None:
        raise ContractError("当前问题尚未登记 risk_package")
    return package


def main() -> int:
    """执行风险包生成、实际结果登记或状态读取。

    Returns:
        成功时返回零，合同错误时返回一。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="写入或替换一个问题的 analysis 风险包")
    plan.add_argument("run_dir", type=Path)
    plan.add_argument("--question", required=True)
    source = plan.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="风险包 JSON；可直接传入或使用 risk_package 包装")
    source.add_argument("--auto", action="store_true", help="按题型和 question_delta 生成可编辑模板")

    record = commands.add_parser("record", help="登记风险攻击结果、分流决定和主张边界")
    record.add_argument("run_dir", type=Path)
    record.add_argument("--question", required=True)
    record.add_argument("--input", type=Path, required=True)

    status = commands.add_parser("status", help="读取各问已登记的风险包和实际分流")
    status.add_argument("run_dir", type=Path)

    args = parser.parse_args()
    try:
        document = _document(args.run_dir)
        if args.command == "status":
            report = {
                "run_id": document.get("run_id"),
                "questions": [
                    {
                        "question_id": unit.get("question_id"),
                        "risk_package": unit.get("risk_package"),
                        "risk_assessment": (
                            unit.get("actual", {}).get("risk_assessment")
                            if isinstance(unit.get("actual"), dict)
                            else None
                        ),
                    }
                    for unit in document.get("units", [])
                    if isinstance(unit, dict)
                ],
            }
        else:
            unit = _unit(document, args.question)
            if args.command == "plan":
                package = (
                    default_risk_package(
                        question_id=args.question,
                        core_question=unit.get("core_question") is True,
                        unit_kind=_unit_kind(unit),
                        semantic_risk_signals=_signals(unit),
                    )
                    if args.auto
                    else _risk_package_from_input(_input_payload(args.input))
                )
                unit["risk_package"] = package
                document = write_modeling_units(args.run_dir, document)
                report = {
                    "question_id": args.question,
                    "risk_package": _validated_package(_unit(document, args.question)),
                }
            else:
                assessment = _risk_assessment_from_input(_input_payload(args.input))
                package = _validated_package(unit)
                results = {
                    item["result_id"]
                    : item
                    for item in read_result_index(args.run_dir).get("results", [])
                    if isinstance(item, dict) and isinstance(item.get("result_id"), str)
                }
                # 登记时通常尚未出现 production 结果；正式进入论文前会重新核验
                # 其确实发生在第一次 production 之前。
                boundary = validate_risk_assessment(
                    assessment,
                    package=package,
                    results=results,
                    question_id=args.question,
                    label=f"{unit.get('unit_id', args.question)}.actual.risk_assessment",
                    require_before_first_production=False,
                )
                actual = unit.get("actual")
                if not isinstance(actual, dict):
                    raise ContractError("必须先写入当前问题的 actual 对象，再登记风险攻击结论")
                actual["risk_assessment"] = assessment
                write_modeling_units(args.run_dir, document)
                report = {"question_id": args.question, "claim_boundary": boundary}
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"success": True, "result": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
