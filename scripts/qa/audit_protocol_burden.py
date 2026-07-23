"""量化主动 Skill 的协议认知负担，并确认防伪检查仍由运行时承担。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from shumozizi.paper.compiler import verify_paper_compile_receipt
from shumozizi.simple.capabilities import require_knowledge_consumption
from shumozizi.simple.review import run_red_team_evidence
from shumozizi.simple.visualization import run_figure_render

ACTIVE_SKILLS = {
    "workflow": Path(".agents/skills/mathmodel-workflow/SKILL.md"),
    "capability_router": Path(".agents/skills/mathmodel-capability-router/SKILL.md"),
    "solve": Path(".agents/skills/mathmodel-solve/SKILL.md"),
    "experiment": Path(".agents/skills/mathmodel-experiment/SKILL.md"),
    "visual": Path(".agents/skills/mathmodel-visual/SKILL.md"),
    "paper": Path(".agents/skills/mathmodel-paper/SKILL.md"),
    "final_check": Path(".agents/skills/mathmodel-final-check/SKILL.md"),
    "red_team": Path(".agents/skills/mathmodel-red-team/SKILL.md"),
    "writing": Path("skills/5writing/SKILL.md"),
}
PROTOCOL_TERMS = (
    "adapter",
    r"source[- ]closure",
    "provenance",
    "coverage",
    "registry",
    "challenge",
    r"marginal[- ]gain",
)
PROTOCOL_EXPLANATION_TERMS = PROTOCOL_TERMS + (
    "哈希",
    "收据",
    "冻结",
    "审查包",
    r"review/packet",
    "回执",
    "状态机",
)
MATH_FOCUS_TERMS = (
    "题目",
    "数学",
    "模型",
    "推导",
    "变量",
    "单位",
    "约束",
    "目标",
    "假设",
    "结构",
    "路线",
    "求解",
    "实验",
    "结果",
    "验证",
    "几何",
    "优化",
    "数据",
    "oracle",
    "baseline",
    "probe",
)
MAIN_DIALOGUE_DECISIONS = (
    "problem_families",
    "capabilities",
    "verification_capability",
    "toolchain",
    "knowledge_assets",
)
CONDITIONAL_DIALOGUE_DECISION = "visual_evidence"
ROUTE_RUNTIME_FIELDS = (
    "run_id",
    "status",
    "created_at",
    "tooling_sha256",
    "toolchain.requirement_receipts",
    "knowledge_assets[].sha256",
)
KNOWLEDGE_RUNTIME_FIELDS = (
    "route_sha256",
    "reader",
    "assets[].sha256",
    "assets[].bytes_read",
    "consumed_at",
)
FIGURE_RUNTIME_FIELDS = (
    "render command",
    "script/input/output hashes",
    "stdout/stderr evidence",
    "render receipt hash",
)
PAPER_RUNTIME_FIELDS = (
    "compiler executions",
    "template/source/PDF hashes",
    "compile receipt",
)


def _body_lines(path: Path) -> list[str]:
    """读取 Skill 正文行，排除 frontmatter 以免元数据污染篇幅统计。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines[:1] == ["---"]:
        try:
            closing = lines.index("---", 1)
        except ValueError:
            return lines
        lines = lines[closing + 1 :]
    return [line for line in lines if line.strip()]


def _count_hits(line: str, terms: tuple[str, ...]) -> int:
    """统计一行中术语的出现次数，支持短语的空格/连字符变体。"""
    return sum(len(re.findall(term, line, flags=re.IGNORECASE)) for term in terms)


def _skill_metrics(path: Path) -> dict[str, Any]:
    """生成单个主动 Skill 的协议与数学关注度量。"""
    lines = _body_lines(path)
    protocol_lines = [line for line in lines if _count_hits(line, PROTOCOL_TERMS)]
    protocol_explanation_lines = [
        line for line in lines if _count_hits(line, PROTOCOL_EXPLANATION_TERMS)
    ]
    math_lines = [line for line in lines if _count_hits(line, MATH_FOCUS_TERMS)]
    return {
        "path": path.as_posix(),
        "nonempty_lines": len(lines),
        "protocol_lines": len(protocol_lines),
        "protocol_hits": sum(_count_hits(line, PROTOCOL_TERMS) for line in lines),
        "protocol_explanation_lines": len(protocol_explanation_lines),
        "protocol_explanation_hits": sum(
            _count_hits(line, PROTOCOL_EXPLANATION_TERMS) for line in lines
        ),
        "math_focus_lines": len(math_lines),
        "math_focus_hits": sum(_count_hits(line, MATH_FOCUS_TERMS) for line in lines),
    }


def _runtime_guards() -> list[dict[str, Any]]:
    """确认收据和独立审查仍有真实执行入口，而非仅靠 Skill 文本。"""
    guards = (
        ("figure_render", run_figure_render),
        ("knowledge_consumption", require_knowledge_consumption),
        ("red_team_evidence", run_red_team_evidence),
        ("paper_compile_receipt", verify_paper_compile_receipt),
    )
    return [{"name": name, "available": callable(function)} for name, function in guards]


def audit_protocol_burden(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """审计主动 Skill 的认知负担与运行时防伪边界。

    Args:
        repo_root: 仓库根目录，测试可传入临时副本。

    Returns:
        可序列化的审计报告。文字计数只用于发现协议反客为主的风险；防伪能力
        仍要由真实执行和篡改测试证明。
    """
    metrics: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name, relative in ACTIVE_SKILLS.items():
        path = repo_root / relative
        if not path.is_file():
            missing.append(relative.as_posix())
            continue
        metrics[name] = _skill_metrics(path)

    protocol_lines = sum(item["protocol_lines"] for item in metrics.values())
    protocol_hits = sum(item["protocol_hits"] for item in metrics.values())
    protocol_explanation_lines = sum(
        item["protocol_explanation_lines"] for item in metrics.values()
    )
    protocol_explanation_hits = sum(
        item["protocol_explanation_hits"] for item in metrics.values()
    )
    math_lines = sum(item["math_focus_lines"] for item in metrics.values())
    math_hits = sum(item["math_focus_hits"] for item in metrics.values())
    guards = _runtime_guards()
    # 不能只移除英文术语就判为精简；广义流程说明也不得压过数学关注内容。
    balanced = not missing and math_lines >= protocol_explanation_lines
    report = {
        "schema_version": "1.0",
        "active_skills": metrics,
        "protocol_terms": list(PROTOCOL_TERMS),
        "protocol_explanation_terms": list(PROTOCOL_EXPLANATION_TERMS),
        "main_dialogue_decisions": list(MAIN_DIALOGUE_DECISIONS),
        "conditional_dialogue_decision": CONDITIONAL_DIALOGUE_DECISION,
        "manual_input_boundaries": {
            "route": {
                "decision_fields": list(MAIN_DIALOGUE_DECISIONS),
                "protocol_field_count": 0,
                "runtime_generated_fields": list(ROUTE_RUNTIME_FIELDS),
            },
            "knowledge_consumption": {
                "manual_summary_required": False,
                "runtime_generated_fields": list(KNOWLEDGE_RUNTIME_FIELDS),
            },
            "completed_figure": {
                "manual_evidence_paths_or_hashes_required": False,
                "runtime_generated_fields": list(FIGURE_RUNTIME_FIELDS),
            },
            "paper_compile": {
                "manual_hashes_or_command_log_required": False,
                "runtime_generated_fields": list(PAPER_RUNTIME_FIELDS),
            },
        },
        "runtime_generated_receipts": [
            "tooling and route hashes",
            "knowledge consumption",
            "figure render",
            "red-team evidence",
            "paper compile",
        ],
        "runtime_guards": guards,
        "summary": {
            "protocol_lines": protocol_lines,
            "protocol_hits": protocol_hits,
            "protocol_explanation_lines": protocol_explanation_lines,
            "protocol_explanation_hits": protocol_explanation_hits,
            "math_focus_lines": math_lines,
            "math_focus_hits": math_hits,
            "main_dialogue_required_field_count": len(MAIN_DIALOGUE_DECISIONS),
            "main_dialogue_protocol_field_count": 0,
            "math_focus_at_least_protocol": math_lines >= protocol_lines,
            "math_focus_at_least_protocol_explanation": math_lines
            >= protocol_explanation_lines,
            "all_runtime_guards_available": all(item["available"] for item in guards),
            "cognitive_burden_reduced": balanced,
        },
        "limitations": (
            "文本统计不是安全或科学正确性的证明；必须与真实执行、独立审查、"
            "源文件/输出篡改和回执复验测试一起解释。"
        ),
        "missing_skill_files": missing,
    }
    return report


def main() -> int:
    """输出审计 JSON，必要时写入指定路径。"""
    parser = argparse.ArgumentParser(description="审计 v3 主动 Skill 的协议认知负担")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_protocol_burden()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    print(rendered)
    return 0 if report["summary"]["cognitive_burden_reduced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
