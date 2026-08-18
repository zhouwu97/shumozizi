"""BZD 外部评委两阶段提示词生成器。

定位：模拟国赛评委视角，执行两阶段审查（阶段一：基于题面预冻结评分细则；阶段二：依据冻结细则攻击论文）。
"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_rubric_prompt(run_dir: Path) -> str:
    """阶段一提示词：仅读题面，独立推导并预冻结本题 100 分评分细则。"""
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir():
        raise FileNotFoundError(f"问题目录不存在: {problem_dir}")

    problem_texts = []
    for path in sorted(problem_dir.glob("*.md")) + sorted(problem_dir.glob("*.txt")):
        problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8')}")

    if not problem_texts:
        for path in sorted(problem_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json"}:
                problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")

    joined_problem = "\n\n".join(problem_texts) if problem_texts else "【题面文件存放在 problem/ 目录下】"

    return f"""你现在作为全国大学生数学建模竞赛（CUMCM）资深评审专家（BZD Review Judge - 阶段一）。

【任务目标】
在未阅读参赛论文前，仅依据赛题题面，独立构建一份详尽、客观的 100 分制评阅细则与赋分点分布。

【赛题内容】
{joined_problem}

【赋分标准分布要求】
1. 摘要：固定 10 分（核心要素齐全、结论数据明确、行文精炼、非工作汇报）
2. 格式规范与排版：固定 10 分（论文结构、图表清晰、公式规范、引用与附录）
3. 模型建立与求解：70-75 分（按各小问难度与任务量合理切分：问题分析、假设合理性、模型推导、算法求解、结果呈现）
4. 补充质量（检验/敏感性/创新点）：5-10 分

【输出要求】
请将评分细则输出为 JSON 格式，保存至：`review/external/bzd-frozen-rubric.json`
结构包含：
- `total_points`: 100
- `sections`: 各部分名称、满分权重、关键踩分点与扣分判定标准
"""


def build_judge_prompt(run_dir: Path, pdf_path: Path | None = None) -> str:
    """阶段二提示词：读取冻结评分细则与待评阅论文 PDF，输出评委评审报告。"""
    rubric_file = run_dir / "review" / "external" / "bzd-frozen-rubric.json"
    rubric_context = ""
    if rubric_file.is_file():
        rubric_context = f"\n\n【预冻结评分细则 (Frozen Rubric)】\n{rubric_file.read_text(encoding='utf-8')}"

    pdf_target = pdf_path or (run_dir / "paper" / "paper.pdf")

    return f"""你现在作为全国大学生数学建模竞赛（CUMCM）资深评审专家（BZD Review Judge - 阶段二）。

【待评阅论文】
PDF 路径: `{pdf_target}`{rubric_context}

【评审要求】
1. 严格对照预冻结的评分细则进行逐项核验与攻击。
2. 检查：任务覆盖度、数学严谨性、物理单位、算法真实性、数值前后一致性、敏感性分析与图表三步论证。
3. 找出所有实质缺陷（严重缺陷 P0、重要缺陷 P1、一般缺陷 P2），指明具体页码、章节和修改建议。

【输出目标】
请生成完整的评审报告，保存至：`review/external/bzd-review.md`（可同时输出 HTML 报告）。

【报告必须包含】
1. 总体评价与打分表（按细则逐项给出得分、扣分点与具体位置）
2. 本题任务覆盖核验（未完成/不完整任务清单）
3. 评委式主要缺陷与扣分依据（按 P0/P1/P2 标注）
4. 优先修改建议（按收益排序）
"""


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
