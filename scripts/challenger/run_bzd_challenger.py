"""BZD 独立 Challenger 桥接工具：隔离生成建模思路、选型比较与路线候选。

定位：独立二号解题专家（Challenger B/C），在完全隔离上下文运行，与主路线 A 统一打擂。
产物路径：analysis/external/bzd-route-candidates.md
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def build_isolated_challenger_prompt(run_dir: Path) -> str:
    """生成隔离上下文下的 BZD Modeling Ideas 提示词。

    【严格隔离要求】：
    只输入 problem/ 题面（及可选 bzd-problem-ledger.md）。
    严禁泄露当前主解法、代码、BASELINE_FREEZE、ROUTE_COMPETITION 或任何实验结果。
    """
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

    ledger_path = run_dir / "analysis" / "external" / "bzd-problem-ledger.md"
    ledger_context = ""
    if ledger_path.is_file():
        ledger_context = f"\n\n【题面逐句 Ledger 参考】\n{ledger_path.read_text(encoding='utf-8')[:8000]}"

    return f"""你现在作为独立的数学建模高级专家（BZD Modeling Ideas Challenger），在完全隔离的上下文中独立进行整题建模体系设计。

【独立性与隔离声明】
你未接触过任何已有的代码实现、预设路线或实验数值。请完全基于赛题本身，独立提出具备数学异构性与整篇连贯性的建模方案。

【待求解题面】
{joined_problem}{ledger_context}

【任务要求】
1. 建立整篇论文的共享建模骨干（backbone），杜绝各小问孤立拼凑模型。
2. 对每一个必答问题，提供至少 2~3 种具有实质数学结构差异的候选模型并进行详尽表格对比。
3. 明确说明主选模型、备选模型、接口数据流、失败风险与针对性验证实验。
4. 提出的所有路线必须能严格输出题目要求的正式目标，不得做静默目标替换（silent replacement）。

【输出目标文件】
请将完整的分析报告保存到：`analysis/external/bzd-route-candidates.md`

【必须包含的章节结构（按顺序）】
### 1. 整题建模主线
### 2. 跨问题联动链（Mermaid 流程图）
### 3. 全文统一建模口径
### 4. 分问题求解思路
#### 4.x.1 问题概述
#### 4.x.2 总体求解思路
#### 4.x.3 可用模型及选型比较
| 可行模型/思路 | 模型本质与核心变量 | 完整实现步骤 | 所需数据与假设 | 优点 | 局限与失败风险 | 验证方法 | 与前后问题的接口 | 适用场景 |
- 推荐模型：
- 选用理由：
- 备选模型：
- 多模型对比建议（公平打擂方案）：
#### 4.x.4 创新与改进方向
| 创新或改进方向 | 基础方案 | 具体改动与实现步骤 | 预期改进 | 新增工作量 | 验证指标与对照实验 | 风险及备用方案 | 影响的问题 |
"""


def validate_challenger_candidates(candidates_path: Path) -> tuple[bool, list[str]]:
    """验证 BZD Challenger 产物的结构完整性。"""
    if not candidates_path.is_file():
        return False, [f"文件不存在: {candidates_path}"]

    content = candidates_path.read_text(encoding="utf-8")
    issues: list[str] = []

    required_sections = [
        "1. 整题建模主线",
        "2. 跨问题联动链",
        "3. 全文统一建模口径",
        "4. 分问题求解思路",
    ]

    for section in required_sections:
        if section not in content:
            issues.append(f"缺失必要章节: {section}")

    if "可用模型及选型比较" not in content and "| 可行模型/思路 |" not in content:
        issues.append("缺失分问题模型选型比较表格")

    return len(issues) == 0, issues


def extract_challenger_routes(candidates_path: Path) -> list[dict[str, str]]:
    """从 Challenger 产物中提取各问候选路线摘要，用于汇入 ROUTE_COMPETITION.md。"""
    if not candidates_path.is_file():
        return []

    content = candidates_path.read_text(encoding="utf-8")
    routes: list[dict[str, str]] = []

    # 提取推荐模型条目
    for match in re.finditer(r"[-\*]\s*推荐模型[：:]\s*([^\n]+)", content):
        routes.append({"role": "challenger_primary", "model": match.group(1).strip()})
    for match in re.finditer(r"[-\*]\s*备选模型[：:]\s*([^\n]+)", content):
        routes.append({"role": "challenger_alternative", "model": match.group(1).strip()})

    return routes


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 BZD 独立 Challenger 提示词或验证路线产物")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    parser.add_argument("--validate", action="store_true", help="验证 analysis/external/bzd-route-candidates.md")
    parser.add_argument("--extract", action="store_true", help="提取候选路线摘要")
    args = parser.parse_args()

    candidates = args.run_dir / "analysis" / "external" / "bzd-route-candidates.md"

    if args.validate:
        valid, issues = validate_challenger_candidates(candidates)
        if valid:
            print(f"BZD Challenger 产物验证通过: {candidates}")
        else:
            print("BZD Challenger 产物验证未通过:\n" + "\n".join(f"- {i}" for i in issues))
            raise SystemExit(1)
    elif args.extract:
        routes = extract_challenger_routes(candidates)
        print(f"提取到 {len(routes)} 条候选路线:")
        for r in routes:
            print(f"  [{r['role']}] {r['model']}")
    else:
        prompt = build_isolated_challenger_prompt(args.run_dir)
        print(prompt)


if __name__ == "__main__":
    main()
