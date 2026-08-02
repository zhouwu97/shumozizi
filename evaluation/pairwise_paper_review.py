"""生成匿名 A/B 论文盲评顺序，不访问论文内容或给出主观分数。"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path


def build_blinded_pair(left: Path, right: Path, output_dir: Path, seed: int) -> dict[str, object]:
    """随机化两个 PDF 的展示顺序并复制为匿名 A/B 文件。

    Args:
        left: 基线 PDF。
        right: 候选 PDF。
        output_dir: 匿名评审包输出目录。
        seed: 固定随机种子，供评测管理员复现映射。

    Returns:
        不含来源映射的 reviewer manifest。
    """
    if not left.is_file() or not right.is_file():
        raise FileNotFoundError("两个 PDF 都必须存在")
    ordered = [("baseline", left), ("candidate", right)]
    random.Random(seed).shuffle(ordered)
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = ("A", "B")
    administrator_mapping: dict[str, str] = {}
    for label, (source, path) in zip(labels, ordered, strict=True):
        shutil.copy2(path, output_dir / f"paper-{label}.pdf")
        administrator_mapping[label] = source
    mapping_path = output_dir.parent / f"{output_dir.name}.administrator-mapping.json"
    mapping_path.write_text(
        json.dumps({"seed": seed, "mapping": administrator_mapping}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "schema_version": "1.0",
        "papers": ["paper-A.pdf", "paper-B.pdf"],
        "required_independent_reviewers": 3,
        "blinding_rule": "Reviewer 不得接收来源映射、版本标签、工作流说明或前序评价。",
        "criteria": {
            "problem_structure": 15,
            "model_quality": 25,
            "result_competitiveness": 15,
            "insight_and_explanation": 15,
            "figure_persuasion": 10,
            "paper_logic_and_expression": 20,
        },
        "pairwise_questions": [
            "哪篇更像数学建模论文，而不是工作报告？",
            "哪篇主线更容易用一句话复述？",
            "哪篇中央推导更充分？",
            "哪篇图表对结论的解释力更强？",
            "哪篇前五页更快建立数据直觉与核心矛盾？",
            "哪篇的 AI 模板化句式和重复结构更少？",
        ],
        "reviewer_output": {
            "winner": "A、B 或 tie",
            "fatal_scientific_error": "若存在，定位页码并停止竞争力排名",
            "criterion_reasons": "每个问题给出页码与一句证据",
            "highest_value_revision": "只保留一项最值得修改的内容",
        },
        "fatal_error_rule": "致命科学错误不进入竞争力排名",
    }
    (output_dir / "reviewer-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    """解析命令行并创建匿名评审包。"""
    parser = argparse.ArgumentParser(description="创建匿名 A/B 论文盲评包")
    parser.add_argument("baseline_pdf", type=Path)
    parser.add_argument("candidate_pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(build_blinded_pair(args.baseline_pdf, args.candidate_pdf, args.output_dir, args.seed), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
