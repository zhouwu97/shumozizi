"""将已登记的真实 v3 结果渲染为可追溯科研图表。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, relative_inside, resolve_inside
from shumozizi.simple.figure_templates import SUPPORTED_TEMPLATES, load_data, render
from shumozizi.simple.figures import register_figure
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state

TEMPLATE_SCRIPTS = {
    "cv-roc-ci": "make_cv_roc_ci.py",
    "prediction-marginal-grid": "make_prediction_marginal_grid.py",
    "paired-raincloud": "make_paired_raincloud.py",
    "correlation-pairgrid": "make_correlation_pairgrid.py",
}


def _freeze_runtime_source(source: Path, target_dir: Path, *, prefix: str) -> Path:
    """按内容哈希冻结运行期源文件，避免后续重渲染覆盖既有证据。

    Args:
        source: 当前仓库中的源文件。
        target_dir: 当前运行内的冻结代码目录。
        prefix: 冻结文件名的稳定前缀。

    Returns:
        运行目录内内容寻址后的冻结副本路径。
    """
    content_hash = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    target = target_dir / f"{prefix}.{content_hash}{source.suffix}"
    if not target.is_file():
        shutil.copy2(source, target)
    return target


def _find_input(run_dir: Path, result_id: str, requested: str | None) -> str:
    """从 current 结果中确定唯一的真实 JSON 输出。

    Args:
        run_dir: v3 运行目录。
        result_id: 已登记结果 ID。
        requested: 用户显式指定的输出文件。

    Returns:
        相对运行目录的 JSON 输出路径。

    Raises:
        ContractError: 结果无效、不是 current 或 JSON 输出不唯一。
    """
    index = read_result_index(run_dir)
    result = next((item for item in index["results"] if item["result_id"] == result_id), None)
    if (
        result is None
        or result["status"] != "current"
        or not result["execution_valid"]
        or not quality_allows_paper(run_dir, result_id)
    ):
        raise ContractError("--result-id 必须指向 current、execution_valid=true 且通过质量层的结果")
    if requested:
        normalized = relative_inside(
            run_dir, resolve_inside(run_dir, requested, must_exist=True)
        ).as_posix()
        if normalized not in result["output_hashes"]:
            raise ContractError("--input-result 必须是 --result-id 的已登记输出")
        if Path(normalized).suffix.lower() != ".json":
            raise ContractError("--input-result 必须是 JSON 输出")
        return normalized
    candidates = [item for item in result["output_files"] if Path(item).suffix.lower() == ".json"]
    if len(candidates) != 1:
        raise ContractError("结果含零个或多个 JSON 输出；请用 --input-result 显式选择")
    return candidates[0]


def _copy_runtime_sources(run_dir: Path, template_id: str) -> tuple[str, str]:
    """复制内容寻址的模板源和 v3 渲染器到本次运行代码目录。

    Args:
        run_dir: v3 运行目录。
        template_id: 受支持的模板 ID。

    Returns:
        参考模板和渲染器在运行目录内的相对路径。
    """
    target_dir = run_dir / "code" / "figures"
    target_dir.mkdir(parents=True, exist_ok=True)
    source_template = (
        REPO_ROOT
        / "skills"
        / "mathmodel-figure-templates"
        / "scripts"
        / "templates"
        / TEMPLATE_SCRIPTS[template_id]
    )
    if not source_template.is_file():
        raise ContractError(f"保留模板源不存在: {source_template}")
    reference_target = _freeze_runtime_source(
        source_template,
        target_dir,
        prefix=f"reference_{source_template.stem}",
    )
    renderer_target = _freeze_runtime_source(
        REPO_ROOT / "src" / "shumozizi" / "simple" / "figure_templates.py",
        target_dir,
        prefix="v3_figure_templates",
    )
    return (
        reference_target.relative_to(run_dir).as_posix(),
        renderer_target.relative_to(run_dir).as_posix(),
    )


def _output_stem(run_dir: Path, value: str) -> tuple[Path, str, str]:
    """验证输出前缀并派生稳定图表 ID。

    Args:
        run_dir: v3 运行目录。
        value: 不含扩展名的相对输出前缀。

    Returns:
        绝对输出 stem、规范相对 stem 和默认图表 ID。

    Raises:
        ContractError: 前缀越界、无扩展名规则不满足或目录不在 figures 下。
    """
    stem = resolve_inside(run_dir, value)
    relative = relative_inside(run_dir, stem).as_posix()
    if stem.suffix or not relative.startswith("figures/"):
        raise ContractError("--output-prefix 必须是 figures/ 下且不含扩展名的相对路径")
    figure_id = stem.name.replace(" ", "-")
    if not figure_id:
        raise ContractError("--output-prefix 不能为空")
    return stem, relative, figure_id


def generate_from_result(
    run_dir: Path,
    *,
    template_id: str,
    result_id: str,
    output_prefix: str,
    input_result: str | None = None,
    figure_id: str | None = None,
) -> dict[str, object]:
    """以 current 真实结果生成并登记一张 v3 图表。

    Args:
        run_dir: v3 运行目录。
        template_id: 已接入模板 ID。
        result_id: 数据来源结果 ID。
        output_prefix: ``figures/`` 内的不含扩展名输出前缀。
        input_result: 可选的具体 JSON 输出路径。
        figure_id: 可选稳定图表 ID；重新生成同 ID 会替代旧图。

    Returns:
        新登记图表及其输出。
    """
    root = run_dir.resolve()
    read_simple_state(root)
    if template_id not in SUPPORTED_TEMPLATES:
        raise ContractError(
            f"模板未接入真实数据接口: {template_id}；可用: {', '.join(SUPPORTED_TEMPLATES)}"
        )
    chosen_input = _find_input(root, result_id, input_result)
    data = load_data(template_id, resolve_inside(root, chosen_input, must_exist=True))
    stem, relative_stem, default_id = _output_stem(root, output_prefix)
    reference_template, renderer_script = _copy_runtime_sources(root, template_id)
    text_boxes = render(template_id, data, stem)
    outputs = [f"{relative_stem}{suffix}" for suffix in (".png", ".pdf", ".svg")]
    entry = register_figure(
        root,
        figure_id=figure_id or default_id,
        template_id=template_id,
        result_id=result_id,
        input_result=chosen_input,
        reference_template=reference_template,
        renderer_script=renderer_script,
        outputs=outputs,
        text_boxes=relative_inside(root, text_boxes).as_posix(),
    )
    return {"success": True, "figure": entry, "outputs": outputs}


def main() -> int:
    """解析命令行、生成真实图表并输出登记摘要。"""
    parser = argparse.ArgumentParser(description="从 current v3 真实结果生成可追溯科研图表")
    parser.add_argument("run_dir", nargs="?", help="v3 运行目录")
    parser.add_argument("--template", choices=SUPPORTED_TEMPLATES)
    parser.add_argument("--result-id")
    parser.add_argument("--output-prefix")
    parser.add_argument("--input-result")
    parser.add_argument("--figure-id")
    parser.add_argument("--list", action="store_true", help="列出已接入真实数据接口的模板")
    args = parser.parse_args()
    if args.list:
        print("\n".join(SUPPORTED_TEMPLATES))
        return 0
    if not args.run_dir or not args.template or not args.result_id or not args.output_prefix:
        parser.error("除 --list 外，必须提供 run_dir、--template、--result-id 和 --output-prefix")
    try:
        payload = generate_from_result(
            Path(args.run_dir),
            template_id=args.template,
            result_id=args.result_id,
            output_prefix=args.output_prefix,
            input_result=args.input_result,
            figure_id=args.figure_id,
        )
    except (ContractError, OSError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
