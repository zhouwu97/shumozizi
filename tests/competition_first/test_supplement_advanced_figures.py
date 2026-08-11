"""验证 SECOND STEP 高级图补充脚本：首稿后独立渲染、插入、登记（工作流独立阶段）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shumozizi.core.io import atomic_json

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))
sys.path.insert(0, str(ROOT / ".agents" / "skills" / "mathmodel-advanced-figures" / "scripts"))

from supplement_advanced_figures import (  # noqa: E402,F401
    _figure_block,
    _insert_figure,
    _register_figure,
)


def _synthetic_run(tmp_path: Path) -> Path:
    """构造带首稿 + production 数据 + 空图索引的最小运行。"""
    run_dir = tmp_path / "run"
    (run_dir / "paper").mkdir(parents=True)
    (run_dir / "results/raw").mkdir(parents=True)
    (run_dir / "figures").mkdir(parents=True)
    (run_dir / "paper/longform-source.tex").write_text(
        "\\section{问题 Q2：测试}\n\n只有文字。\n\n\\section{问题 Q3：测试}\n\n更多文字。\n",
        encoding="utf-8",
    )
    atomic_json(
        run_dir / "results/raw/q2_probability_curve.json",
        {
            "results": [
                {"volume_fraction": 0.5, "p_estimate": 0.079, "ci_lower": 0.070, "ci_upper": 0.089, "n_media": 354},
                {"volume_fraction": 0.7, "p_estimate": 0.358, "ci_lower": 0.341, "ci_upper": 0.375, "n_media": 495},
            ]
        },
    )
    atomic_json(
        run_dir / "figures/index.json",
        {"schema_name": "simple_figure_index", "schema_version": "1.3", "run_id": run_dir.name, "figures": []},
    )
    return run_dir


def test_insert_figure_after_section(tmp_path: Path) -> None:
    """figure 块必须插在对应 section 标题之后。"""
    run_dir = _synthetic_run(tmp_path)
    tex = (run_dir / "paper/longform-source.tex").read_text(encoding="utf-8")
    block = _figure_block("fig_q2", "../figures/current/fig_q2.pdf", "图注", "展示了渗流转变")
    out = _insert_figure(tex, block, "问题 Q2")
    # 图块插在 Q2 section 后、Q3 section 前
    assert out.find("问题 Q2") < out.find("includegraphics") < out.find("问题 Q3")
    assert "fig:fig_q2" in out


def test_register_figure_writes_current_entry(tmp_path: Path) -> None:
    """登记后 figures/index.json 有 current 条目且绑定 production 来源。"""
    run_dir = _synthetic_run(tmp_path)
    _register_figure(run_dir, "fig_q2_adv", "fig_q2_adv", "results/raw/q2_probability_curve.json", "probability_curve")
    index = json.loads((run_dir / "figures/index.json").read_text(encoding="utf-8"))
    entry = next(item for item in index["figures"] if item["figure_id"] == "fig_q2_adv")
    assert entry["status"] == "current"
    assert entry["source_files"][0]["path"] == "results/raw/q2_probability_curve.json"
    assert "probability_curve" in entry["takeaway"]


def test_supplement_script_end_to_end(tmp_path: Path) -> None:
    """整脚本：渲染 + 插入 + 登记一次完成。"""
    from supplement_advanced_figures import main

    run_dir = _synthetic_run(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            [
                {
                    "template": "probability_curve",
                    "input": "results/raw/q2_probability_curve.json",
                    "output": "figures/current/fig_q2_curve_adv",
                    "caption": "导通概率转变",
                    "interpretation": "这张图展示了渗流转变",
                    "insert_after": "问题 Q2",
                }
            ]
        ),
        encoding="utf-8",
    )
    import contextlib
    import io as _io

    # 直接调用 main() 需要伪造 sys.argv（argparse 从 sys.argv 读取）。
    import sys as _sys

    _sys.argv = [
        "supplement_advanced_figures.py",
        str(run_dir),
        "--plan",
        str(plan_path),
    ]
    with contextlib.redirect_stdout(_io.StringIO()):
        exit_code = main()
    assert exit_code == 0
    tex = (run_dir / "paper/longform-source.tex").read_text(encoding="utf-8")
    assert "fig_q2_curve_adv" in tex
    assert (run_dir / "figures/current/fig_q2_curve_adv.png").is_file()
    index = json.loads((run_dir / "figures/index.json").read_text(encoding="utf-8"))
    assert any(item["figure_id"] == "fig_q2_curve_adv" for item in index["figures"])
