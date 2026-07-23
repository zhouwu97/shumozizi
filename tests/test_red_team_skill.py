"""防止独立红队 Skill 退化回模板或仅检查内部一致性。"""

from __future__ import annotations

from pathlib import Path


def test_red_team_skill_requires_clean_room_attacks_and_two_review_boundaries() -> None:
    """Skill 必须保留共模错误攻击菜单和新对话隔离约束。

    该测试不声称自动文本能完成科学审查；它只锁定给独立对话的最低工作指令。
    """
    skill = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "mathmodel-red-team"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    for required in (
        "全新的 Codex 对话",
        "不含质量标签",
        "有限线段与无限直线",
        "端点落入球体",
        "重叠重复计数",
        "至多",
        "量纲不一致",
        "信息泄漏",
        "proxy 与 exact 排序反转",
        "高维联合覆盖",
        "共享同一判定语义",
        "弱搜索区域",
        "paper-blind",
    ):
        assert required in skill
    assert "[TODO:" not in skill
