"""结构图确定性 TikZ renderer：structure spec -> TikZ -> PDF/SVG/PNG。

用法：:

    python render_structure.py --spec <spec.json> --output <stem>

边界硬门：spec.argument_role 为 decisive_evidence 时拒绝（TikZ 只做解释性结构图，
不进入 evidence layer；数据证据必须走确定性 Python renderer）。

spec JSON：:

    {
      "template": "shared_model_map",
      "title": "共享模型路线图",
      "argument_role": "model_understanding",
      "nodes": [{"id":"in","label":"输入","role":"input"}, ...],
      "edges": [{"from":"in","to":"core","kind":"feed"}, ...],
      "emphasis": ["core"]
    }
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from structure_templates import BLOCKED_EVIDENCE_ROLES, TEMPLATES  # noqa: E402

_PREAMBLE = r"""\documentclass[tikz,border=8pt]{standalone}
\usepackage[UTF8]{ctex}
\usepackage{amsmath,amssymb}
\usepackage{xcolor}
\definecolor{teal}{RGB}{20,125,128}
\usetikzlibrary{arrows.meta,positioning}
\begin{document}
\begin{tikzpicture}[node distance=1.2cm, font=\small]
"""

_POSTAMBLE = r"""\end{tikzpicture}
\end{document}
"""


def _validate(spec: dict[str, Any]) -> None:
    """结构图边界校验：模板已知、角色允许、节点/边结构合法。"""
    template = str(spec.get("template", "")).strip()
    if template not in TEMPLATES:
        raise SystemExit(f"未知结构模板 {template}；可用: {', '.join(TEMPLATES)}")
    role = str(spec.get("argument_role", "model_understanding")).strip()
    if role in BLOCKED_EVIDENCE_ROLES:
        raise SystemExit(
            f"argument_role={role} 拒绝：TikZ 只做解释性结构图，证据图必须走数据 renderer"
        )
    if not isinstance(spec.get("nodes"), list) or not spec["nodes"]:
        raise SystemExit("structure spec 至少需要一个节点")
    for node in spec["nodes"]:
        if not isinstance(node, dict) or not str(node.get("id", "")).strip():
            raise SystemExit("每个节点必须有非空 id")
    for edge in spec.get("edges", []):
        if not isinstance(edge, dict) or not str(edge.get("from", "")).strip() or not str(edge.get("to", "")).strip():
            raise SystemExit("每条边必须是非空 from/to")


def render_standalone_tex(spec: dict[str, Any]) -> str:
    """把 spec 渲染成可独立编译的 standalone TikZ 文档。"""
    template = str(spec["template"])
    body = TEMPLATES[template](spec)
    return _PREAMBLE + body + "\n" + _POSTAMBLE


def _compile(tex_path: Path, out_stem: Path, timeout: int) -> list[Path]:
    """用 xelatex 编译 standalone TikZ，返回产出文件。cwd 已设为输出父目录，故传文件名。"""
    cmd = [
        "xelatex", "-interaction=nonstopmode", "-halt-on-error",
        "-jobname", out_stem.stem, tex_path.name,
    ]
    proc = subprocess.run(cmd, cwd=str(out_stem.parent), capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        log = proc.stdout[-2000:] + proc.stderr[-2000:]
        raise SystemExit(f"TikZ 编译失败:\n{log}")
    produced = [
        out_stem.with_suffix(suffix)
        for suffix in (".pdf", ".aux", ".log")
    ]
    return [p for p in produced if p.exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description="结构图确定性 TikZ renderer")
    parser.add_argument("--spec", required=True, help="structure spec JSON 文件")
    parser.add_argument("--output", required=True, help="输出 stem（不含扩展名）")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        raise SystemExit(f"缺少 spec 文件: {spec_path}")
    import json

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    _validate(spec)

    out_stem = Path(args.output)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    tex_path = out_stem.parent / f"{out_stem.stem}_src.tex"
    tex_path.write_text(render_standalone_tex(spec), encoding="utf-8")
    produced = _compile(tex_path, out_stem, args.timeout_seconds)
    for path in produced:
        print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
