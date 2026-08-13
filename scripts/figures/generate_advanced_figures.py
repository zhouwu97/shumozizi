"""数据驱动的高级图自动产出：把论文 current 图升级为国奖级渲染。

实验阶段用朴素 render.py 画单面板曲线（calibration/probability/pr_roc），
不是因为没有高级渲染器，而是没有把 production 数据路由到高级模板。本脚本
补齐这条桥：读 ``figures/index.json`` 找到正文 current 图引用的 production
结果，用适配器构造 render_advanced 模板的输入文档，确定性渲染高级图并登记，
最后复跑视觉竞争力审计确认缺口是否闭合。

用法：:

    # 预览（不写文件）：列出将渲染的高级图与预计的审计变化
    python scripts/figures/generate_advanced_figures.py <run_dir>

    # 实际渲染并登记到 figures/index.json
    python scripts/figures/generate_advanced_figures.py <run_dir> --apply

本脚本不修改论文正文、不改模型结果；只新增可审计的高级图条目。论文阶段
（mathmodel-paper）按论证需要决定是否采纳这些图。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "mathmodel-advanced-figures" / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from shumozizi.core.io import atomic_json, load_json, sha256_file  # noqa: E402
from shumozizi.paper.advanced_figure_adapters import (  # noqa: E402
    build_advanced_figures,
    hero_figure_upgrades,
)
from shumozizi.paper.visual_competition_audit import audit_visual_competition  # noqa: E402

# 高级模板 → 论证角色/图型（与 advanced-figures 目录对齐）。
_TEMPLATE_ROLE = {
    "survival_curve": "decisive_evidence",
    "ci_forest": "insight",
    "cv_roc_ci": "decisive_evidence",
}


def _sha(path: Path) -> str:
    """计算文件哈希（缺失返回空串）。"""
    return sha256_file(path) if path.is_file() else ""


def _render(template: str, document: dict[str, Any], out_stem: Path) -> list[dict[str, str]]:
    """调用 advanced-figures 模板渲染，返回输出记录。"""
    from render_advanced import _TEMPLATES

    if template not in _TEMPLATES:
        raise SystemExit(f"未知模板 {template}；可用: {', '.join(_TEMPLATES)}")
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    result = _TEMPLATES[template](document, out_stem)
    return result["outputs"]


def _register(
    run_dir: Path,
    *,
    figure_id: str,
    stem: str,
    source: str,
    template: str,
    question_id: str,
    presentation_role: str = "supporting",
) -> None:
    """把新高级图登记进 figures/index.json（current + 来源绑定）。"""
    index_path = run_dir / "figures/index.json"
    index = load_json(index_path) if index_path.is_file() else {
        "schema_version": "1.3",
        "run_id": run_dir.name,
        "figures": [],
    }
    index.setdefault("figures", [])
    index["figures"] = [
        item for item in index["figures"]
        if not (isinstance(item, dict) and item.get("figure_id") == figure_id)
    ]
    # 高级图接替 hero 时，旧朴素 hero 降为 supporting，避免正文出现两张同内容 hero。
    if presentation_role in {"question_hero", "data_portrait"}:
        for item in index["figures"]:
            if (
                isinstance(item, dict)
                and item.get("status") == "current"
                and str(item.get("question_id", "")) == question_id
                and item.get("presentation_role") in {"question_hero", "data_portrait"}
            ):
                item["presentation_role"] = "supporting"
    entry = {
        "figure_id": figure_id,
        "template_id": template,
        "visual_archetype": template,
        "advanced_template": template,
        "question_id": question_id,
        "status": "current",
        "paper_allowed": True,
        "demo": False,
        "figure_stage": "current",
        "role": _TEMPLATE_ROLE.get(template, "decisive_evidence"),
        "placement": "body",
        "presentation_role": presentation_role,
        "source_files": [{"path": source, "sha256": _sha(run_dir / source)}],
        "renderer_script": {
            "path": ".agents/skills/mathmodel-advanced-figures/scripts/render_advanced.py",
            "sha256": _sha(SKILL_SCRIPTS / "render_advanced.py"),
        },
        "outputs": [
            {"path": f"figures/current/{stem}.png", "sha256": _sha(run_dir / f"figures/current/{stem}.png")},
            {"path": f"figures/current/{stem}.pdf", "sha256": _sha(run_dir / f"figures/current/{stem}.pdf")},
            {"path": f"figures/current/{stem}.svg", "sha256": _sha(run_dir / f"figures/current/{stem}.svg")},
        ],
        "takeaway": f"高级模板 {template} 由同一 current 数据确定性渲染（{source}）。",
    }
    index["figures"].append(entry)
    atomic_json(index_path, index)


def _report_findings(report: dict[str, Any]) -> list[str]:
    """提取审计发现的代码列表。"""
    return [str(item["code"]) for item in report.get("findings", [])]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把论文 current 图升级为高级模板渲染并审计缺口闭合"
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际渲染并登记；默认仅预览（dry-run）",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"运行目录不存在: {run_dir}")

    before = audit_visual_competition(run_dir)
    before_codes = _report_findings(before)

    plan = build_advanced_figures(run_dir)
    index_path = run_dir / "figures/index.json"
    index = load_json(index_path) if index_path.is_file() else {"figures": []}
    hero_map = hero_figure_upgrades(index, plan)
    print("=" * 70)
    print(f"运行目录: {run_dir.name}")
    print(f"审计基线: body_figures={before['metrics'].get('body_figure_count')} "
          f"findings={before_codes or '无'}")
    if hero_map:
        print(f"hero 晋升: {len(hero_map)} 张高级图将接替朴素 hero")
    print("=" * 70)
    if not plan:
        print("没有可升级的高级图计划项（论文 current 图引用的结果无适配模板）。")
        print("审计保持：", before_codes or "无")
        return 0

    print(f"发现 {len(plan)} 个高级图计划项（全部来自论文 current 图引用的 production 结果）：")
    for item in plan:
        marker = " [hero]" if item["output"].rsplit("/", 1)[-1] in hero_map else ""
        print(f"  - [{item['template']:14s}]{marker} {item['input']}")
        if args.apply:
            print(f"       -> {item['output']}")
    print()

    if not args.apply:
        print("[dry-run] 未渲染/登记。加 --apply 实际生成。")
        print("[预计] 渲染后将新增以下高级 archetype（降低报告式占比）:")
        pending = sorted({item["template"] for item in plan})
        print("        ", ", ".join(pending))
        return 0

    rendered: list[str] = []
    for item in plan:
        out_stem = run_dir / item["output"]
        figure_id = out_stem.name
        try:
            _render(item["template"], item["document"], out_stem)
        except (ValueError, OSError) as exc:
            print(f"  ! 渲染失败 {item['template']} <- {item['input']}: {exc}")
            continue
        _register(
            run_dir,
            figure_id=figure_id,
            stem=out_stem.name,
            source=item["input"],
            template=item["template"],
            question_id=item["question_id"],
            presentation_role="question_hero" if figure_id in hero_map else "supporting",
        )
        rendered.append(item["template"])
        hero_note = "（接替 hero）" if figure_id in hero_map else ""
        print(f"  + 渲染并登记 {figure_id} ({item['template']}){hero_note} <- {item['input']}")

    after = audit_visual_competition(run_dir)
    after_codes = _report_findings(after)
    print()
    print("=" * 70)
    print(f"复跑审计: body_figures={after['metrics'].get('body_figure_count')} "
          f"findings={after_codes or '无'}")
    print(f"渲染 {len(rendered)} 张高级图，register 到 figures/index.json")
    closed = sorted(set(before_codes) - set(after_codes))
    remaining = sorted(set(after_codes))
    if closed:
        print(f"已闭合的审计发现: {closed}")
    if remaining:
        print(f"仍存在的发现（需盲评裁决）: {remaining}")
    else:
        print("视觉竞争力审计已全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
