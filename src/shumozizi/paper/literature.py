"""管理论文文献检索计划、候选来源和检索审计。

本模块只处理用户已经获得或人工录入的来源元数据，不实现登录、凭据存储或
站点抓取。这样可以把检索可追溯性补进论文流程，同时不把机构认证状态带入
运行目录或提交包。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import utc_now

PLAN_PATH = Path("paper/generated/literature-search-plan.json")
REPORT_PATH = Path("paper/generated/literature-search-report.json")
_SECRET_KEY = re.compile(r"password|passwd|cookie|token|secret|credential|session", re.IGNORECASE)
_SAFE_POLICY_KEYS = {
    "persist_credentials",
    "persist_cookies_in_repo",
    "session_policy",
    "reuse_authenticated_session",
}
_CATEGORIES = ("background", "core_method", "validation", "uncertainty", "extension")


def _path_inside_run(run_dir: Path, relative: Path) -> Path:
    """解析固定运行目录内的输出路径。"""
    root = run_dir.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"文献检索文件必须位于运行目录内: {relative}") from exc
    return candidate


def _assert_no_secret_keys(value: object, *, path: str = "<root>") -> None:
    """拒绝意外写入凭据字段，避免审计账本成为秘密载体。"""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if _SECRET_KEY.search(key_text) and key_text not in _SAFE_POLICY_KEYS:
                raise ContractError(f"文献检索记录禁止出现凭据字段: {path}.{key_text}")
            _assert_no_secret_keys(child, path=f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_keys(child, path=f"{path}[{index}]")


def _write_plan(run_dir: Path, plan: dict[str, Any]) -> Path:
    """校验并原子写入检索计划。"""
    _assert_no_secret_keys(plan)
    require_valid(plan, "literature_search_plan")
    path = _path_inside_run(run_dir, PLAN_PATH)
    atomic_json(path, plan)
    return path


def _write_report(run_dir: Path, report: dict[str, Any]) -> Path:
    """校验并原子写入候选来源报告。"""
    _assert_no_secret_keys(report)
    require_valid(report, "literature_search_report")
    path = _path_inside_run(run_dir, REPORT_PATH)
    atomic_json(path, report)
    return path


def _load_plan(run_dir: Path) -> tuple[dict[str, Any], Path]:
    """读取并校验检索计划。"""
    path = _path_inside_run(run_dir, PLAN_PATH)
    plan = load_json(path)
    _assert_no_secret_keys(plan)
    require_valid(plan, "literature_search_plan")
    return plan, path


def _load_report(run_dir: Path) -> tuple[dict[str, Any], Path]:
    """读取并校验候选来源报告。"""
    path = _path_inside_run(run_dir, REPORT_PATH)
    report = load_json(path)
    _assert_no_secret_keys(report)
    require_valid(report, "literature_search_report")
    return report, path


def _query_record(index: int, topic: str, categories: list[str], providers: list[str]) -> dict[str, Any]:
    """根据主题生成可人工细化的双语查询记录。"""
    query_id = f"q{index:02d}"
    return {
        "query_id": query_id,
        "purpose": f"围绕 {topic} 检索可用于论文的外部来源",
        "target_categories": categories,
        "zh": [topic],
        "en": [topic],
        "providers": providers,
    }


def prepare_search_plan(
    run_dir: Path,
    *,
    topics: Iterable[str],
    categories: Iterable[str] = ("background", "core_method"),
    reasons: Iterable[str] = (),
    chinese_required: bool = False,
    institutional_access: str = "none",
    institution: str = "沈阳理工大学",
) -> dict[str, Any]:
    """生成并写入双语文献检索计划。

    Args:
        run_dir: 当前运行目录。
        topics: 需要检索的题型、场景或方法主题。
        categories: 目标引用类别。
        reasons: 要求中文检索的题面理由。
        chinese_required: 是否把中文检索列为硬要求。
        institutional_access: ``none`` 或用户人工认证后的 ``manual-browser``。
        institution: 已确认的机构名称，只记录公开访问路由，不记录账号。
    """
    root = run_dir.resolve()
    if not root.is_dir():
        raise ContractError(f"运行目录不存在: {root}")
    topic_list = [str(item).strip() for item in topics if str(item).strip()]
    category_list = [str(item).strip() for item in categories if str(item).strip()]
    reason_list = [str(item).strip() for item in reasons if str(item).strip()]
    if not topic_list:
        raise ContractError("至少需要一个非空检索主题")
    if not category_list or any(item not in _CATEGORIES for item in category_list):
        raise ContractError(f"检索类别必须来自: {', '.join(_CATEGORIES)}")
    if institutional_access not in {"none", "manual-browser"}:
        raise ContractError("institutional_access 只能是 none 或 manual-browser")
    providers = ["cnki", "wanfang", "library-discovery", "crossref", "openalex"]
    plan = {
        "schema_name": "literature_search_plan",
        "schema_version": "2.0",
        "run_id": root.name,
        "topics": topic_list,
        "search_scope": {
            "languages": ["zh", "en"],
            "chinese_search_required": bool(chinese_required),
            "requirement_reasons": reason_list,
            "executed_languages": [],
            "queries": [
                _query_record(index, topic, category_list, providers)
                for index, topic in enumerate(topic_list, start=1)
            ],
        },
        "institutional_access": {
            "enabled": institutional_access == "manual-browser",
            "institution": institution,
            "provider": "cnki",
            "access_mode": institutional_access,
            "authentication_mode": "carsi-saml" if institutional_access == "manual-browser" else "unknown",
            "observed_route": [
                "https://www.cnki.net/",
                "https://fsso.cnki.net/",
                "https://idp.sylu.edu.cn/",
            ],
            "provider_priority": ["library-discovery", "cnki", "wanfang"],
            "authentication": {
                "handled_by_user": True,
                "persist_credentials": False,
                "persist_cookies_in_repo": False,
            },
            "session_policy": {
                "reuse_authenticated_session": True,
                "automate_login": False,
                "reauth_requires_user": True,
            },
        },
        "generated_at": utc_now(),
    }
    _write_plan(root, plan)
    report = {
        "schema_name": "literature_search_report",
        "schema_version": "2.0",
        "run_id": root.name,
        "plan_sha256": sha256_file(_path_inside_run(root, PLAN_PATH)),
        "candidates": [],
        "audit": {"status": "not_audited", "errors": [], "warnings": []},
        "updated_at": utc_now(),
    }
    _write_report(root, report)
    return plan


def _validate_candidate(candidate: dict[str, Any], run_dir: Path) -> None:
    """校验来源候选并复核私有本地文件边界。"""
    _assert_no_secret_keys(candidate)
    require_valid(candidate, "literature_source")
    artifact = candidate.get("local_artifact")
    if artifact is not None:
        artifact_path = resolve_inside(run_dir.resolve(), str(artifact["path"]), must_exist=True)
        if sha256_file(artifact_path) != artifact["sha256"]:
            raise ContractError(f"本地文献材料哈希不匹配: {artifact['path']}")
    if candidate["selection_status"] == "selected" and not candidate.get("claim_bindings"):
        raise ContractError("selected 来源必须至少绑定一个正文判断")
    if candidate["selection_status"] == "rejected" and not str(candidate.get("rejection_reason") or "").strip():
        raise ContractError("rejected 来源必须填写不采用理由")


def record_candidate(
    run_dir: Path,
    candidate: dict[str, Any] | None = None,
    *,
    mark_languages: Iterable[str] = (),
) -> dict[str, Any]:
    """登记候选来源，并可标记某种语言检索已执行。"""
    root = run_dir.resolve()
    plan, plan_path = _load_plan(root)
    try:
        report, _ = _load_report(root)
    except ContractError:
        report = {
            "schema_name": "literature_search_report",
            "schema_version": "2.0",
            "run_id": root.name,
            "plan_sha256": sha256_file(plan_path),
            "candidates": [],
            "audit": {"status": "not_audited", "errors": [], "warnings": []},
            "updated_at": utc_now(),
        }
    if report["run_id"] != root.name:
        raise ContractError("文献报告 run_id 与运行目录不一致")
    if candidate is not None:
        _validate_candidate(candidate, root)
        if any(item["source_id"] == candidate["source_id"] for item in report["candidates"]):
            raise ContractError(f"来源 source_id 已登记: {candidate['source_id']}")
        report["candidates"].append(candidate)
    valid_languages = {"zh", "en"}
    languages = {str(item).strip() for item in mark_languages if str(item).strip()}
    if not languages <= valid_languages:
        raise ContractError("mark_languages 只能包含 zh 或 en")
    executed = set(plan["search_scope"]["executed_languages"])
    plan["search_scope"]["executed_languages"] = sorted(executed | languages)
    _write_plan(root, plan)
    report["plan_sha256"] = sha256_file(plan_path)
    report["audit"] = {"status": "not_audited", "errors": [], "warnings": []}
    report["updated_at"] = utc_now()
    _write_report(root, report)
    return report


def audit_search(run_dir: Path) -> dict[str, Any]:
    """审计检索执行状态、候选核验层级和本地材料边界。"""
    root = run_dir.resolve()
    plan, plan_path = _load_plan(root)
    report, _ = _load_report(root)
    errors: list[str] = []
    warnings: list[str] = []
    if report["run_id"] != root.name:
        errors.append("文献报告 run_id 与运行目录不一致")
    expected_sha = sha256_file(plan_path)
    if report["plan_sha256"] != expected_sha:
        errors.append("文献报告绑定的检索计划已变化，请重新登记或审计")
    scope = plan["search_scope"]
    candidates = report["candidates"]
    zh_candidates = [item for item in candidates if item["language"] == "zh"]
    if scope["chinese_search_required"] and "zh" not in scope["executed_languages"]:
        errors.append("题面要求中文来源，但中文检索尚未标记为已执行")
    elif scope["chinese_search_required"] and not zh_candidates:
        warnings.append("中文检索已执行但没有登记中文候选；请记录具体不采用理由")
    if "en" not in scope["executed_languages"]:
        warnings.append("英文检索尚未标记为已执行")
    if not candidates:
        warnings.append("尚未登记任何候选来源")
    for candidate in candidates:
        try:
            _validate_candidate(candidate, root)
        except ContractError as exc:
            errors.append(f"{candidate.get('source_id', '<unknown>')}: {exc}")
        if candidate["verification_level"] == "fulltext" and not candidate.get("fulltext_checked", False):
            errors.append(f"{candidate['source_id']}: fulltext 核验级别要求 fulltext_checked=true")
        if candidate["verification_level"] == "abstract" and not candidate.get("abstract_checked", False):
            errors.append(f"{candidate['source_id']}: abstract 核验级别要求 abstract_checked=true")
        if candidate["selection_status"] == "pending":
            warnings.append(f"候选来源尚未决定是否采用: {candidate['source_id']}")
        if candidate["selection_status"] == "selected" and candidate["verification_level"] == "metadata":
            warnings.append(f"已采用来源仅完成 metadata 核验: {candidate['source_id']}")
    status = "blocked" if errors else ("warning" if warnings else "pass")
    report["audit"] = {"status": status, "errors": errors, "warnings": warnings}
    report["updated_at"] = utc_now()
    _write_report(root, report)
    return report


def plan_sha256(run_dir: Path) -> str:
    """返回当前检索计划哈希，供外部回执绑定。"""
    return sha256_file(_path_inside_run(run_dir.resolve(), PLAN_PATH))
