"""BZD 独立解题大脑 (Solver B) 准备工具。

作用：
1. 准备物理隔离的赛题与附件输入包 (analysis/dual_solver/solver_b_packet/) 与工作区 (analysis/dual_solver/solver_b/)；
2. 完整装配上游原版 BZD Modeling Ideas 与 References 知识库；
3. 一键生成 Solver B 独立全题解题提示词，用于在新对话 B 中独立完成整题建模与计算。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from scripts.challenger.bzd_skill_bundle import format_bzd_prompt


def prepare_solver_b_packet(run_dir: Path) -> Path:
    """构建 Solver B 独立赛题与附件包，清空旧目录，确保绝不包含 Solver A 的任何解题信息。"""
    packet_dir = run_dir / "analysis" / "dual_solver" / "solver_b_packet"
    if packet_dir.exists():
        shutil.rmtree(packet_dir, ignore_errors=True)

    packet_problem_dir = packet_dir / "problem"
    packet_problem_dir.mkdir(parents=True, exist_ok=True)

    # 同时创建 Solver B 结果归档目录
    solver_b_dir = run_dir / "analysis" / "dual_solver" / "solver_b"
    (solver_b_dir / "code").mkdir(parents=True, exist_ok=True)
    (solver_b_dir / "results").mkdir(parents=True, exist_ok=True)

    src_problem_dir = run_dir / "problem"
    manifest_lines = [
        "# Solver B 隔离题面清单 (Problem Manifest)",
        "",
        "| 文件路径 | 类型 | 大小 (Bytes) | SHA-256 (前12位) |",
        "|---|---|---|---|",
    ]

    if src_problem_dir.is_dir():
        for src_file in sorted(src_problem_dir.rglob("*")):
            if src_file.is_file():
                rel_path = src_file.relative_to(src_problem_dir)
                dest_file = packet_problem_dir / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)

                content_bytes = src_file.read_bytes()
                sha_prefix = hashlib.sha256(content_bytes).hexdigest()[:12]
                file_type = src_file.suffix.lower() or "file"
                manifest_lines.append(
                    f"| `problem/{rel_path.as_posix()}` | {file_type} | {len(content_bytes)} | `{sha_prefix}` |"
                )

    (packet_dir / "INPUT_MANIFEST.md").write_text("\n".join(manifest_lines), encoding="utf-8")
    return packet_dir


def build_solver_b_prompt(run_dir: Path) -> str:
    """生成用于独立新对话 B (Solver B - BZD) 的完整解题提示词。"""
    packet_dir = prepare_solver_b_packet(run_dir)
    packet_problem_dir = packet_dir / "problem"

    problem_texts: list[str] = []
    attachment_summaries: list[str] = []

    for path in sorted(packet_problem_dir.rglob("*")):
        if path.is_file():
            suffix = path.suffix.lower()
            rel_name = path.relative_to(packet_problem_dir).as_posix()
            if suffix in {".md", ".txt", ".json"}:
                problem_texts.append(f"=== {rel_name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")
            elif suffix in {".csv", ".tsv"}:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                preview = "\n".join(lines[:15])
                attachment_summaries.append(
                    f"=== [CSV数据附件] {rel_name} (共 {len(lines)} 行) ===\n{preview}\n..."
                )
            elif suffix in {".xlsx", ".xls"}:
                attachment_summaries.append(
                    f"=== [Excel数据附件] {rel_name} ({path.stat().st_size} bytes) ===\n（请使用 Python/pandas 读取其全部 sheet 结构与字段分布）"
                )
            elif suffix in {".pdf"}:
                attachment_summaries.append(
                    f"=== [PDF题面/附件] {rel_name} ({path.stat().st_size} bytes) ===\n（请深入阅读其全部章节、图表与附注）"
                )
            else:
                attachment_summaries.append(
                    f"=== [附件文件] {rel_name} ({path.stat().st_size} bytes) ==="
                )

    joined_problem = "\n\n".join(problem_texts) if problem_texts else "【题面文件存放在 problem/ 目录下】"
    if attachment_summaries:
        joined_problem += "\n\n【附件概览与前置数据】\n" + "\n\n".join(attachment_summaries)

    task_context = f"{joined_problem}"

    local_rules = """你现在作为独立的数学建模解题专家 (Solver B - BZD)。

【解题要求】：
1. 独立完成整题建模，不参考任何已有外部方案。
2. 建立整篇论文的统一共享建模骨干（backbone），并逐问给出模型选型理由（对比更简单 baseline）、数学变量与目标形式化定义、约束物理意义展开。
3. 提供完整的求解算法设计、Python 实现代码（或关键计算步骤）与数值验证结果。
4. 若附件包含 Excel/PDF/CSV/图片，必须直接检视具体数据字段与真实特征，禁止凭空猜测。
5. 明确指出方案的局限性、可能崩塌的边界条件与建议的多模型对比实验。

【成果归档要求】：
请将你的本次完整解题对话、关键代码与计算结果保存至：
- **完整解题与对话记录**：`analysis/dual_solver/solver_b/TRANSCRIPT.md`（或 `SOLUTION_B.md`）
- **核心算法与仿真代码**：`analysis/dual_solver/solver_b/code/`
- **计算与指标数据文件**：`analysis/dual_solver/solver_b/results/`"""

    return format_bzd_prompt(
        skill_name="bzd-modeling-ideas",
        task_context=task_context,
        local_rules=local_rules,
        required_references=[
            "integrated-modeling-patterns.md",
            "strategy-output-standard.md",
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Solver B (BZD 独立解题) 提示词或构建隔离包")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    parser.add_argument("--prepare-packet-only", action="store_true", help="仅生成隔离输入包")
    args = parser.parse_args()

    if args.prepare_packet_only:
        packet = prepare_solver_b_packet(args.run_dir)
        print(f"Solver B 隔离输入包已就绪: {packet}")
    else:
        prompt = build_solver_b_prompt(args.run_dir)
        print(prompt)


if __name__ == "__main__":
    main()
