"""在定时或手动 CI 中验证科研绘图模板可实际渲染。"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERER = (
    REPO_ROOT
    / "skills"
    / "mathmodel-figure-templates"
    / "scripts"
    / "render_template.py"
)
EXPECTED_TEMPLATE_IDS = {
    "correlation-pairgrid",
    "cv-roc-ci",
    "grouped-circular-heatmap",
    "grouped-corr-split-violin",
    "multiclass-shap-combo",
    "nature-chord-diagram",
    "paired-raincloud",
    "prediction-marginal-grid",
    "rf-tpe-surface",
    "taylor-diagram",
    "urban-park-cooling-combo",
}
GLYPH_WARNING = re.compile(r"glyph\s+\d+.*missing", re.IGNORECASE)


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    """运行模板渲染器并将失败信息保留给 CI。

    Args:
        arguments: 渲染器参数。

    Returns:
        子进程执行结果。
    """
    return subprocess.run(
        [sys.executable, str(RENDERER), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _require_success(result: subprocess.CompletedProcess[str], label: str) -> None:
    """在渲染失败或缺字警告时给出可定位错误。

    Args:
        result: 子进程执行结果。
        label: 当前测试对象。

    Raises:
        RuntimeError: 渲染失败或发现字体字形缺失警告。
    """
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        raise RuntimeError(f"{label} 渲染失败：\n{output}")
    if GLYPH_WARNING.search(output):
        raise RuntimeError(f"{label} 出现字体字形缺失警告：\n{output}")


def main() -> int:
    """渲染全部内置模板并检查 v3 真实数据适配器。

    Returns:
        所有模板通过时返回零。
    """
    listing = _run("--list")
    _require_success(listing, "模板列表")
    template_ids = set(filter(None, listing.stdout.splitlines()))
    if template_ids != EXPECTED_TEMPLATE_IDS:
        raise RuntimeError(
            "模板列表与冻结目录不一致："
            f"expected={sorted(EXPECTED_TEMPLATE_IDS)}, actual={sorted(template_ids)}"
        )

    with tempfile.TemporaryDirectory(prefix="shumozizi-figure-smoke-") as directory:
        root = Path(directory)
        for template_id in sorted(template_ids):
            project = root / template_id
            result = _run(template_id, "--project", str(project))
            _require_success(result, template_id)
            output_dir = project / "outputs"
            for suffix in (".png", ".pdf", ".svg"):
                artifacts = list(output_dir.glob(f"*{suffix}"))
                if not artifacts or any(item.stat().st_size == 0 for item in artifacts):
                    raise RuntimeError(f"{template_id} 未生成非空 {suffix} 文件")
    adapted = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_v3_figures.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    _require_success(adapted, "v3 真实图表适配器")
    print(f"已验证 {len(template_ids)} 套科研绘图模板")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
