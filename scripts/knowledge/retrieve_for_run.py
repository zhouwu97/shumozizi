"""为 v3.2 运行执行分析检索或生成写作迁移判断模板。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.knowledge.retrieval import (
    require_analysis_knowledge_retrieval,
    require_paper_knowledge_application,
    write_analysis_knowledge_retrieval,
    write_paper_knowledge_application,
)


def _analysis(args: argparse.Namespace) -> Path:
    """执行分析阶段检索，显式判断可由 decisions 文件补入。"""
    fingerprint_path = args.input or args.run_dir / "knowledge" / "TASK_FINGERPRINT.json"
    fingerprint = load_json(fingerprint_path)
    decisions = load_json(args.decisions) if args.decisions else None
    path = write_analysis_knowledge_retrieval(
        args.run_dir,
        args.index,
        fingerprint,
        decisions=decisions,
        unavailable_reason=args.unavailable_reason,
    )
    if decisions is not None or args.unavailable_reason is not None:
        require_analysis_knowledge_retrieval(args.run_dir)
    return path


def _paper(args: argparse.Namespace) -> Path:
    """首次调用生成模板，再次调用复验人工填写结果。"""
    path = args.run_dir / "paper" / "KNOWLEDGE_APPLICATION.md"
    existed = path.is_file()
    output = write_paper_knowledge_application(args.run_dir, overwrite=args.force)
    if existed and not args.force:
        require_paper_knowledge_application(args.run_dir)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="消费仓内论文卡并记录采用或拒绝判断")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--stage", choices=("analysis", "paper"), required=True)
    parser.add_argument("--input", type=Path, help="分析阶段任务指纹 JSON")
    parser.add_argument(
        "--index", type=Path, default=Path("knowledge/indexes/papers.json")
    )
    parser.add_argument("--decisions", type=Path, help="采用/拒绝判断 JSON")
    parser.add_argument("--unavailable-reason")
    parser.add_argument("--force", action="store_true", help="重新生成写作迁移模板")
    args = parser.parse_args()
    try:
        output = _analysis(args) if args.stage == "analysis" else _paper(args)
    except ContractError as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
