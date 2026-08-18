"""BZD 原版技能包加载器与提示词装配模块。

负责从 `vendor/bzd-math-modeling/<skill_name>` 加载真实原版的 `SKILL.md`
及其 `references/*.md`（包含近五年国赛评阅蒸馏模式库、赋分细则构建标准、策略输出口径等），
杜绝本地手写缩水版 Prompt。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_BZD_ROOT = REPO_ROOT / "vendor" / "bzd-math-modeling"


def load_bzd_skill(
    skill_name: str, required_references: list[str] | None = None
) -> dict[str, Any]:
    """读取指定 BZD 原版技能的 SKILL.md 与引用的 reference 文件内容。

    Args:
        skill_name: 技能目录名（如 ``bzd-problem-translator``, ``bzd-modeling-ideas``, ``bzd-review-paper``）。
        required_references: 需要显式加载的 reference 文件名列表；如果为 None，则加载 `references/` 下所有 `.md` 文件。

    Returns:
        包含 `skill_name`, `skill_md`, `references` (字典映射: ref_name -> text) 的字典。
    """
    skill_dir = VENDOR_BZD_ROOT / skill_name
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"BZD 原版技能目录不存在: {skill_dir}")

    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.is_file():
        raise FileNotFoundError(f"BZD 技能 SKILL.md 缺失: {skill_md_path}")

    skill_md = skill_md_path.read_text(encoding="utf-8")

    references: dict[str, str] = {}
    ref_dir = skill_dir / "references"
    if ref_dir.is_dir():
        if required_references is not None:
            target_files = [ref_dir / r for r in required_references]
        else:
            target_files = sorted(ref_dir.glob("*.md"))

        for ref_path in target_files:
            if ref_path.is_file():
                references[ref_path.name] = ref_path.read_text(encoding="utf-8")

    return {
        "skill_name": skill_name,
        "skill_dir": str(skill_dir),
        "skill_md": skill_md,
        "references": references,
    }


def format_bzd_prompt(
    skill_name: str,
    task_context: str,
    local_rules: str,
    required_references: list[str] | None = None,
) -> str:
    """装配包含原版技能、知识库 References、本地覆盖规则与隔离任务上下文的完整 Prompt。

    Args:
        skill_name: 技能名称。
        task_context: 隔离环境下的题面、附件与前置输入。
        local_rules: shumozizi 针对打擂、防泄漏、裁决等本地覆盖规则。
        required_references: 需要注入的 reference 列表。

    Returns:
        装配完成的提示词字符串。
    """
    bundle = load_bzd_skill(skill_name, required_references)

    sections = [
        f"【上游 BZD 原版 Skill: {skill_name}】\n{bundle['skill_md']}\n",
    ]

    if bundle["references"]:
        sections.append("【上游 Required References（国赛评阅蒸馏知识库与标准）】")
        for ref_name, ref_content in bundle["references"].items():
            sections.append(f"--- reference: {ref_name} ---\n{ref_content}\n")

    if local_rules.strip():
        sections.append(f"【shumozizi 本地覆盖规则（硬性执行约束）】\n{local_rules}\n")

    sections.append(f"【待求解/评阅任务输入】\n{task_context}")

    return "\n\n".join(sections)
