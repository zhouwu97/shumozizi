"""BZD 外部评委两阶段提示词生成器。

定位：模拟国赛评委视角，执行两阶段审查：
- 阶段一：基于完整题面独立构建并预冻结 100 分制评分细则 (`review/external/bzd-frozen-rubric.json`)；
- 阶段二：依据完整题面、预冻结细则与冻结 PDF 联合攻击论文 (`review/external/bzd-review.md`)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.challenger.bzd_skill_bundle import format_bzd_prompt


def _load_problem_text_and_attachments(run_dir: Path) -> str:
    """读取问题目录下的全部题面与附件描述。"""
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir():
        return "【题面目录不存在】"

    problem_texts: list[str] = []
    attachment_summaries: list[str] = []

    for path in sorted(problem_dir.rglob("*")):
        if path.is_file():
            suffix = path.suffix.lower()
            rel_name = path.relative_to(problem_dir).as_posix()
            if suffix in {".md", ".txt", ".json"}:
                problem_texts.append(f"=== {rel_name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")
            elif suffix in {".csv", ".tsv"}:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                attachment_summaries.append(f"=== [CSV附件] {rel_name} ({len(lines)} 行) ===")
            else:
                attachment_summaries.append(f"=== [附件文件] {rel_name} ({path.stat().st_size} bytes) ===")

    full_text = "\n\n".join(problem_texts)
    if attachment_summaries:
        full_text += "\n\n【附件列表】\n" + "\n".join(attachment_summaries)
    return full_text


def build_rubric_prompt(run_dir: Path) -> str:
    """阶段一提示词：仅读题面与附件，依据 BZD 评阅蒸馏标准独立推导并预冻结 100 分评分细则。"""
    problem_text = _load_problem_text_and_attachments(run_dir)

    task_context = f"{problem_text}"

    local_rules = """1. 此时绝未阅读参赛论文，仅依据赛题本身独立推导详尽的 100 分制评阅细则与赋分点分布。
2. 赋分分布：摘要 10 分，格式与排版 10 分，模型建立与求解 70-75 分（按各问难度分配），检验与敏感性 5-10 分。
3. 输出文件必须保存至：`review/external/bzd-frozen-rubric.json`。
4. JSON 结构需包含 `total_points`: 100 与 `sections`（各部分名称、分值、踩分点与扣分标准）。"""

    return format_bzd_prompt(
        skill_name="bzd-review-paper",
        task_context=task_context,
        local_rules=local_rules,
        required_references=[
            "rubric-construction.md",
            "rubric.md",
        ],
    )


def build_judge_prompt(run_dir: Path, pdf_path: Path | None = None) -> str:
    """阶段二提示词：读取完整题面、预冻结评分细则与待评阅论文 PDF，输出评委评审报告。"""
    problem_text = _load_problem_text_and_attachments(run_dir)
    rubric_file = run_dir / "review" / "external" / "bzd-frozen-rubric.json"
    rubric_context = ""
    if rubric_file.is_file():
        rubric_context = f"\n\n【预冻结评分细则 (Frozen Rubric)】\n{rubric_file.read_text(encoding='utf-8')}"

    pdf_target = pdf_path or (run_dir / "paper" / "paper.pdf")

    task_context = f"【原始赛题与附件】\n{problem_text}{rubric_context}\n\n【待评阅论文 PDF 路径】\n`{pdf_target}`"

    local_rules = """1. 严格依据原始赛题与阶段一已预冻结的评分细则进行逐项核验与攻击，禁止因论文表现事后修改评分标准。
2. 全面检查：任务覆盖度、数学严谨性、物理单位一致性、算法真实性、数值前后一致性、敏感性分析与图表三步论证。
3. 标出所有实质缺陷（严重缺陷 P0、重要缺陷 P1、一般缺陷 P2），指明具体页码、章节和修改建议。
4. 输出目标文件：`review/external/bzd-review.md`。
5. 报告必须包含：总体评价、逐问任务覆盖核验清单、主要缺陷与扣分依据（按 P0/P1/P2 标明）、优先修改建议。"""

    return format_bzd_prompt(
        skill_name="bzd-review-paper",
        task_context=task_context,
        local_rules=local_rules,
        required_references=[
            "cross-case-patterns.md",
            "formatting-standard.md",
            "title-abstract-keywords.md",
            "rubric.md",
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 BZD 外部评委提示词")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    parser.add_argument("--stage", choices=["rubric", "judge"], default="judge", help="评审阶段")
    parser.add_argument("--pdf", type=Path, default=None, help="待评阅 PDF 路径")
    args = parser.parse_args()

    if args.stage == "rubric":
        print(build_rubric_prompt(args.run_dir))
    else:
        print(build_judge_prompt(args.run_dir, args.pdf))


if __name__ == "__main__":
    main()
