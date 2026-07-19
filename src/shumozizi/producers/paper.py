"""论文生产器：建立可增量更新的 Typst 章节骨架。"""

from __future__ import annotations

from pathlib import Path


def create_paper_skeleton(run_dir: Path, *, title: str = "数学建模论文") -> Path:
    """创建不含虚构数字的论文骨架，结果值由 evidence macro 注入。"""
    paper = run_dir / "paper" / "main.typ"
    if paper.exists():
        raise FileExistsError(f"论文源文件已存在，拒绝覆盖: {paper}")
    paper.parent.mkdir(parents=True, exist_ok=True)
    paper.write_text(
        "#set page(paper: \"a4\", margin: 2.5cm)\n"
        "#set text(lang: \"zh\")\n"
        f"= {title}\n\n"
        "== 摘要\n"
        "本文从锁定的模型规格和可复验实验结果增量生成。关键数值必须通过 `evidence_map.json` 映射。\n\n"
        "== 问题重述与假设\n待补充题面驱动内容。\n\n"
        "== 模型与算法\n待补充变量、目标、约束、算法和停止条件。\n\n"
        "== 实验与验证\n待补充 baseline、primary 和 robustness/ablation。\n\n"
        "== 结论与局限\n待补充证据边界和实际意义。\n",
        encoding="utf-8",
    )
    return paper
