"""BZD 题意翻译桥接工具：加载原版 Skill、生成提示词、解析与 100% 逐句覆盖验证。

定位：主链分析前置辅助，确保题面 100% 句子覆盖，无遗漏约束与隐含建模信号。
产物路径：analysis/external/bzd-problem-ledger.md
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from scripts.challenger.bzd_skill_bundle import format_bzd_prompt


def slice_problem_into_sentence_units(problem_text: str) -> list[dict[str, str]]:
    """将题面文本拆解为带唯一编号的实体句子单元（substantive sentence units）。

    - 题干背景段落编号为 B01, B02, ...
    - 针对具体小问（问题1/一/Q1）拆解为 Q1-01, Q1-02, Q2-01, ...
    """
    units: list[dict[str, str]] = []
    lines = [line.strip() for line in problem_text.splitlines() if line.strip()]

    current_scope = "B"
    q_index = 0
    unit_counters: dict[str, int] = {"B": 0}

    for line in lines:
        if line.startswith("#"):
            # 检查是否切换到具体问题
            q_match = re.search(r"问题\s*([一二三四五1-5])|第\s*([一二三四五1-5])\s*问|Q([1-5])", line, re.IGNORECASE)
            if q_match:
                digit_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5"}
                raw_q = q_match.group(1) or q_match.group(2) or q_match.group(3)
                q_num = digit_map.get(raw_q, raw_q)
                current_scope = f"Q{q_num}"
                if current_scope not in unit_counters:
                    unit_counters[current_scope] = 0
            continue

        # 按中文/英文句号、分号、问号切分子句
        sentences = re.split(r"(?<=[。！？；\n])|(?<=[.!?])\s+", line)
        for s in sentences:
            s_clean = s.strip()
            # 过滤过短或非实体句子（如纯符号、表格分割线、markdown 标记）
            if len(s_clean) < 4 or s_clean.startswith("|") or s_clean.startswith("```"):
                continue

            unit_counters[current_scope] += 1
            idx = unit_counters[current_scope]
            unit_id = f"{current_scope}{idx:02d}" if current_scope == "B" else f"{current_scope}-{idx:02d}"
            units.append({
                "unit_id": unit_id,
                "scope": current_scope,
                "text": s_clean,
            })

    return units


def build_translator_prompt(run_dir: Path) -> str:
    """生成结合 BZD 原版技能与切分单元的题意翻译提示词。"""
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir():
        raise FileNotFoundError(f"问题目录不存在: {problem_dir}")

    problem_texts: list[str] = []
    for path in sorted(problem_dir.glob("*.md")) + sorted(problem_dir.glob("*.txt")):
        problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8')}")

    if not problem_texts:
        for path in sorted(problem_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json", ".csv"}:
                problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")

    joined_problem = "\n\n".join(problem_texts) if problem_texts else "【题面文件存放在 problem/ 目录下】"
    units = slice_problem_into_sentence_units(joined_problem)

    unit_manifest_lines = [
        "【题面预切分实体句子单元（编号必须 100% 完整保留在第 2 节表格第一列中）】",
    ]
    for u in units:
        unit_manifest_lines.append(f"- [{u['unit_id']}] {u['text']}")

    task_context = f"{joined_problem}\n\n" + "\n".join(unit_manifest_lines)

    local_rules = """1. 严格使用原版 BZD 逐句翻译与联动体系，从标题第一句开始，表格第一列的编号必须与预切分单元 ID（B01.., Q1-01..）一一精确匹配。
2. 严禁遗漏任何一个单元 ID（系统将执行 missing == 0 与 duplicate == 0 的机械硬校验）。
3. 严格区分题面原句（一级事实）、符号定义、推论解释与潜在歧义。
4. 输出目标文件固定为：`analysis/external/bzd-problem-ledger.md`。
5. 必须包含涵盖全部必答问题的跨问题 Mermaid 依赖流程图。"""

    return format_bzd_prompt(
        skill_name="bzd-problem-translator",
        task_context=task_context,
        local_rules=local_rules,
        required_references=[
            "sentence-interpretation-rules.md",
            "historical-review-signals.md",
            "md-output-standard.md",
        ],
    )


def validate_bzd_ledger(
    ledger_path: Path, problem_dir: Path | None = None
) -> tuple[bool, list[str]]:
    """验证 BZD 题意 Ledger 报告的结构完整性与 100% 句子单元覆盖率。"""
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

    # 提取表格中的全部单元 ID
    table_ids: list[str] = []
    for line in content.splitlines():
        if line.strip().startswith("|") and not line.strip().startswith("|---"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if cells:
                first_cell = cells[0]
                if re.match(r"^(B\d+|Q\d+-\d+)$", first_cell):
                    table_ids.append(first_cell)

    if not table_ids:
        # 也支持非严格正则的匹配
        extracted = re.findall(r"\b(B\d+|Q\d+-\d+)\b", content)
        table_ids = extracted

    # 若提供了题面目录，执行精准的 100% 句子覆盖比对
    target_problem_dir = problem_dir
    if target_problem_dir is None:
        # 尝试从 ledger_path 路径向上查找 problem/ 目录
        possible_problem = ledger_path.resolve().parents[2] / "problem"
        if possible_problem.is_dir():
            target_problem_dir = possible_problem

    if target_problem_dir and target_problem_dir.is_dir():
        problem_texts: list[str] = []
        for path in sorted(target_problem_dir.glob("*.md")) + sorted(target_problem_dir.glob("*.txt")):
            problem_texts.append(path.read_text(encoding="utf-8"))
        if problem_texts:
            units = slice_problem_into_sentence_units("\n".join(problem_texts))
            expected_ids = {u["unit_id"] for u in units}
            found_ids = set(table_ids)

            missing_ids = expected_ids - found_ids
            if missing_ids:
                issues.append(f"题面单元未 100% 覆盖，缺失以下 {len(missing_ids)} 个单元: {sorted(missing_ids)}")

    # 检查重复 ID
    duplicates = {i for i in table_ids if table_ids.count(i) > 1}
    if duplicates:
        issues.append(f"第2节逐句翻译表存在重复单元 ID: {sorted(duplicates)}")

    return len(issues) == 0, issues


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 BZD 题意翻译提示词或验证 Ledger 产物")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    parser.add_argument("--validate", action="store_true", help="验证 analysis/external/bzd-problem-ledger.md")
    args = parser.parse_args()

    if args.validate:
        ledger = args.run_dir / "analysis" / "external" / "bzd-problem-ledger.md"
        valid, issues = validate_bzd_ledger(ledger, args.run_dir / "problem")
        if valid:
            print(f"BZD Problem Ledger 验证通过 (100% 句子覆盖): {ledger}")
        else:
            print("BZD Problem Ledger 验证未通过:\n" + "\n".join(f"- {i}" for i in issues))
            raise SystemExit(1)
    else:
        prompt = build_translator_prompt(args.run_dir)
        print(prompt)


if __name__ == "__main__":
    main()
