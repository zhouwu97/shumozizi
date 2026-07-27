"""管理 Competition-First 科学挑战的一次专项追问。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    json_bytes,
    load_json,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import (
    is_competition_first_v32_state,
    read_simple_state,
    utc_now,
)

FOCUSED_FOLLOWUP_PATH = Path("review/FOCUSED_FOLLOWUP.md")
SCIENTIFIC_CHALLENGE_EVIDENCE_PATH = Path("review/scientific-challenge-evidence.json")
STRONGER_ALTERNATIVE_PATH = Path("review/stronger-alternative.json")
_ALTERNATIVE_RESOLUTIONS = frozenset({"attempted", "infeasible_in_schedule"})
_FINDING_ACTIONS = frozenset(
    {
        "WRITING_FIX",
        "MODEL_REPAIR",
        "OBJECTIVE_REDESIGN",
        "DATA_LIMITATION",
        "ANSWER_REJECTION",
    }
)
_BLOCKING_FINDING_ACTIONS = frozenset(
    {"MODEL_REPAIR", "OBJECTIVE_REDESIGN", "ANSWER_REJECTION"}
)
_FINDING_STATUSES = frozenset({"open", "closed"})


def _normalize_scientific_findings(
    run_dir: Path,
    findings: object,
    current_results: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """验证科学挑战发现的动作、回退阶段和关闭证据。"""
    if not isinstance(findings, list):
        raise ContractError("科学挑战 findings 必须是数组")
    question_ids = set(read_simple_state(run_dir)["required_questions"])
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    rollback_by_action: dict[str, set[str]] = {
        "WRITING_FIX": {"paper"},
        "MODEL_REPAIR": {"experiment"},
        "OBJECTIVE_REDESIGN": {"analysis"},
        "DATA_LIMITATION": {"paper"},
        "ANSWER_REJECTION": {"analysis", "experiment"},
    }
    for index, raw in enumerate(findings):
        if not isinstance(raw, dict):
            raise ContractError(f"scientific findings[{index}] 必须是对象")
        item = dict(raw)
        finding_id = item.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id.strip() or finding_id in seen:
            raise ContractError("scientific finding_id 必须是唯一非空文本")
        seen.add(finding_id)
        question_id = item.get("question_id")
        if question_id not in question_ids:
            raise ContractError(f"{finding_id}.question_id 不是必答问题")
        if item.get("severity") not in {"P0", "P1", "P2", "P3"}:
            raise ContractError(f"{finding_id}.severity 必须为 P0-P3")
        if not isinstance(item.get("finding"), str) or not item["finding"].strip():
            raise ContractError(f"{finding_id}.finding 必须是非空文本")
        action = item.get("action_type")
        if action not in _FINDING_ACTIONS:
            raise ContractError(f"{finding_id}.action_type 不受支持")
        rollback = item.get("rollback_target")
        if rollback not in rollback_by_action[action]:
            raise ContractError(
                f"{finding_id}.{action} 必须回退到 "
                + "/".join(sorted(rollback_by_action[action]))
            )
        invalidates = item.get("invalidates")
        if (
            not isinstance(invalidates, list)
            or not invalidates
            or not all(isinstance(value, str) and value.strip() for value in invalidates)
        ):
            raise ContractError(f"{finding_id}.invalidates 必须是非空文本数组")
        if not isinstance(item.get("required_action"), str) or not item["required_action"].strip():
            raise ContractError(f"{finding_id}.required_action 必须是非空文本")
        status = item.get("status")
        if status not in _FINDING_STATUSES:
            raise ContractError(f"{finding_id}.status 必须为 open 或 closed")
        closure_ids = item.get("closure_evidence_result_ids")
        if not isinstance(closure_ids, list) or not all(
            isinstance(value, str) and value.strip() for value in closure_ids
        ):
            raise ContractError(f"{finding_id}.closure_evidence_result_ids 必须是文本数组")
        missing = [value for value in closure_ids if value not in current_results]
        if missing:
            raise ContractError(
                f"{finding_id} 绑定了非 current production 关闭证据: "
                + ", ".join(missing)
            )
        if status == "closed" and action in _BLOCKING_FINDING_ACTIONS and not closure_ids:
            raise ContractError(f"{finding_id} 不能没有真实结果证据就关闭 {action}")
        if action == "DATA_LIMITATION" and (
            not isinstance(item.get("why_not_repairable"), str)
            or not item["why_not_repairable"].strip()
        ):
            raise ContractError(
                f"{finding_id}.DATA_LIMITATION 必须说明为何无法通过模型或实验修复"
            )
        normalized.append(item)
    return normalized


def record_stronger_alternative(
    run_dir: Path,
    *,
    found: bool,
    description: str | None = None,
    resolution: str | None = None,
    result_ids: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """登记科学挑战是否发现更强路线或目标定义，以及后续处置。

    只有 P0/P1 阻断时，"存在明显更强的路线"这类判断写进报告即可继续前进，
    等于让挑战发现了上限却不必去拿。这里要求二选一：真的跑一次，或写明为何
    在赛程内不可行。

    Args:
        run_dir: 当前运行目录。
        found: 是否发现更强路线或目标定义。
        description: 更强方案的具体描述。
        resolution: ``attempted`` 或 ``infeasible_in_schedule``。
        result_ids: ``attempted`` 时必须绑定的真实生产结果。
        reason: ``infeasible_in_schedule`` 时的具体理由。

    Returns:
        已写入的处置记录。

    Raises:
        ContractError: 声明发现更强方案却没有实际尝试也没有说明不可行。
    """
    if not found:
        # 绑定记录时的生产结果集合：若后续实验新增了生产结果，说明挑战可能
        # 尚未覆盖新的路线，"无更强路线"判断需重新记录。
        try:
            prod_result_ids = sorted(
                item["result_id"]
                for item in read_result_index(run_dir)["results"]
                if item.get("execution_mode") == "production"
                and item.get("execution_valid") is True
            )
        except (KeyError, TypeError, ValueError, OSError):
            prod_result_ids = []
        payload = {
            "schema_version": "1.1",
            "run_id": run_dir.name,
            "stronger_alternative_found": False,
            "production_result_ids_at_recording": prod_result_ids,
            "recorded_at": utc_now(),
        }
        atomic_json(run_dir / STRONGER_ALTERNATIVE_PATH, payload)
        return payload
    if not (description or "").strip():
        raise ContractError("发现更强路线时必须写明它是什么")
    if resolution not in _ALTERNATIVE_RESOLUTIONS:
        raise ContractError(
            "更强路线的处置必须是 attempted 或 infeasible_in_schedule"
        )
    identifiers = list(dict.fromkeys(result_ids or []))
    if resolution == "attempted":
        if not identifiers:
            raise ContractError("声明已尝试更强路线时必须绑定真实生产结果")
        available = {
            item["result_id"]
            for item in read_result_index(run_dir)["results"]
            if item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
        }
        missing = sorted(set(identifiers) - available)
        if missing:
            raise ContractError(
                "更强路线尝试绑定了未真实执行的结果: " + ", ".join(missing)
            )
    elif not (reason or "").strip():
        raise ContractError("声明赛程内无法尝试更强路线时必须写明具体理由")
    payload = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "stronger_alternative_found": True,
        "description": description.strip(),
        "resolution": resolution,
        "result_ids": identifiers,
        "reason": (reason or "").strip(),
        "recorded_at": utc_now(),
    }
    atomic_json(run_dir / STRONGER_ALTERNATIVE_PATH, payload)
    return payload


def stronger_alternative_status(run_dir: Path) -> dict[str, Any]:
    """返回更强路线判断是否已闭合，可作为论文放行条件之一。"""
    path = run_dir / STRONGER_ALTERNATIVE_PATH
    if not path.is_file():
        return {
            "allowed": False,
            "reason": "科学挑战未记录是否存在更强路线或目标定义",
        }
    try:
        payload = load_json(path)
        if payload.get("run_id") != run_dir.name:
            raise ContractError("更强路线记录 run_id 不匹配")
        if payload.get("stronger_alternative_found") is not True:
            # 检查"无更强路线"记录是否因后续实验新增了生产结果而过时。
            # schema_version 1.0 不含 production_result_ids_at_recording，不触发失效检查
            # （向后兼容旧记录）。
            recorded_ids = set(payload.get("production_result_ids_at_recording") or [])
            if recorded_ids:
                try:
                    current_ids = {
                        item["result_id"]
                        for item in read_result_index(run_dir)["results"]
                        if item.get("execution_mode") == "production"
                        and item.get("execution_valid") is True
                    }
                    new_results = sorted(current_ids - recorded_ids)
                    if new_results:
                        return {
                            "allowed": False,
                            "reason": (
                                "实验新增了生产结果，科学挑战时的'无更强路线'判断需重新记录: "
                                + ", ".join(new_results)
                            ),
                        }
                except (KeyError, TypeError, ValueError, OSError):
                    pass  # 无法读取结果索引时不阻断（保守策略）
            return {"allowed": True, "reason": "", "record": payload}
        resolution = payload.get("resolution")
        if resolution not in _ALTERNATIVE_RESOLUTIONS:
            raise ContractError("更强路线记录缺少合法处置")
        if resolution == "attempted":
            results = {
                item["result_id"]
                for item in read_result_index(run_dir)["results"]
                if item.get("execution_mode") == "production"
                and item.get("execution_valid") is True
            }
            missing = sorted(set(payload.get("result_ids", [])) - results)
            if missing:
                raise ContractError(
                    "更强路线尝试引用的结果已失效: " + ", ".join(missing)
                )
        return {"allowed": True, "reason": "", "record": payload}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc)}


def write_focused_followup(run_dir: Path, content: str) -> Path:
    """创建唯一允许的专项追问记录。

    Args:
        run_dir: 当前运行目录。
        content: 包含待验证问题、证据和结论的 Markdown 内容。

    Returns:
        已写入的追问路径。

    Raises:
        ContractError: 已经存在追问或内容过短。
    """
    path = run_dir / FOCUSED_FOLLOWUP_PATH
    if path.exists():
        raise ContractError("每轮科学审核最多允许一个 FOCUSED_FOLLOWUP.md")
    if len(content.strip()) < 32:
        raise ContractError("专项追问必须说明决定性缺口及其验证结论")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
    return path


def record_scientific_challenge_evidence(
    run_dir: Path,
    *,
    result_ids: list[str],
    attack_description: str,
    comparison_result_ids: list[str] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """绑定科学挑战的当前结论与保留对照执行结果。

    Args:
        run_dir: 当前运行目录。
        result_ids: 支撑当前结论的 current production 结果。
        attack_description: 该攻击试图推翻的具体结论。
        comparison_result_ids: 用于反例或路线取舍的生产级对照结果；允许已经
            被当前候选替换，但其输出仍须保持登记时的内容。

    Returns:
        已写入的轻量挑战证据收据。

    Raises:
        ContractError: 结果不存在、已失效或描述为空。
    """
    if not attack_description.strip():
        raise ContractError("科学挑战必须说明实际攻击要推翻的具体结论")
    if not result_ids:
        raise ContractError("科学挑战必须绑定至少一个真实执行结果")
    comparison_ids = list(dict.fromkeys(comparison_result_ids or []))
    if set(result_ids) & set(comparison_ids):
        raise ContractError("科学挑战结果不能同时作为当前结论和对照证据")
    current_results = {
        item["result_id"]: item
        for item in read_result_index(run_dir)["results"]
        if item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
    }
    missing = [result_id for result_id in result_ids if result_id not in current_results]
    if missing:
        raise ContractError("科学挑战绑定了非 current production 结果: " + ", ".join(missing))

    # 对照结果用于保留已验证的反例或目标取舍，不能因为 winner 更新被静默抹去。
    # 但 failed/diagnostic 或探索性结果从不具备挑战证据资格。
    comparison_results = {
        item["result_id"]: item
        for item in read_result_index(run_dir)["results"]
        if item.get("status") in {"current", "superseded"}
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
    }
    comparison_missing = [
        result_id for result_id in comparison_ids if result_id not in comparison_results
    ]
    if comparison_missing:
        raise ContractError(
            "科学挑战绑定了无效的生产级对照结果: " + ", ".join(comparison_missing)
        )

    records = [
        {
            "result_id": result_id,
            "sha256": sha256_bytes(json_bytes(current_results[result_id])),
            "evidence_role": "current",
            "output_hashes": current_results[result_id]["output_hashes"],
        }
        for result_id in dict.fromkeys(result_ids)
    ]
    records.extend(
        {
            "result_id": result_id,
            "sha256": sha256_bytes(json_bytes(comparison_results[result_id])),
            "evidence_role": "comparison",
            "output_hashes": comparison_results[result_id]["output_hashes"],
        }
        for result_id in comparison_ids
    )
    is_v32 = is_competition_first_v32_state(read_simple_state(run_dir))
    normalized_findings = _normalize_scientific_findings(
        run_dir, findings or [], current_results
    ) if is_v32 or findings is not None else None
    payload = {
        "schema_version": (
            "1.3" if normalized_findings is not None else "1.2" if comparison_ids else "1.0"
        ),
        "run_id": run_dir.name,
        "attack_description": attack_description.strip(),
        "results": records,
        "recorded_at": utc_now(),
    }
    if normalized_findings is not None:
        payload["findings"] = normalized_findings
    atomic_json(run_dir / SCIENTIFIC_CHALLENGE_EVIDENCE_PATH, payload)
    return payload


def verify_scientific_challenge_evidence(run_dir: Path) -> dict[str, Any]:
    """确认科学挑战仍绑定未漂移的真实执行结果。

    Args:
        run_dir: 当前运行目录。

    Returns:
        有效性和错误列表。
    """
    path = run_dir / SCIENTIFIC_CHALLENGE_EVIDENCE_PATH
    if not path.is_file():
        return {"valid": False, "errors": ["缺少 review/scientific-challenge-evidence.json"]}
    try:
        payload = load_json(path)
        if payload.get("run_id") != run_dir.name or not payload.get("attack_description"):
            raise ContractError("科学挑战证据 run_id 或攻击描述无效")
        schema_version = payload.get("schema_version", "1.0")
        if schema_version not in {"1.0", "1.1", "1.2", "1.3"}:
            raise ContractError("科学挑战证据 schema_version 不受支持")
        results = {
            item["result_id"]: item
            for item in read_result_index(run_dir)["results"]
            if item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
        }
        errors = []
        for item in payload.get("results", []):
            result_id = item.get("result_id") if isinstance(item, dict) else None
            result = results.get(result_id)
            evidence_role = item.get("evidence_role", "current") if isinstance(item, dict) else None
            allowed_statuses = (
                {"current", "superseded"}
                if schema_version in {"1.2", "1.3"} and evidence_role == "comparison"
                else {"current"}
            )
            if (
                evidence_role not in {"current", "comparison"}
                or (evidence_role == "comparison" and schema_version not in {"1.2", "1.3"})
                or result is None
                or result.get("status") not in allowed_statuses
                or not isinstance(item, dict)
            ):
                errors.append(f"科学挑战结果已失效或漂移: {result_id}")
                continue
            record_sha256 = sha256_bytes(json_bytes(result))
            recorded_output_hashes = item.get("output_hashes")
            if recorded_output_hashes is not None:
                # v1.2 同时冻结登记记录和所有输出，避免保留对照只校验元数据。
                if (
                    item.get("sha256") != record_sha256
                    or recorded_output_hashes != result.get("output_hashes")
                    or not isinstance(recorded_output_hashes, dict)
                ):
                    errors.append(f"科学挑战结果已失效或漂移: {result_id}")
                    continue
                try:
                    for output_file, output_sha256 in recorded_output_hashes.items():
                        output_path = resolve_inside(run_dir, output_file, must_exist=True)
                        if sha256_file(output_path) != output_sha256:
                            raise ContractError("科学挑战输出文件哈希不匹配")
                except (ContractError, OSError, KeyError, TypeError, ValueError):
                    errors.append(f"科学挑战结果已失效或漂移: {result_id}")
                continue
            if item.get("sha256") == record_sha256:
                continue
            # v1.1 曾以结果原始输出文件作为挑战证据。仍须同时核验登记的
            # output_hashes 和磁盘实际文件，不能仅凭路径或报告文字放行。
            output_file = item.get("file")
            output_hashes = result.get("output_hashes")
            if (
                not isinstance(output_file, str)
                or output_file not in result.get("output_files", [])
                or not isinstance(output_hashes, dict)
                or output_hashes.get(output_file) != item.get("sha256")
            ):
                errors.append(f"科学挑战结果已失效或漂移: {result_id}")
                continue
            try:
                output_path = resolve_inside(run_dir, output_file, must_exist=True)
                if sha256_file(output_path) != item["sha256"]:
                    errors.append(f"科学挑战结果已失效或漂移: {result_id}")
            except (ContractError, OSError, KeyError, TypeError, ValueError):
                errors.append(f"科学挑战结果已失效或漂移: {result_id}")
        if not payload.get("results"):
            errors.append("科学挑战没有绑定任何执行结果")
        blocking_findings: list[dict[str, Any]] = []
        if schema_version == "1.3":
            try:
                normalized = _normalize_scientific_findings(
                    run_dir, payload.get("findings"), {
                        key: value
                        for key, value in results.items()
                        if value.get("status") == "current"
                    }
                )
                blocking_findings = [
                    item for item in normalized
                    if item["status"] == "open"
                    and item["action_type"] in _BLOCKING_FINDING_ACTIONS
                ]
            except ContractError as exc:
                errors.append(str(exc))
        return {
            "valid": not errors,
            "errors": errors,
            "evidence": payload,
            "blocking_findings": blocking_findings,
        }
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"valid": False, "errors": [str(exc)]}
