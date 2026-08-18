"""BZD 题意翻译桥接工具：生成提示词、解析与验证题面逐句 Ledger。

定位：主链分析前置辅助，确保题面 100% 句子覆盖，无遗漏约束与隐含建模信号。
产物路径：analysis/external/bzd-problem-ledger.md
"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_translator_prompt(run_dir: Path) -> str:
    """生成 BZD 题意翻译提示词。

    输入仅包含 run_dir 下的 problem/ 目录内容与 vendor 参考规则。
    """
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir():
        raise FileNotFoundError(f"问题目录不存在: {problem_dir}")

    problem_texts = []
    for path in sorted(problem_dir.glob("*.md")) + sorted(problem_dir.glob("*.txt")):
        problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8')}")

    if not problem_texts:
        # 尝试查找任何题面文本
        for path in sorted(problem_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json"}:
                problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")

    joined_problem = "\n\n".join(problem_texts) if problem_texts else "【题面文件存放在 problem/ 目录下】"

    return f"""你现在作为严谨的数学建模题意翻译专家（BZD Problem Translator），对以下赛题进行逐句精确建模翻译与联动分析。

【核心原则】
1. 从题目标题开始，每个实体句子（substantive sentence）恰好覆盖一次，绝不省略任何一句话。
2. 区分题面硬事实（source_fact）、符号定义（source_definition）、建模推论（bzd_interpretation）与潜在歧义（ambiguity）。
3. 提取所有明示条件、隐含建模信号、前后问依赖、漏读后果、后文必须给出的证据。
4. 必须输出包含全部问的跨问题 Mermaid 依赖流程图（flowchart TD/LR）。

【待分析题面】
{joined_problem}

【输出目标文件】
请将完整的分析报告保存到：`analysis/external/bzd-problem-ledger.md`

【必须包含的章节结构（按顺序）】
### 1. 整题概览
### 2. 逐句题意翻译与联动表
| 编号 | 题干原句 | 通俗而精确的翻译 | 明示条件/数据 | 隐含建模信号 | 与前后内容的联动 | 漏读后果 | 后文必须出现的证据 |
### 3. 核心术语与口径表
### 4. 各问输入—任务—输出表
| 问题 | 直接输入 | 需要解决的任务 | 必须满足的约束 | 最终输出 | 依赖前问内容 | 将被后问复用的内容 |
### 5. 跨问题联动链（必须为合法 Mermaid 流程图，涵盖所有问题节点）
### 6. 最容易漏读或误解的句子（5-12条核心避坑点）
### 7. 完整性核验
"""


def validate_bzd_ledger(ledger_path: Path) -> tuple[bool, list[str]]:
    """验证 BZD 题意 Ledger 报告的结构完整性。"""
    if not ledger_path.is_file():
        return False, [f"文件不存在: {ledger_path}"]

    content = ledger_path.read_text(encoding="utf-8")
    issues: list[str] = []

    required_sections = [
        "1. 整题概览",
        "2. 逐句题意翻译与联动表",
        "3. 核心术语与口径表",
        "4. 各问输入—任务—输出表",
        "5. 跨问题联动链",
        "6. 最容易漏读或误解的句子",
        "7. 完整性核验",
    ]

    for section in required_sections:
        if section not in content:
            issues.append(f"缺失必要章节: {section}")

    if "```mermaid" not in content and "flowchart" not in content:
        issues.append("缺失第5节 Mermaid 跨问联动图")

    if "| 编号 | 题干原句 |" not in content and "| 编号 |" not in content:
        issues.append("第2节缺失逐句翻译表格")

    return len(issues) == 0, issues


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 BZD 题意翻译提示词或验证 Ledger 产物")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    parser.add_argument("--validate", action="store_true", help="验证 analysis/external/bzd-problem-ledger.md")
    args = parser.parse_args()

    if args.validate:
        ledger = args.run_dir / "analysis" / "external" / "bzd-problem-ledger.md"
        valid, issues = validate_bzd_ledger(ledger)
        if valid:
            print(f"BZD Problem Ledger 验证通过: {ledger}")
        else:
            print("BZD Problem Ledger 验证未通过:\n" + "\n".join(f"- {i}" for i in issues))
            raise SystemExit(1)
    else:
        prompt = build_translator_prompt(args.run_dir)
        print(prompt)


if __name__ == "__main__":
    main()
