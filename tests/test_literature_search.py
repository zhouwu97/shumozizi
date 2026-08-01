"""验证按需文献检索计划、候选记录和安全审计。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.paper.literature import audit_search, prepare_search_plan, record_candidate
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import utc_now


def _new_run(tmp_path: Path, run_id: str) -> Path:
    """创建最小论文运行目录。"""
    return initialize_simple_run(tmp_path, run_id, workflow_version="3.2")


def _candidate(source_id: str = "zh-001", *, status: str = "selected") -> dict:
    """构造不含凭据的来源候选。"""
    payload = {
        "schema_name": "literature_source",
        "schema_version": "2.0",
        "source_id": source_id,
        "title": "本土场景中的协同优化研究",
        "authors": ["作者甲"],
        "year": 2024,
        "language": "zh",
        "discovery_provider": "cnki",
        "canonical_source": "某学术期刊",
        "source_type": "journal",
        "verification_level": "abstract",
        "abstract_checked": True,
        "selection_status": status,
        "categories": ["background"],
        "retrieved_at": utc_now(),
    }
    if status == "selected":
        payload["claim_bindings"] = ["中国场景约束"]
    elif status == "rejected":
        payload["rejection_reason"] = "仅为二次介绍"
    return payload


def test_prepare_record_and_audit_are_reproducible(tmp_path: Path) -> None:
    """计划、候选和审计报告应绑定当前 run 且可顺序写入。"""
    run_dir = _new_run(tmp_path, "literature-pass")
    plan = prepare_search_plan(
        run_dir,
        topics=["多无人机协同路径规划"],
        categories=["background", "core_method"],
        reasons=["中国本土行业背景"],
        chinese_required=True,
        institutional_access="manual-browser",
    )
    assert plan["institutional_access"]["authentication"]["persist_credentials"] is False
    assert plan["institutional_access"]["institution"] == "沈阳理工大学"
    assert plan["institutional_access"]["authentication_mode"] == "carsi-saml"
    assert plan["institutional_access"]["session_policy"]["reuse_authenticated_session"] is True
    assert plan["institutional_access"]["session_policy"]["automate_login"] is False
    record_candidate(run_dir, _candidate(), mark_languages=["zh", "en"])

    report = audit_search(run_dir)

    assert report["audit"]["status"] == "pass"
    assert report["candidates"][0]["source_id"] == "zh-001"


def test_required_chinese_search_is_conditional_not_count_quota(tmp_path: Path) -> None:
    """执行中文检索但没有合适来源时只提示，不强迫凑引用。"""
    run_dir = _new_run(tmp_path, "literature-no-selection")
    prepare_search_plan(
        run_dir,
        topics=["纯数学定理"],
        categories=["core_method"],
        chinese_required=True,
        reasons=["中文术语核对"],
    )
    record_candidate(run_dir, mark_languages=["zh", "en"])

    report = audit_search(run_dir)

    assert report["audit"]["status"] == "warning"
    assert not report["audit"]["errors"]
    assert any("没有登记中文候选" in item for item in report["audit"]["warnings"])


def test_unexecuted_required_language_blocks(tmp_path: Path) -> None:
    """必需中文检索未执行时才形成硬错误。"""
    run_dir = _new_run(tmp_path, "literature-blocked")
    prepare_search_plan(run_dir, topics=["中国交通标准"], chinese_required=True)

    report = audit_search(run_dir)

    assert report["audit"]["status"] == "blocked"
    assert any("尚未标记为已执行" in item for item in report["audit"]["errors"])


def test_credential_fields_are_rejected(tmp_path: Path) -> None:
    """密码、Cookie 等字段不得进入来源账本。"""
    run_dir = _new_run(tmp_path, "literature-secret")
    prepare_search_plan(run_dir, topics=["协同优化"])
    candidate = _candidate()
    candidate["password"] = "not-written"

    with pytest.raises(ContractError, match="凭据字段"):
        record_candidate(run_dir, candidate)


def test_selected_metadata_only_source_is_advisory(tmp_path: Path) -> None:
    """只完成元数据核验的采用来源应提示提高核验等级。"""
    run_dir = _new_run(tmp_path, "literature-metadata")
    prepare_search_plan(run_dir, topics=["协同优化"])
    candidate = _candidate()
    candidate["verification_level"] = "metadata"
    candidate.pop("abstract_checked")
    record_candidate(run_dir, candidate, mark_languages=["zh"])

    report = audit_search(run_dir)

    assert report["audit"]["status"] == "warning"
    assert any("metadata 核验" in item for item in report["audit"]["warnings"])
