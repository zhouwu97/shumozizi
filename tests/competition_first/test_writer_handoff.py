"""验证 v3.4 Writer Handoff Checkpoint：就绪、构建、暂停与新鲜度。

正向路径（Test A）隔离了 ``require_paper_generation_allowed``：该函数是
v3.2 科学门禁，已由 ``test_competition_first_v32.py`` 单独覆盖。这里用
monkeypatch 把它置空，聚焦本模块新增的 handoff 逻辑本身。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.handoff import (
    build_writer_handoff,
    handoff_status,
    mark_waiting_external_author,
    verify_handoff_freshness,
    writer_handoff_readiness,
)
from shumozizi.paper.materials import build_material_pool
from shumozizi.paper.storyboard import build_research_storyboard
from shumozizi.simple.authoring import (
    mark_authoring_status,
    read_authoring,
    require_internal_authoring,
    set_authoring_mode,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review_focus import record_scientific_challenge_evidence
from shumozizi.simple.state import read_simple_state, write_simple_state

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(tmp_path: Path, name: str = "handoff") -> Path:
    """创建最小 v3.2 运行并把阶段推进到 paper。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )
    state = read_simple_state(run_dir)
    state["phase"] = "paper"
    write_simple_state(run_dir, state)
    return run_dir


def _write_results(run_dir: Path) -> None:
    """写入三问的 current production 结果，供直接答案兜底。"""
    index = load_json(run_dir / "results/index.json")
    for question_id, objective in (("Q1", 12.0), ("Q2", 8.0), ("Q3", 581.0)):
        index["results"].append(
            {
                "result_id": f"r-{question_id}",
                "question_id": question_id,
                "kind": "test",
                "source_script": None,
                "command": "test",
                "input_files": [],
                "input_hashes": {},
                "output_files": [],
                "output_hashes": {},
                "metric_sources": {},
                "method_facts": {},
                "status": "current",
                "execution_mode": "production",
                "execution_valid": True,
                "exit_code": 0,
                "stdout_path": f"results/{question_id}.stdout.log",
                "stderr_path": f"results/{question_id}.stderr.log",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "duration_seconds": 1.0,
                "error": None,
                "created_at": "2026-01-01T00:00:01Z",
                "objective_semantics_sha256": "0" * 64,
                "dependency_scope": "question",
                "affected_question_ids": [question_id],
                "metrics": {"objective": objective, "feasible": True},
            }
        )
    atomic_json(run_dir / "results/index.json", index)
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                question_id: {
                    "primary_result_id": f"r-{question_id}",
                    "result_ids": [f"r-{question_id}"],
                    "direct_answer_location": f"{question_id} 结论",
                    "objective_answer": {
                        "result_id": f"r-{question_id}",
                        "answer": f"{question_id} 的正式目标值为 {objective}。",
                    },
                }
                for question_id, objective in (("Q1", 12.0), ("Q2", 8.0), ("Q3", 581.0))
            }
        },
    )


def _material_items() -> list[dict[str, object]]:
    """为三问各提供直接答案/推导/机制/边界四类素材。"""
    items: list[dict[str, object]] = []
    for question_id in ("Q1", "Q2", "Q3"):
        roles = {
            "Direct Answer": "正式答案由活动约束的互补松弛条件唯一决定。",
            "Mathematical Derivation": "由拉格朗日函数的 KKT 条件导出判据。",
            "Mechanism": "容量约束活跃后边际收益递减。",
            "Boundary/Robustness": "该结论只覆盖已测试的预算区间。",
        }
        for category, content in roles.items():
            items.append(
                {
                    "material_id": f"{question_id}-{category.split('/')[0].lower().replace(' ', '-')}",
                    "category": category,
                    "title": f"{question_id} {category}",
                    "content": content,
                    "question_id": question_id,
                    "source_result_ids": [f"r-{question_id}"],
                    "source_figure_ids": [],
                    "inclusion": "body",
                }
            )
    return items


def _storyboard_cards(pool: dict[str, object]) -> list[dict[str, object]]:
    """为三问各生成覆盖全部实质字段的问题卡。"""
    material_ids = [str(item["material_id"]) for item in pool["items"]]
    cards: list[dict[str, object]] = []
    for question_id in ("Q1", "Q2", "Q3"):
        card: dict[str, object] = {
            "question_id": question_id,
            "reader_needs": f"{question_id} 需要先定位共享模型下的直接答案。",
            "phenomenon": f"{question_id} 的结果呈现明显容量拐点。",
            "why_math_object": f"{question_id} 需要引入统一的决策变量与约束集。",
            "model_evolution": f"{question_id} 在前问共享模型上新增资源耦合约束。",
            "key_derivation": f"{question_id} 由互补松弛条件导出活动约束判据。",
            "structural_finding": f"{question_id} 的答案由唯一活动约束决定。",
            "decision_determinant": f"{question_id} 的正式答案绑定 objective_answer 结果。",
            "mechanism": f"{question_id} 的边际收益在容量约束活跃后递减。",
            "contrast": f"{question_id} 与放宽容量约束的替代方案形成对照。",
            "boundary": f"{question_id} 的结论只适用于已测试的参数区间。",
            "best_media": ["表格", "活动约束图"],
            "material_ids": material_ids,
        }
        if question_id != "Q3":
            card["handoff_to_next"] = {
                "Q1": "把判据交给 Q2 的新增约束。",
                "Q2": "把活动约束集合交给 Q3 的全局配置。",
            }[question_id]
        cards.append(card)
    return cards


def _build_assets(run_dir: Path) -> dict[str, object]:
    """写入素材池、故事板、蓝图、主张门禁与科学挑战证据。"""
    pool = build_material_pool(run_dir, materials=_material_items())
    build_research_storyboard(run_dir, cards=_storyboard_cards(pool))
    blueprint = (
        "# 论证驱动论文\n\n"
        "## 中心判断\n"
        "本文最终主张最小可行人数由第 12 日的活跃约束决定，该结论在当前模型与"
        "约束下是紧下界，并有对应的可行构造作为证据。\n\n"
        "## 论证链\n"
        "题面给出需求峰值与可用班次的耦合约束。我们把这些事实形式化为统一决策"
        "变量与共享约束集，导出活动约束判据，再由真实实验给出数值结果，最后把"
        "该结果与放宽容量约束的替代方案对照，说明为何该结论成立。\n\n"
        "## 各问递进\n"
        "Q1 建立基本数学对象与评价指标，明确单体评价口径；Q2 在 Q1 基础上引入"
        "资源耦合的新共享约束，改变可行域结构；Q3 进一步考虑时间覆盖，形成全局"
        "配置模型，各问共用同一目标与判据，后问只增加约束而不重造模型。\n\n"
        "## 核心矛盾\n"
        "需求峰值与有限班次之间的资源冲突是全文的主要矛盾，第 12 日约束余量最"
        "小，因此成为控制日期。\n\n"
        "## 主要讨论\n"
        "结果为什么呈现当前结构：因为只有一处约束真正活跃，其余日期均有冗余。\n\n"
        "## 完整性预算\n"
        "逐问预留问题分析、模型流、推导、算法、结果解释和验证边界的空间，核心"
        "问题允许显著更多篇幅。"
    )
    (run_dir / "paper/PAPER_BLUEPRINT.md").write_text(blueprint, encoding="utf-8")
    gate = {
        "schema_name": "paper_claim_gate",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "evaluator_version": "test",
        "stale": False,
        "claimability": "claims",
        "claims": [
            {
                "claim_id": "c-q3",
                "question_id": "Q3",
                "status": "supported",
                "reference_allowed": True,
                "contribution_mode": "full",
                "allowed_uses": ["contribution", "results", "limitations"],
                "reason": "581 是当前模型约束下的紧下界并有可行构造。",
            }
        ],
    }
    atomic_json(run_dir / "paper/claim_gate.json", gate)
    record_scientific_challenge_evidence(
        run_dir,
        result_ids=["r-Q1", "r-Q2", "r-Q3"],
        attack_description="独立复核三问正式结果、约束和主张边界。",
        findings=[],
    )
    return {"pool": pool}


def _ready_run(tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    """构造满足全部 handoff 条件的运行（隔离科学门禁）。"""
    run_dir = _run(tmp_path, name)
    _write_results(run_dir)
    _build_assets(run_dir)
    import shumozizi.paper.handoff as handoff

    monkeypatch.setattr(
        handoff.simple_review,
        "require_paper_generation_allowed",
        lambda run_dir: None,
    )
    return run_dir


def test_bare_run_blocks_handoff_with_reasons(tmp_path: Path) -> None:
    """材料不足时 WRITER_HANDOFF 必须 blocked 并给出可读原因。"""
    run_dir = _run(tmp_path, "bare")
    readiness = writer_handoff_readiness(run_dir)
    assert readiness["ready"] is False
    assert readiness["reasons"]
    with pytest.raises(ContractError, match="未就绪"):
        build_writer_handoff(run_dir)


def test_prepare_writer_handoff_cli_blocks_with_exit_code_1(tmp_path: Path) -> None:
    """CLI 在材料不足时输出 blocked 并以退出码 1 结束。"""
    run_dir = _run(tmp_path, "cli-blocked")
    script = REPO_ROOT / "scripts/paper/prepare_writer_handoff.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(run_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 1
    assert '"status": "blocked"' in completed.stdout


def test_material_sufficient_reaches_waiting_external_author(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test A：材料充分 → handoff_ready → waiting_external_author，阶段保持 paper。"""
    run_dir = _ready_run(tmp_path, "ready", monkeypatch)
    set_authoring_mode(run_dir, "external_handoff", reason="交给外部写作模型")
    mark_authoring_status(run_dir, "handoff_ready")
    receipt = build_writer_handoff(run_dir)
    assert receipt["status"] == "WRITER_HANDOFF_READY"
    mark_waiting_external_author(run_dir)

    authoring = read_authoring(run_dir)
    assert authoring["authoring_status"] == "waiting_external_author"
    assert read_simple_state(run_dir)["phase"] == "paper"  # 非 blocked

    manifest = load_json(run_dir / "paper/writer-handoff/manifest.json")
    for relative in receipt["writer_files"]:
        assert (run_dir / relative).is_file()
    assert (run_dir / "review/writer-handoff-ready.json").is_file()
    assert manifest["run_id"] == run_dir.name


def test_handoff_files_are_writer_facing_not_control_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writer 文件不含 result_id/哈希等控制字段；机器绑定留在 JSON 与 manifest。"""
    run_dir = _ready_run(tmp_path, "faces", monkeypatch)
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    build_writer_handoff(run_dir)
    research_package = (run_dir / "paper/writer-handoff/RESEARCH_PACKAGE.md").read_text(
        encoding="utf-8"
    )
    assert "result_id" not in research_package
    assert "sha256" not in research_package
    assert "正式答案" in research_package
    author_brief = (run_dir / "paper/writer-handoff/AUTHOR_BRIEF.md").read_text(
        encoding="utf-8"
    )
    assert "完整数学建模竞赛论文" in author_brief
    assert "国奖级完整竞赛论文" in author_brief
    assert "应提出返工请求" in author_brief
    manifest = load_json(run_dir / "paper/writer-handoff/manifest.json")
    assert sorted(manifest["writer_files"]) == [
        "paper/writer-handoff/AUTHOR_BRIEF.md",
        "paper/writer-handoff/RESEARCH_PACKAGE.md",
    ]
    handoff_root = run_dir / "paper/writer-handoff"
    for filename in (
        "WRITER_BRIEF.md",
        "PAPER_BLUEPRINT.md",
        "ANSWER_AND_CLAIMS.md",
        "MATERIAL_POOL.md",
        "FIGURE_CATALOG.md",
        "CITATION_PACKET.md",
    ):
        assert not (handoff_root / filename).exists()
        assert (handoff_root / "internal" / filename).is_file()
    assert (handoff_root / "RESEARCH_PACKAGE.md").read_bytes() == (
        run_dir / "paper/author-pass/RESEARCH_PACKAGE.md"
    ).read_bytes()
    answer_json = load_json(run_dir / "paper/writer-handoff/answer-and-claims.json")
    assert any(q["question_id"] == "Q3" and q["must_answer"] for q in answer_json["questions"])
    assert next(
        q["essential_numbers"] for q in answer_json["questions"] if q["question_id"] == "Q3"
    ) == [581.0]


def test_freshness_detects_writer_file_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writer 文件被改动后，verify_handoff_freshness 必须报告 stale。"""
    run_dir = _ready_run(tmp_path, "stale", monkeypatch)
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    build_writer_handoff(run_dir)
    assert verify_handoff_freshness(run_dir)["fresh"] is True
    package_md = run_dir / "paper/writer-handoff/RESEARCH_PACKAGE.md"
    package_md.write_text(
        package_md.read_text(encoding="utf-8") + "\n外部 Author 附加内容\n", encoding="utf-8"
    )
    result = verify_handoff_freshness(run_dir)
    assert result["fresh"] is False
    assert any("writer 文件已变化" in reason for reason in result["reasons"])


def test_external_handoff_blocks_auto_compile(tmp_path: Path) -> None:
    """Test B：external 模式 waiting_external_author 后禁止自动撰写正式正文。"""
    run_dir = _run(tmp_path, "guard")
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    mark_authoring_status(run_dir, "handoff_ready")
    mark_authoring_status(run_dir, "waiting_external_author")

    from shumozizi.paper.compiler import compile_longform_draft

    with pytest.raises(ContractError, match="禁止自动撰写正式正文"):
        compile_longform_draft(run_dir)

    # 导入外部稿后允许编译入口继续（其余检查由各自门禁负责）。
    mark_authoring_status(run_dir, "draft_imported")
    require_internal_authoring(run_dir)


def test_internal_mode_compile_is_not_blocked(tmp_path: Path) -> None:
    """内部写作模式不受 authoring 编译守卫影响。"""
    run_dir = _run(tmp_path, "internal-ok")
    require_internal_authoring(run_dir)


def test_handoff_status_summary(tmp_path: Path) -> None:
    """handoff_status 汇总 authoring、就绪与新鲜度。"""
    run_dir = _run(tmp_path, "status")
    status = handoff_status(run_dir)
    assert status["authoring_mode"] == "internal"
    assert status["ready"] is False
    assert status["external_draft_present"] is False
