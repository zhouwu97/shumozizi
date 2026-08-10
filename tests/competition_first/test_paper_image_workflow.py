"""论文解释图 P0 规划与候选状态机回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.paper_image_generation import run_paper_image_generation
from shumozizi.simple.paper_image_prompts import build_paper_image_prompts
from shumozizi.simple.paper_image_review import (
    HARD_CHECKS,
    invalidate_promoted_candidate,
    select_review,
    validate_review,
)


def _hard(status: str = "PASS") -> dict[str, str]:
    """构造统一 Hard review。"""
    return {key: status for key in HARD_CHECKS}


def _review(status: str = "PASS", *, score: float = 8.5, richness: float = 8.0, generic: float = 2.0) -> dict[str, object]:
    """构造包含信息图质量门的审图结果。"""
    return {
        "hard_checks": _hard(status),
        "soft_score": score,
        "academic_visual_richness": richness,
        "generic_box_diagram_score": generic,
        "generic_box_diagram_level": "HIGH" if generic >= 7 else "LOW",
        "non_text_visual_elements": ["formula", "network_sketch"],
        "issues": [],
    }


def _prompt_run(tmp_path: Path) -> Path:
    """构造一个与具体题目无关的调度问题最小运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "paper-image-scheduling",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_name": "modeling_units",
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "unit_id": "u1",
                    "question_id": "Q1",
                    "unit_kind": "coordination",
                    "core_question": True,
                    "visual_outputs": [
                        {
                            "visual_question": "资源如何经过分配和约束形成班次？",
                            "takeaway": "共享资源约束决定最终排班。",
                            "visual_archetype": "structure map",
                        }
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": "schedule-current",
                    "result_ids": ["schedule-current"],
                    "objective_answer": {"result_id": "schedule-current", "answer": "排班方案"},
                }
            }
        },
    )
    atomic_json(
        run_dir / "results/index.json",
        {
            "results": [
                {
                    "result_id": "schedule-current",
                    "question_id": "Q1",
                    "status": "current",
                    "execution_valid": True,
                    "metrics": {"coverage": 0.92},
                    "metric_sources": {},
                }
            ]
        },
    )
    return run_dir


def test_prompt_builder_is_domain_agnostic_and_low_is_suggested_only(tmp_path: Path) -> None:
    """调度题只依赖结构化单元，且 P0 只生产 academic_flowchart。"""
    run_dir = _prompt_run(tmp_path)
    payload = build_paper_image_prompts(run_dir)

    assert payload["generated_count"] >= 1
    planned = [item for item in payload["planned"] if item["status"] == "planned"]
    assert planned
    assert len(planned) == 1
    assert len({item["image_id"] for item in payload["planned"]}) == len(payload["planned"])
    assert (run_dir / "figures/prompts/plan.json").is_file()
    assert all(item["visual_type"] == "academic_flowchart" for item in planned)
    requirements = load_json(run_dir / "paper/generated/VISUAL_REQUIREMENTS.json")
    assert any(
        item["paper_image_opportunity"]["production_status"] == "planned"
        for item in requirements["requirements"]
    )
    for item in planned:
        prompt_dir = run_dir / "figures/prompts" / item["image_id"]
        assert (prompt_dir / "meta.json").is_file()
        assert (prompt_dir / "variant_a.txt").is_file()
        assert (prompt_dir / "variant_b.txt").is_file()
        meta = load_json(prompt_dir / "meta.json")
        assert meta["must_not_confuse"]
        assert meta["style_reference"] == "academic_bilingual_infographic_v1"
        assert len(meta["visual_elements"]) >= 2
        assert "数学对象必须被画出来" in (prompt_dir / "variant_b.txt").read_text(encoding="utf-8")
        assert "内容蓝图（必须按对象绘制" in (prompt_dir / "variant_b.txt").read_text(encoding="utf-8")
        assert (prompt_dir / "variant_a.txt").read_text(encoding="utf-8") != (
            prompt_dir / "variant_b.txt"
        ).read_text(encoding="utf-8")


def test_review_hard_fail_and_uncertain_cannot_keep() -> None:
    """Hard FAIL/UNCERTAIN 必须阻断，即使 soft score 很高。"""
    for status in ("FAIL", "UNCERTAIN"):
        result = validate_review(
            {**_review(), "candidate": "a.png", "attempt": 1, "hard_checks": {**_hard(), "critical_values_correct": status}, "issues": ["需复核"]}
        )
        assert result["hard_pass"] is False
        assert result["verdict"] == "RETRY"
    selected = select_review(
        [
            {**_review(), "candidate": "a.png", "attempt": 1, "hard_checks": {**_hard(), "critical_values_correct": "FAIL"}, "soft_score": 9.9, "issues": ["数值错误"]},
            {**_review(), "candidate": "b.png", "attempt": 1, "soft_score": 8.0},
        ]
    )
    assert selected["selected_candidate"] == "b.png"


def test_generation_retries_then_registers_pending_promotion(tmp_path: Path) -> None:
    """首轮失败、第二轮通过时只进入 Sandbox pending，不直接复制到 current。"""
    run_dir = _prompt_run(tmp_path)
    plan = build_paper_image_prompts(run_dir)
    image_id = next(item["image_id"] for item in plan["planned"] if item["status"] == "planned")
    calls: list[str] = []

    def generator(prompt: Path, output: Path, meta: Path) -> None:
        del meta
        calls.append(prompt.name)
        output.write_bytes(b"fake-png")

    def reviewer(meta: Path, image: Path, prompt: Path, attempt: int) -> dict[str, object]:
        del meta, image, prompt
        return {**_review("FAIL" if attempt == 1 else "PASS"), "issues": [] if attempt == 2 else ["首轮失败"]}

    result = run_paper_image_generation(
        run_dir,
        image_id,
        generator=generator,
        reviewer=reviewer,
        reviewer_context_id="fresh-paper-image-review",
    )

    assert result["status"] == "selected_pending_promotion"
    assert len(calls) == 4
    assert not (run_dir / f"figures/current/{image_id}.png").exists()
    assert load_json(run_dir / f"figures/sandbox/{image_id}/review.json")["formal_render_required"] is True


def test_generation_two_round_failure_routes_drawio(tmp_path: Path) -> None:
    """两轮 Hard 失败后必须 DROP_AI_IMAGE 并留下 DrawIO fallback。"""
    run_dir = _prompt_run(tmp_path)
    plan = build_paper_image_prompts(run_dir)
    image_id = next(item["image_id"] for item in plan["planned"] if item["status"] == "planned")

    def generator(prompt: Path, output: Path, meta: Path) -> None:
        del prompt, meta
        output.write_bytes(b"fake-png")

    def reviewer(meta: Path, image: Path, prompt: Path, attempt: int) -> dict[str, object]:
        del meta, image, prompt, attempt
        return {**_review("FAIL", score=10.0), "issues": ["无法确认数值"]}

    result = run_paper_image_generation(
        run_dir,
        image_id,
        generator=generator,
        reviewer=reviewer,
        reviewer_context_id="fresh-paper-image-review",
    )

    assert result["status"] == "DROP_AI_IMAGE"
    assert result["fallback"] == "drawio"


def test_generic_box_diagram_caps_score_and_missing_visuals_fail() -> None:
    """普通框图即使声称 9.2 也必须被限分，Hero 缺少非文字元素不能通过。"""
    capped = validate_review(
        {**_review(score=9.2, richness=8.5, generic=8.5), "candidate": "box.png", "attempt": 1}
    )
    assert capped["soft_score"] == 6.5
    assert capped["score_cap_reasons"] == ["generic_box_diagram=HIGH"]

    failed = validate_review(
        {
            **_review(),
            "candidate": "text-only.png",
            "attempt": 1,
            "non_text_visual_elements": ["icon"],
        }
    )
    assert failed["hard_pass"] is False
    assert failed["verdict"] == "RETRY"


def test_duplicate_requirement_id_is_rejected_before_prompt_write(tmp_path: Path) -> None:
    """重复需求不得静默覆盖同一个 Prompt 目录。"""
    run_dir = _prompt_run(tmp_path)
    build_paper_image_prompts(run_dir)
    requirements_path = run_dir / "paper/generated/VISUAL_REQUIREMENTS.json"
    payload = load_json(requirements_path)
    payload["requirements"].append(dict(payload["requirements"][0]))
    atomic_json(requirements_path, payload)

    with pytest.raises(ContractError, match="需求 ID 缺失或重复"):
        build_paper_image_prompts(run_dir, refresh_requirements=False)


def test_invalidate_promoted_candidate_archives_and_revokes_current(tmp_path: Path) -> None:
    """旧普通框图撤销后必须归档、禁入论文并删除 current 文件。"""
    run_dir = _prompt_run(tmp_path)
    current_paths = [
        run_dir / "figures/current/old-flow.png",
        run_dir / "figures/current/old-flow.pdf",
        run_dir / "figures/current/old-flow.svg",
    ]
    for current in current_paths:
        current.parent.mkdir(parents=True, exist_ok=True)
        current.write_bytes(b"old-flow")
    index = load_json(run_dir / "figures/index.json")
    index["schema_version"] = "1.0"
    index["figures"].append(
        {
            "figure_id": "old-flow",
            "question_id": "Q1",
            "role": "model_understanding",
            "outputs": [
                {"path": f"figures/current/{path.name}", "sha256": "0" * 64}
                for path in current_paths
            ],
            "status": "current",
            "paper_allowed": True,
            "demo": False,
            "created_at": "2026-08-08T00:00:00Z",
        }
    )
    atomic_json(run_dir / "figures/index.json", index)

    record = invalidate_promoted_candidate(
        run_dir,
        figure_id="old-flow",
        image_id="old-flow-image",
        reason="普通框图未满足论文级信息图质量门。",
    )

    assert record["verdict"] == "DROP_AI_IMAGE"
    assert all(not path.exists() for path in current_paths)
    archived = run_dir / record["archived_outputs"][0]["archive"]
    assert archived.read_bytes() == b"old-flow"
    updated = load_json(run_dir / "figures/index.json")["figures"][-1]
    assert updated["status"] == "superseded"
    assert updated["paper_allowed"] is False
