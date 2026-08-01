"""在隔离副本上回放 v3.4 的素材—故事板—视觉—论文前置闭环。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, atomic_json, load_json  # noqa: E402
from shumozizi.knowledge.retrieval import write_analysis_knowledge_retrieval  # noqa: E402
from shumozizi.paper.editorial import editorial_readiness  # noqa: E402
from shumozizi.paper.materials import (  # noqa: E402
    build_material_pool,
    material_pool_quality_report,
    require_material_pool,
    validate_material_pool_freshness,
)
from shumozizi.paper.storyboard import (  # noqa: E402
    build_research_storyboard,
    read_research_storyboard,
    require_research_storyboard,
    storyboard_quality_report,
    validate_storyboard_freshness,
)
from shumozizi.simple.visual_opportunities import (  # noqa: E402
    build_visual_opportunity_pool,
    visual_opportunity_pool_freshness,
)


def _copy_run(source: Path, output: Path) -> Path:
    """把旧生产运行复制到隔离回放目录，避免改写用户原运行。"""
    destination = output / source.name
    if destination.exists():
        raise ContractError(f"回放目标已存在: {destination}")
    shutil.copytree(source, destination)
    return destination


def _record_gate(callable_: Any) -> dict[str, Any]:
    """执行一个前置门并把失败作为证据记录，而不是吞掉。"""
    try:
        value = callable_()
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"ready": False, "reason": str(exc)}
    if isinstance(value, dict):
        # 质量/新鲜度报告可能以“正常返回报告”表达未通过，不能只看函数未抛异常。
        ready = value.get("substantive") is not False and value.get("current") is not False
        return {"ready": ready, "result": value}
    return {"ready": True, "result": str(value)}


def replay_run(source: Path, output: Path, *, index_path: Path) -> dict[str, Any]:
    """回放一个旧正式结果运行并返回结构化证据。"""
    run_dir = _copy_run(source.resolve(), output)
    retrieval_path = run_dir / "knowledge/TASK_FINGERPRINT.json"
    retrieval = {"status": "unavailable_with_reason", "reason": "旧运行缺少 TASK_FINGERPRINT.json"}
    if retrieval_path.is_file():
        fingerprint = load_json(retrieval_path)
        written = write_analysis_knowledge_retrieval(
            run_dir,
            index_path,
            fingerprint,
        )
        retrieval = load_json(written)

    old_storyboard: dict[str, Any] | None = None
    storyboard_path = run_dir / "paper/generated/research_storyboard.json"
    if storyboard_path.is_file():
        try:
            old_storyboard = read_research_storyboard(run_dir)
        except (ContractError, OSError, ValueError):
            old_storyboard = None

    material_pool = build_material_pool(run_dir)
    if old_storyboard is not None:
        storyboard = build_research_storyboard(
            run_dir,
            cards=old_storyboard.get("question_cards", []),
            cross_question_links=old_storyboard.get("cross_question_links", []),
        )
    else:
        storyboard = build_research_storyboard(run_dir)
    visual_draft = build_visual_opportunity_pool(run_dir)
    if visual_draft.get("opportunities"):
        visual = build_visual_opportunity_pool(
            run_dir,
            opportunities=visual_draft["opportunities"],
        )
    else:
        visual = visual_draft

    current_figures = [
        path.relative_to(run_dir).as_posix()
        for path in (run_dir / "figures/current").rglob("*")
        if path.is_file()
    ]
    material_gate = _record_gate(lambda: material_pool_quality_report(run_dir))
    storyboard_gate = _record_gate(lambda: storyboard_quality_report(run_dir))
    strict_material = _record_gate(
        lambda: require_material_pool(run_dir, substantive=True)
    )
    strict_storyboard = _record_gate(
        lambda: require_research_storyboard(run_dir, substantive=True)
    )
    page_budget_gate = {
        "ready": (run_dir / "qa/paper-page-budget.json").is_file(),
        "reason": "旧运行尚未生成候选 PDF 页数审计"
        if not (run_dir / "qa/paper-page-budget.json").is_file()
        else "已有页数审计",
    }
    report = {
        "source_run": source.name,
        "replay_run": run_dir.name,
        "current_figure_count": len(current_figures),
        "current_figure_files": current_figures,
        "material_pool": {
            "item_count": len(material_pool.get("items", [])),
            "freshness": validate_material_pool_freshness(run_dir),
            "quality": material_gate,
            "strict_longform_gate": strict_material,
        },
        "storyboard": {
            "question_count": len(storyboard.get("question_cards", [])),
            "freshness": validate_storyboard_freshness(run_dir),
            "quality": storyboard_gate,
            "strict_longform_gate": strict_storyboard,
        },
        "visual": {
            "opportunity_count": len(visual.get("opportunities", [])),
            "status": visual.get("status"),
            "knowledge_check": visual.get("knowledge_check"),
            "freshness": _record_gate(lambda: visual_opportunity_pool_freshness(run_dir)),
        },
        "longform": {
            "ready": strict_material["ready"] and strict_storyboard["ready"],
            "reason": "素材池和故事板均通过严格门" if strict_material["ready"] and strict_storyboard["ready"] else "严格长篇前置门未闭合",
        },
        "cold_reader": editorial_readiness(run_dir, require_record=True),
        "candidate": {
            "ready": False,
            "reason": "回放只检查候选前置证据；未在旧运行上伪造最终 PDF 或冷读回执。",
            "page_budget": page_budget_gate,
        },
        "knowledge_retrieval": {
            "status": retrieval.get("status"),
            "matched_cards": len(retrieval.get("matched_cards", [])),
            "visual_pattern_count": sum(
                len(card.get("visual_patterns", []))
                for card in retrieval.get("matched_cards", [])
                if isinstance(card, dict)
            ),
            "reason": retrieval.get("no_match_reason") or retrieval.get("unavailable_reason") or retrieval.get("reason"),
        },
    }
    atomic_json(run_dir / "replay-v34-closure.json", report)
    return report


def main() -> int:
    """解析旧运行列表，执行隔离回放并输出汇总路径。"""
    parser = argparse.ArgumentParser(description="回放 v3.4 论文资产闭环")
    parser.add_argument("run_dir", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, help="回放目录；默认使用临时目录")
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("knowledge/indexes/papers.json"),
        help="仓内论文卡索引",
    )
    args = parser.parse_args()
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="shumozizi-v34-replay-"))
    output.mkdir(parents=True, exist_ok=True)
    reports = [
        replay_run(path, output, index_path=args.index.resolve())
        for path in args.run_dir
    ]
    summary = output / "replay-summary.json"
    atomic_json(summary, {"reports": reports})
    print(json.dumps({"output": str(output), "summary": str(summary), "runs": reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
