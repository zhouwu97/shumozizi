"""用历史运行回放 v3.4 Author Pass，验证事实稳定与表达可竞争。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.core.io import atomic_json, sha256_file  # noqa: E402
from shumozizi.paper.author_pass import prepare_longform_author  # noqa: E402
from shumozizi.paper.narrative_competition import (  # noqa: E402
    select_narrative_candidate,
    write_narrative_candidates,
)

SCIENCE_FILES = (
    Path("results/index.json"),
    Path("paper/answer-map.json"),
    Path("paper/claim_gate.json"),
)
REPLAY_FILES = (
    Path("state/run.json"),
    *SCIENCE_FILES,
    Path("paper/generated/material_pool.json"),
    Path("figures/index.json"),
)
LEGACY_WRITER_FILES = (
    "WRITER_BRIEF.md",
    "PAPER_BLUEPRINT.md",
    "ANSWER_AND_CLAIMS.md",
    "MATERIAL_POOL.md",
    "FIGURE_CATALOG.md",
    "CITATION_PACKET.md",
    "answer-and-claims.json",
)


def _copy_replay_inputs(source: Path, target: Path) -> None:
    """只复制 Author Pass 所需事实，避免复制完整 169 MB 历史运行。"""
    for relative in REPLAY_FILES:
        current = source / relative
        if not current.is_file():
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current, destination)


def _digests(run_dir: Path) -> dict[str, str]:
    """计算科学事实文件摘要。"""
    return {
        relative.as_posix(): sha256_file(run_dir / relative)
        for relative in SCIENCE_FILES
        if (run_dir / relative).is_file()
    }


def replay_authoring(source_run: Path) -> dict[str, Any]:
    """回放 Author Pass 并返回事实稳定与表达竞争指标。

    Args:
        source_run: 历史运行目录，函数只读该目录。

    Returns:
        可序列化的回放报告。
    """
    source = source_run.resolve()
    try:
        source_label = source.relative_to(ROOT).as_posix()
    except ValueError:
        source_label = source.as_posix()
    before = _digests(source)
    baseline_pdf = source / "paper/cold-reader-draft-2.pdf"
    # 历史目录可能已被新版本重建 handoff；基线应绑定旧协议本身，而不是可变产物。
    previous_writer_count = len(LEGACY_WRITER_FILES)

    with tempfile.TemporaryDirectory(prefix="shumozizi-debureaucracy-") as temporary:
        replay = Path(temporary) / source.name
        _copy_replay_inputs(source, replay)
        manifest = prepare_longform_author(replay, require_template=False)
        candidates = write_narrative_candidates(
            replay,
            [
                {
                    "candidate_id": "question-progression",
                    "title": "问题递进型",
                    "central_thread": "从单日安排递进到共享截止与月度身份排班。",
                    "section_flow": ["数据直觉", "共享容量模型", "逐问新增约束", "统一检验"],
                    "memorable_takeaway": "三问是同一容量网络逐层增加耦合。",
                    "risks": ["共享推导可能分散"],
                },
                {
                    "candidate_id": "active-bound",
                    "title": "活跃下界机制型",
                    "central_thread": "从需求峰值追踪到活跃下界和可行构造。",
                    "section_flow": ["峰值现象", "下界判据", "联合构造", "跨日冗余"],
                    "memorable_takeaway": "581 人由峰值日下界锁定，并由构造达到。",
                    "risks": ["需要保留 Q1/Q2 直接答案索引"],
                },
            ],
        )
        selected = select_narrative_candidate(
            replay,
            "active-bound",
            reviewer_context_id="historical-replay-fresh-reader",
            selection_reason="机制主线更快解释核心数字，同时不改变逐问正式结果。",
            revision_advice="在前五页保留三问答案总览。",
        )
        after = _digests(replay)
        author_files = [
            manifest["research_package"]["path"],
            manifest["author_brief"]["path"],
        ]
        flows = [tuple(item["section_flow"]) for item in candidates["candidates"]]

    return {
        "schema_name": "debureaucracy_historical_replay",
        "schema_version": "1.0",
        "source_run": source_label,
        "baseline_pdf_pages": len(PdfReader(str(baseline_pdf)).pages),
        "science_digests_before": before,
        "science_digests_after": after,
        "science_facts_stable": before == after,
        "previous_writer_facing_count": previous_writer_count,
        "previous_writer_facing_source": "legacy_writer_handoff_protocol",
        "author_facing_files": author_files,
        "author_facing_count": len(author_files),
        "control_file_reduction_at_least_half": (
            previous_writer_count > 0 and len(author_files) * 2 <= previous_writer_count
        ),
        "narrative_candidate_count": len(candidates["candidates"]),
        "distinct_narrative_flows": len(flows) == len(set(flows)),
        "selected_narrative": selected["selected_candidate_id"],
    }


def main() -> int:
    """执行历史回放并可选写入 JSON 报告。"""
    parser = argparse.ArgumentParser(description="v3.4 减负历史 Author Pass 回放")
    parser.add_argument("source_run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = replay_authoring(args.source_run)
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
