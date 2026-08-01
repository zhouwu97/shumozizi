"""验证 v3.4 外部 Author 材料请求的读取、决策与硬原则。

Test C/D（设计文档 §43）：
- Test C：partial draft + AUTHOR_REQUESTS → 系统接受，草稿保留；
- Test D：缺图但 can_continue_without_it=true 且有 fallback → 进入请求裁决，
  不自动 blocked。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.paper.external_author import (
    decide_author_request,
    read_author_requests,
)
from shumozizi.simple.authoring import (
    mark_authoring_status,
    read_authoring,
    set_authoring_mode,
)
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, name: str = "requests") -> Path:
    """创建处于 waiting_external_author 的 v3.2 运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    mark_authoring_status(run_dir, "handoff_ready")
    mark_authoring_status(run_dir, "waiting_external_author")
    return run_dir


def _write_requests(run_dir: Path) -> None:
    """写入两个请求：visual（可替代）与 evidence（希望回实验）。"""
    document = {
        "schema_name": "author_request",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "requests": [
            {
                "gap_id": "GAP-Q3-01",
                "kind": "visual",
                "affected_argument": "Q3 活跃约束形成机制",
                "request": "希望展示各日期约束余量",
                "why_needed": "仅有最终结果表，机制不直观",
                "can_continue_without_it": True,
                "fallback": "使用现有约束余量表并增加文字解释",
                "recommended_route": "visual",
                "expected_benefit": "提高核心结论的可理解性",
                "estimated_cost": "low",
            },
            {
                "gap_id": "GAP-Q3-02",
                "kind": "evidence",
                "affected_argument": "Q3 下界紧性",
                "request": "需要补充更大规模的独立复算",
                "why_needed": "确认下界在更大规模下仍紧",
                "can_continue_without_it": True,
                "fallback": "声明当前规模证据",
                "recommended_route": "experiment",
                "expected_benefit": "提高下界可信度",
                "estimated_cost": "high",
            },
        ],
    }
    requests_path = run_dir / "paper/external-author/AUTHOR_REQUESTS.json"
    requests_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(requests_path, document)


def test_read_author_requests_returns_validated_requests(tmp_path: Path) -> None:
    """读取请求并校验五类 kind。"""
    run_dir = _run(tmp_path, "read")
    _write_requests(run_dir)
    requests = read_author_requests(run_dir)
    assert {item["gap_id"] for item in requests} == {"GAP-Q3-01", "GAP-Q3-02"}


def test_partial_draft_with_requests_is_accepted_and_preserved(tmp_path: Path) -> None:
    """Test C：partial draft + requests → 裁决后草稿保留，状态不被阻断。"""
    run_dir = _run(tmp_path, "partial-requests")
    draft = run_dir / "paper/external-author/draft.tex"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("\\section{Q1}\nQ1 部分内容。\n", encoding="utf-8")
    _write_requests(run_dir)
    ledger = decide_author_request(
        run_dir,
        [
            {
                "gap_id": "GAP-Q3-01",
                "decision": "substitute",
                "route": "author",
                "reason": "新图价值一般，公式+表格足够",
            },
            {
                "gap_id": "GAP-Q3-02",
                "decision": "waive",
                "route": "author",
                "reason": "当前规模证据已足够支撑结论",
            },
        ],
    )
    assert ledger["decisions"][0]["decision"] == "substitute"
    assert ledger["decisions"][0]["route"] == "author"
    assert draft.is_file()  # 草稿永不自动丢弃
    assert read_authoring(run_dir)["authoring_status"] == "waiting_external_author"


def test_waivable_visual_request_does_not_block(tmp_path: Path) -> None:
    """Test D：缺图但 can_continue_without_it=true + fallback → waive 合法。"""
    run_dir = _run(tmp_path, "waive")
    _write_requests(run_dir)
    ledger = decide_author_request(
        run_dir,
        [
            {
                "gap_id": "GAP-Q3-01",
                "decision": "waive",
                "route": "author",
                "reason": "问题真实但收益不值得成本",
            },
            {
                "gap_id": "GAP-Q3-02",
                "decision": "waive",
                "route": "author",
                "reason": "更大规模复算超出赛程预算",
            },
        ],
    )
    assert ledger["decisions"][0]["decision"] == "waive"


def test_partial_request_coverage_is_rejected(tmp_path: Path) -> None:
    """P1-1：只裁决一部分请求不允许声称 resolved。"""
    run_dir = _run(tmp_path, "partial-coverage")
    _write_requests(run_dir)
    with pytest.raises(ContractError, match="覆盖全部作者请求"):
        decide_author_request(
            run_dir,
            [
                {
                    "gap_id": "GAP-Q3-01",
                    "decision": "waive",
                    "route": "author",
                    "reason": "只处理一个",
                }
            ],
        )


def test_evidence_request_cannot_auto_route_to_experiment(tmp_path: Path) -> None:
    """硬原则 §16：作者请求不能自动变成实验任务。"""
    run_dir = _run(tmp_path, "no-experiment")
    _write_requests(run_dir)
    with pytest.raises(ContractError, match="不能直接返回实验"):
        decide_author_request(
            run_dir,
            [
                {
                    "gap_id": "GAP-Q3-02",
                    "decision": "fulfill",
                    "route": "experiment",
                    "reason": "作者想要更多复算",
                }
            ],
        )


def test_experiment_route_requires_explicit_scientific_value(tmp_path: Path) -> None:
    """只有声明科学价值且 fulfill 时才允许返回 experiment。"""
    run_dir = _run(tmp_path, "sci-value")
    _write_requests(run_dir)
    ledger = decide_author_request(
        run_dir,
        [
            {
                "gap_id": "GAP-Q3-02",
                "decision": "fulfill",
                "route": "experiment",
                "reason": "检验下界在更大规模下是否仍紧",
                "scientific_value": "closes_evidence_gap",
            },
            {
                "gap_id": "GAP-Q3-01",
                "decision": "substitute",
                "route": "author",
                "reason": "约束余量表已足够",
            },
        ],
    )
    assert ledger["decisions"][0]["route"] == "experiment"


def test_fulfill_upstream_request_advances_rework_requested(tmp_path: Path) -> None:
    """P1-2：fulfill visual/experiment → 草稿标为 rework_requested。"""
    run_dir = _run(tmp_path, "rework-status")
    from shumozizi.simple.authoring import mark_authoring_status

    mark_authoring_status(run_dir, "draft_imported")  # 外部稿已导入
    _write_requests(run_dir)
    decide_author_request(
        run_dir,
        [
            {
                "gap_id": "GAP-Q3-01",
                "decision": "fulfill",
                "route": "visual",
                "reason": "约束余量图确实必要",
            },
            {
                "gap_id": "GAP-Q3-02",
                "decision": "waive",
                "route": "author",
                "reason": "当前规模证据已足够",
            },
        ],
    )
    assert read_authoring(run_dir)["authoring_status"] == "rework_requested"


def test_reject_must_record_reason(tmp_path: Path) -> None:
    """reject 决策必须记录具体原因。"""
    run_dir = _run(tmp_path, "reject")
    _write_requests(run_dir)
    with pytest.raises(ContractError, match="原因"):
        decide_author_request(
            run_dir,
            [{"gap_id": "GAP-Q3-01", "decision": "reject", "route": "author", "reason": ""}],
        )


def test_unknown_request_is_rejected(tmp_path: Path) -> None:
    """裁决不存在的 gap_id 必须被拒绝。"""
    run_dir = _run(tmp_path, "unknown")
    _write_requests(run_dir)
    with pytest.raises(ContractError, match="找不到作者请求"):
        decide_author_request(
            run_dir,
            [{"gap_id": "GAP-NOPE", "decision": "waive", "route": "author", "reason": "测试"}],
        )
