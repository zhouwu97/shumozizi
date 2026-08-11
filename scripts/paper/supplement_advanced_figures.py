"""SECOND STEP 高级图补充：首稿后独立渲染并插入高级图（工作流独立阶段）。

把"高级图补充"从 brief 提示词升级为可执行阶段：
1. Agent 读首稿，按数据特征决定加哪些高级图，写一个 figure plan JSON；
2. 本脚本按 plan 用 mathmodel-advanced-figures 的模板渲染（从 production 数据）、
   把 figure 环境插入正式发布入口、登记进 figures/index.json、并重编译候选稿。

plan JSON 结构：:

    [
      {
        "template": "probability_curve",
        "input": "results/raw/q2_probability_curve.json",
        "output": "figures/current/fig_q2_curve_adv",
        "caption": "导通概率随体积分数的转变与 90% 阈值。",
        "interpretation": "这张图展示了概率在 1% 体积分数量级接近渗流转变。",
        "insert_after": "问题 Q2"      # 或 LaTeX label："fig:q2"
      },
      ...
    ]

用法：:

    python scripts/paper/supplement_advanced_figures.py <run_dir> --plan <plan.json> [--compile]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "mathmodel-advanced-figures" / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from shumozizi.core.io import (  # noqa: E402
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.paper.publication import (  # noqa: E402
    freeze_publication_snapshot,
    publication_entrypoint,
)


def _sha(path: Path) -> str:
    """计算文件哈希（缺失返回空串）。"""
    return sha256_file(path) if path.is_file() else ""


def _render_figure(template: str, document: dict[str, Any], out_stem: Path) -> list[dict[str, str]]:
    """调用 advanced-figures 模板渲染，返回输出记录。"""
    from render_advanced import _TEMPLATES

    if template not in _TEMPLATES:
        raise SystemExit(f"未知模板 {template}；可用: {', '.join(_TEMPLATES)}")
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    result = _TEMPLATES[template](document, out_stem)
    return result["outputs"]


def _render_structure_figure(spec: dict[str, Any], out_stem: Path) -> list[dict[str, str]]:
    """structure spec -> TikZ -> PDF（SECOND STEP 结构图 renderer）。

    复用 render_structure 的确定性布局与边界硬门（decisive_evidence 拒绝）。
    """
    from render_structure import _compile, render_standalone_tex

    out_stem.parent.mkdir(parents=True, exist_ok=True)
    tex_path = out_stem.parent / f"{out_stem.stem}_src.tex"
    tex_path.write_text(render_standalone_tex(spec), encoding="utf-8")
    _compile(tex_path, out_stem, timeout=120)
    return [{"path": str(out_stem.with_suffix(".pdf")), "kind": "pdf"}]


def _figure_block(figure_id: str, include_pdf: str, caption: str, interpretation: str) -> str:
    """构造可插入正文的 LaTeX figure 环境（图注 + 一句'展示了什么'）。"""
    return (
        "\n\\begin{figure}[htbp]\n"
        "  \\centering\n"
        f"  \\includegraphics[width=0.9\\textwidth]{{{include_pdf}}}\n"
        f"  \\caption{{{caption}（{interpretation}）}}\n"
        f"  \\label{{fig:{figure_id}}}\n"
        "\\end{figure}\n"
    )


def _insert_figure(tex: str, block: str, anchor: str) -> str:
    """在锚点后插入 figure 块；锚点匹配 section 标题或 \\label。"""
    # 优先匹配 \section{...anchor...} 或 \subsection{...}
    section_match = re.search(
        rf"\\(?:section|subsection)\*?\{{\s*[^}}]*{re.escape(anchor)}[^}}]*\}}",
        tex,
    )
    if section_match:
        pos = section_match.end()
    else:
        label_match = re.search(rf"\\label\{{[^}}]*{re.escape(anchor)}[^}}]*\}}", tex)
        if label_match:
            pos = label_match.end()
        else:
            raise ValueError(f"正文中找不到插入锚点: {anchor}")
    return tex[:pos] + block + tex[pos:]


def _register_figure(
    run_dir: Path,
    figure_id: str,
    stem: str,
    source: str,
    template: str,
    provenance_type: str = "frozen_inputs",
    question_id: str = "",
    focal_claim: str = "",
) -> None:
    """把新高级图登记进 figures/index.json（current + 来源）。"""
    index_path = run_dir / "figures" / "index.json"
    index = load_json(index_path) if index_path.is_file() else {
        "schema_name": "simple_figure_index", "schema_version": "1.3",
        "run_id": run_dir.name, "figures": [],
    }
    index.setdefault("schema_version", "1.3")
    index.setdefault("run_id", run_dir.name)
    index.setdefault("figures", [])
    # 移除同 id 旧 current 条目，避免重复。
    index["figures"] = [
        item for item in index["figures"]
        if not (isinstance(item, dict) and item.get("figure_id") == figure_id and item.get("status") == "current")
    ]
    entry = {
        "figure_id": figure_id,
        "template_id": template,
        "visual_archetype": template,
        "advanced_template": template,
        "question_id": question_id or str(_question_id_of(index, figure_id) or ""),
        "status": "current",
        "paper_allowed": True,
        "demo": False,
        "figure_stage": "current",
        "created_at": _utc_now_iso(),
        "provenance_type": provenance_type,
        "source_files": [{"path": source, "sha256": _sha(run_dir / source)}],
        "renderer_script": {
            "path": ".agents/skills/mathmodel-advanced-figures/scripts/render_structure.py"
            if provenance_type == "explanatory_structure"
            else ".agents/skills/mathmodel-advanced-figures/scripts/render_advanced.py",
            "sha256": _sha(SKILL_SCRIPTS / "render_structure.py")
            if provenance_type == "explanatory_structure"
            else _sha(SKILL_SCRIPTS / "render_advanced.py"),
        },
        "outputs": [
            {"path": f"figures/current/{stem}.png", "sha256": _sha(run_dir / f"figures/current/{stem}.png")},
            {"path": f"figures/current/{stem}.pdf", "sha256": _sha(run_dir / f"figures/current/{stem}.pdf")},
        ],
        "focal_claim": focal_claim.strip(),
        "takeaway": f"SECOND STEP {'结构图' if provenance_type == 'explanatory_structure' else '高级图'}（{template}）：{stem}",
    }
    index["figures"].append(entry)
    atomic_json(index_path, index)


def _question_id_of(index: dict[str, Any], figure_id: str) -> str | None:
    """从既有登记条目继承 question_id（结构图常为 whole_paper）。"""
    for item in index.get("figures", []):
        if isinstance(item, dict) and item.get("figure_id") == figure_id and item.get("question_id"):
            return str(item["question_id"])
    return None


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间戳，与运行登记一致。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="SECOND STEP 高级图补充")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--plan", required=True, help="高级图 plan JSON")
    parser.add_argument("--compile", action="store_true", help="插入后重编译当前目标；正式入口会生成候选稿")
    parser.add_argument("--target", help="插入目标 tex；默认正式发布入口，长稿只能显式指定")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.is_file() else json.loads(args.plan)

    if args.target:
        try:
            tex_path = resolve_inside(run_dir, args.target, must_exist=True)
        except ContractError as exc:
            raise SystemExit(f"目标 tex 无效: {exc}") from exc
    else:
        try:
            tex_path = publication_entrypoint(run_dir)
        except ContractError as exc:
            raise SystemExit(f"缺少正式发布入口，请先物化正式稿或显式指定 --target: {exc}") from exc
    if not tex_path.is_file():
        raise SystemExit(f"缺少插入目标 {tex_path}")
    target_relative = relative_inside(run_dir, tex_path).as_posix()
    tex = tex_path.read_text(encoding="utf-8")

    for spec in plan:
        template = str(spec["template"])
        stem = str(spec["output"])
        figure_id = Path(stem).name
        out_stem = run_dir / stem
        is_structure = isinstance(spec.get("spec"), dict) or str(spec.get("kind", "")) == "structure"
        if is_structure:
            structure_spec = spec["spec"] if isinstance(spec.get("spec"), dict) else spec
            structure_spec.setdefault("argument_role", str(spec.get("argument_role", "model_understanding")))
            _render_structure_figure(structure_spec, out_stem)
            # 结构图来源是论文正文本身（解释论证结构），默认用插入目标 tex。
            source = str(spec.get("source", target_relative))
            provenance = "explanatory_structure"
        else:
            source = str(spec["input"])
            if not (run_dir / source).is_file():
                raise SystemExit(f"缺少生产数据源: {source}")
            document = load_json(run_dir / source)
            _render_figure(template, document, out_stem)
            provenance = "frozen_inputs"
        include_pdf = os.path.relpath(
            run_dir / f"{stem}.pdf", tex_path.parent
        ).replace("\\", "/")
        block = _figure_block(
            figure_id, include_pdf,
            str(spec.get("caption", "")), str(spec.get("interpretation", "")),
        )
        tex = _insert_figure(tex, block, str(spec["insert_after"]))
        _register_figure(
            run_dir, figure_id, Path(stem).name, source, template,
            provenance_type=provenance,
            question_id=str(spec.get("question_id", "whole_paper" if provenance == "explanatory_structure" else "")),
            focal_claim=str(spec.get("claim", spec.get("interpretation", ""))),
        )
        print(f"插入 {figure_id} ({template}，{provenance}) <- {source}")

    tex_path.write_text(tex, encoding="utf-8")
    print(f"{target_relative} 更新，共 {tex.count('includegraphics')} 张图")

    if args.compile:
        formal_entrypoint = publication_entrypoint(run_dir)
        if tex_path.resolve() == formal_entrypoint.resolve():
            from shumozizi.paper.compiler import compile_paper

            freeze_publication_snapshot(run_dir)
            receipt = compile_paper(run_dir, timeout_seconds=args.timeout_seconds or 300)
        else:
            from shumozizi.paper.compiler import compile_longform_draft

            receipt = compile_longform_draft(run_dir, timeout_seconds=args.timeout_seconds or 300)
        print(json.dumps(receipt, ensure_ascii=False, indent=2)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
