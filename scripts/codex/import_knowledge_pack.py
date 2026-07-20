"""兼容历史运行的旧 KNOWLEDGE_PACK 导入器；新运行不得依赖。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.repo_root import resolve_repo_root  # noqa: E402
from shumozizi.knowledge.authoring import write_argument_map, write_paper_blueprint  # noqa: E402
from shumozizi.knowledge.pack import bind_knowledge_pack  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="兼容导入旧 KNOWLEDGE_PACK（已废弃）")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--problem-source", type=Path)
    parser.add_argument("--questions-json", type=Path)
    parser.add_argument("--claims-json", type=Path)
    parser.add_argument("--repo-root")
    args = parser.parse_args()
    print(
        "警告：KNOWLEDGE_PACK 跨仓导入已废弃；新运行请使用仓内论文卡检索。",
        file=sys.stderr,
    )
    repo_root = Path(args.repo_root).resolve() if args.repo_root else resolve_repo_root()
    run_dir = args.run_dir.resolve()
    problem = args.problem_source.resolve() if args.problem_source else None
    lock = bind_knowledge_pack(repo_root, run_dir, args.pack.resolve(), problem_source=problem)
    questions = json.loads(args.questions_json.read_text(encoding="utf-8")) if args.questions_json else [{"question_id": "q1"}]
    claims = json.loads(args.claims_json.read_text(encoding="utf-8")) if args.claims_json else []
    blueprint = write_paper_blueprint(run_dir, questions)
    argument_map = write_argument_map(run_dir, claims)
    print(json.dumps({"pack": lock["knowledge_pack"], "paper_blueprint": str(blueprint), "argument_map": str(argument_map)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
