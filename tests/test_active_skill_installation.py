"""验证仓库主动 Skill 可被 Codex 正常发现和调用。"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_every_active_skill_has_valid_frontmatter_and_openai_interface() -> None:
    """每个主动入口都必须具有稳定名称、触发描述和显式默认调用提示。"""
    skills_root = REPO_ROOT / ".agents/skills"
    skills = sorted(path for path in skills_root.iterdir() if path.is_dir())
    assert len(skills) == 13

    for skill in skills:
        content = (skill / "SKILL.md").read_text(encoding="utf-8")
        assert content.startswith("---\n"), skill.name
        _, frontmatter_text, _ = content.split("---", maxsplit=2)
        frontmatter = yaml.safe_load(frontmatter_text)
        assert frontmatter["name"] == skill.name
        assert len(frontmatter["description"].strip()) >= 20

        interface_path = skill / "agents/openai.yaml"
        interface = yaml.safe_load(interface_path.read_text(encoding="utf-8"))["interface"]
        assert interface["display_name"].strip()
        assert interface["short_description"].strip()
        assert f"${skill.name}" in interface["default_prompt"]


def test_workflow_routes_problem_families_to_imported_skills() -> None:
    """完整工作流必须把题型映射到新增能力，而非只把 Skill 复制进目录。"""
    router_root = REPO_ROOT / ".agents/skills/mathmodel-capability-router"
    router_text = (router_root / "SKILL.md").read_text(encoding="utf-8")
    workflow_text = (
        REPO_ROOT / ".agents/skills/mathmodel-workflow/SKILL.md"
    ).read_text(encoding="utf-8")
    routing = yaml.safe_load(
        (router_root / "references/skill-routing.yaml").read_text(encoding="utf-8")
    )

    assert routing["schema_version"] == "1.0"
    assert routing["routes"] == {
        "geometry_kinematics": [
            {
                "skill": "mathmodel-geometry-oracle",
                "phase": "experiment",
                "condition": "always",
            },
            {
                "skill": "mathmodel-geometry-visual",
                "phase": "visualization",
                "condition": "spatial_structure_affects_conclusion",
            },
            {
                "skill": "mathmodel-matlab",
                "phase": "experiment",
                "condition": "high_risk_geometry_and_matlab_available",
            },
        ],
        "optimization": [
            {
                "skill": "mathmodel-optimizer-benchmark",
                "phase": "experiment",
                "condition": "always",
            },
            {
                "skill": "mathmodel-matlab",
                "phase": "experiment",
                "condition": "independent_optimization_challenge_and_matlab_available",
            },
        ],
    }
    assert "按题型选择并调用匹配的主动 Skill" in workflow_text
    assert "`create_thread`" in workflow_text
    assert "`wait_threads`" in workflow_text
    assert "不得用 `fork_thread`" in workflow_text
    assert "真实 `threadId`" in workflow_text
    for route in routing["routes"].values():
        for item in route:
            assert f"${item['skill']}" in router_text


def test_vendor_sources_are_pinned_and_do_not_expose_external_workflows() -> None:
    """vendor 只保存选定资产和来源收据，不应导入外部总控入口。"""
    expected = {
        "nature-skills": {"nature-figure"},
        "scientific-agent-skills": {"pymoo", "sympy", "scientific-visualization"},
        "nature-paper-skills": {
            "figure-planner",
            "manuscript-optimizer",
            "stats-reporting-audit",
        },
        "math-modeling-skills": {"solver-references", "paper-references"},
    }
    for source_name, imported in expected.items():
        source_root = REPO_ROOT / "vendor" / source_name
        receipt = yaml.safe_load((source_root / "SOURCE.json").read_text(encoding="utf-8"))
        assert len(receipt["commit"]) == 40
        assert receipt["repository"].startswith("https://github.com/")
        assert receipt["local_modifications"] == []
        directories = {path.name for path in source_root.iterdir() if path.is_dir()}
        assert directories == imported
    assert not list((REPO_ROOT / "vendor").rglob(".git"))
    assert not list((REPO_ROOT / "vendor").rglob("paper-workflow"))
