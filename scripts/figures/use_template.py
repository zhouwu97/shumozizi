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
from shumozizi.simple.direct_adaptation import (
    DIRECT_ADAPTATION_READY,
    adapt_and_render,
    prepare_manual_adaptation,
)
from shumozizi.simple.figure_templates import SUPPORTED_TEMPLATES, load_data, render
from shumozizi.simple.figures import register_figure
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state

_REFERENCE_TEMPLATE_BASE = {
    "active_constraint_map": "feasible-region-active-constraints",
    "argument_evidence_map": "multi-panel-evidence-chain",
    "constraint_margin_timeline": "interval-event-timeline",
    "model_evolution_schematic": "multi-panel-evidence-chain",
    "uncertainty_threshold_ribbon": "uncertainty-fan-threshold",
}

# WHY：由真实 renderer 支持集派生参考脚本，避免新增模板时 CLI 映射静默落后。
TEMPLATE_SCRIPTS = {
    template_id: (
        "make_"
        + _REFERENCE_TEMPLATE_BASE.get(template_id, template_id).replace("-", "_")
        + ".py"
    )
    for template_id in SUPPORTED_TEMPLATES
}

_TEMPLATE_PRESENTATION = {
    "active_constraint_map": ("活跃约束图", "optimization"),
    "argument_evidence_map": ("论证—证据关系图", "schematic"),
    "constraint_margin_timeline": ("约束余量时间线", "optimization"),
    "correlation-pairgrid": ("相关矩阵组合图", "correlation"),
    "cv-roc-ci": ("交叉验证 ROC 与置信区间", "model_evaluation"),
    "feasible-region-active-constraints": ("可行域与活跃约束", "optimization"),
    "grouped-circular-heatmap": ("分组环形热图", "correlation"),
    "grouped-corr-split-violin": ("相关矩阵与分组小提琴", "correlation"),
    "interval-event-timeline": ("区间与关键事件时间线", "temporal"),
    "model_evolution_schematic": ("模型演化示意图", "schematic"),
    "multi-panel-evidence-chain": ("多面板联合证据链", "combination"),
    "multiclass-shap-combo": ("多分类 SHAP 组合图", "machine_learning"),
    "nature-chord-diagram": ("加权关系和弦图", "correlation"),
    "paired-raincloud": ("配对云雨图", "distribution"),
    "prediction-marginal-grid": ("预测—真实值边缘分布", "model_evaluation"),
    "rf-tpe-surface": ("调参试验响应曲面", "machine_learning"),
    "taylor-diagram": ("多模型泰勒图", "model_evaluation"),
    "uncertainty-fan-threshold": ("不确定性扇形与阈值", "uncertainty"),
    "uncertainty_threshold_ribbon": ("不确定性阈值带", "uncertainty"),
    "urban-park-cooling-combo": ("组成与分组分布组合图", "combination"),
}

_CATEGORY_GUIDANCE = {
    "classification": ("存在真实分类标签与留出预测时", "没有留出集或类别极不平衡却未说明时", ["decisive_evidence", "stability"]),
    "combination": ("多个互补面板共同回答一个核心论点时", "只是为了增加面板数量或每问强行拼图时", ["decisive_evidence", "insight"]),
    "correlation": ("关系矩阵、分组相关或加权连接结构真实存在时", "只有少量无结构标量或试图用相关证明因果时", ["model_understanding", "insight"]),
    "distribution": ("需要比较完整分布、配对变化或样本异质性时", "只有单个汇总值或样本未配对时", ["decisive_evidence", "stability"]),
    "machine_learning": ("模型实际产生调参试验或解释值时", "没有真实 trial、SHAP 或留出预测却想补造高级图时", ["insight", "stability"]),
    "model_evaluation": ("多个模型按统一参考和同一留出协议比较时", "模型评价口径、参考标准或样本集合不一致时", ["decisive_evidence", "stability"]),
    "optimization": ("可行域、活跃约束、余量或真实搜索点决定结论时", "只有收敛曲线且没有统一 exact 指标和可行性时", ["decisive_evidence", "insight"]),
    "schematic": ("需要解释模型对象继承或论证关系时", "用示意图替代中央推导、真实结果或约束验证时", ["model_understanding"]),
    "temporal": ("区间、事件、阶段或时间余量的顺序决定结果时", "数据没有时间顺序或事件只是装饰标注时", ["model_understanding", "insight"]),
    "uncertainty": ("分位带、置信区间或阈值越界风险真实可得时", "只有点估计或把搜索波动冒充统计不确定性时", ["stability", "decisive_evidence"]),
}

_TEMPLATE_GUIDANCE_OVERRIDES = {
    "multiclass-shap-combo": (
        "模型已实际计算逐类别、逐特征、逐样本 SHAP 时",
        "只有内置重要性、回归系数或代理解释而没有真实 SHAP 时",
        ["model_understanding", "insight"],
    ),
    "nature-chord-diagram": (
        "真实加权关系或流量需要同时表达节点分组与连接强度时",
        "连接结构不存在、权重不可比较或只有无方向的装饰性关系时",
        ["model_understanding", "insight"],
    ),
    "rf-tpe-surface": (
        "真实调参 trials 覆盖二维参数空间且需解释响应结构时",
        "试验点过少、近共线，或准备把插值曲面写成连续目标函数真值时",
        ["insight", "stability"],
    ),
    "taylor-diagram": (
        "多个模型相对同一参考序列比较标准差与相关性时",
        "模型使用不同参考标准差、样本集合或评价时段时",
        ["decisive_evidence", "stability"],
    ),
}

_REQUIRED_DATA_SUMMARY = {
    "active_constraint_map": "二维候选点、可行 mask、约束边界、活跃约束和选定点",
    "argument_evidence_map": "带 kind 的论证节点和有向关系边",
    "constraint_margin_timeline": "共享时间轴、逐约束余量序列和活跃容差",
    "correlation-pairgrid": "至少三行同字段数值观测",
    "cv-roc-ci": "同一留出协议下各模型各折的 FPR/TPR",
    "feasible-region-active-constraints": "候选点、可行 mask、边界、活跃约束和最终点",
    "grouped-circular-heatmap": "至少三个项目与至少两个同向可比指标环",
    "grouped-corr-split-violin": "两个分组的同字段逐样本观测矩阵",
    "interval-event-timeline": "实体区间、关键事件和最终有效区间",
    "model_evolution_schematic": "带 stage 的模型对象节点和继承边",
    "multi-panel-evidence-chain": "2--4 个共享论点、阅读顺序明确的真实数据面板",
    "multiclass-shap-combo": "实际计算的分类 SHAP 聚合值与逐样本贡献/特征值",
    "nature-chord-diagram": "至少三个节点、真实分组和正权重连接",
    "paired-raincloud": "同一对象成对的 before/after 观测",
    "prediction-marginal-grid": "同一样本的真实值与预测值",
    "rf-tpe-surface": "至少覆盖两个 x 与两个 y 水平的真实调参 trials",
    "taylor-diagram": "统一参考标准差及各模型标准差和相关系数",
    "uncertainty-fan-threshold": "共享 x、中心估计、嵌套区间带和决策阈值",
    "uncertainty_threshold_ribbon": "共享 x、中心估计、嵌套区间带和决策阈值",
    "urban-park-cooling-combo": "类别组成矩阵与 1--3 个多分组逐样本指标",
}

_PREVIEW_FIDELITY = {
    "active_constraint_map": ("preview_grade", "native"),
    "argument_evidence_map": ("preview_grade", "native"),
    "constraint_margin_timeline": ("preview_grade", "native"),
    "correlation-pairgrid": ("safe_adapted", "safe_adaptation"),
    "cv-roc-ci": ("safe_adapted", "safe_adaptation"),
    "feasible-region-active-constraints": ("preview_grade", "native"),
    "grouped-circular-heatmap": ("needs_visual_refinement", "refinement_queue"),
    "grouped-corr-split-violin": ("needs_visual_refinement", "refinement_queue"),
    "interval-event-timeline": ("preview_grade", "native"),
    "model_evolution_schematic": ("preview_grade", "native"),
    "multi-panel-evidence-chain": ("preview_grade", "native"),
    "multiclass-shap-combo": ("needs_visual_refinement", "refinement_queue"),
    "nature-chord-diagram": ("preview_grade", "preview_adaptation"),
    "paired-raincloud": ("preview_grade", "preview_adaptation"),
    "prediction-marginal-grid": ("needs_visual_refinement", "refinement_queue"),
    "rf-tpe-surface": ("safe_adapted", "safe_adaptation"),
    "taylor-diagram": ("safe_adapted", "safe_adaptation"),
    "uncertainty-fan-threshold": ("preview_grade", "native"),
    "uncertainty_threshold_ribbon": ("preview_grade", "native"),
    "urban-park-cooling-combo": ("needs_visual_refinement", "refinement_queue"),
}

_GRAYSCALE_READABILITY = {
    "grouped-circular-heatmap": "weak",
    "multiclass-shap-combo": "conditional",
    "nature-chord-diagram": "conditional",
}

_MIN_PAPER_WIDTH_CM = {
    "correlation-pairgrid": 15.5,
    "grouped-corr-split-violin": 15.5,
    "multi-panel-evidence-chain": 15.5,
    "multiclass-shap-combo": 15.5,
    "prediction-marginal-grid": 15.5,
    "urban-park-cooling-combo": 15.5,
}

_STRUCTURE_ROUTES = {
    "classification": (
        "cv-roc-ci",
        "multiclass-shap-combo",
        "prediction-marginal-grid",
        "taylor-diagram",
    ),
    "distribution": (
        "paired-raincloud",
        "grouped-corr-split-violin",
        "urban-park-cooling-combo",
    ),
    "flow": ("nature-chord-diagram", "argument_evidence_map"),
    "network": ("nature-chord-diagram", "argument_evidence_map"),
    "optimization": (
        "feasible-region-active-constraints",
        "active_constraint_map",
        "constraint_margin_timeline",
        "rf-tpe-surface",
    ),
    "temporal": ("interval-event-timeline", "constraint_margin_timeline"),
    "uncertainty": ("uncertainty-fan-threshold", "uncertainty_threshold_ribbon"),
}


def _master_resources() -> tuple[Path, Path]:
    """返回 sci-box 母版库的模板与预览目录（上游 jihe520/sci-box 原样副本）。

    Returns:
        ``(模板脚本目录, 预览目录)``。
    """
    sci_box_templates = Path("skills/sci-box/scibox-figure/scripts/templates")
    sci_box_previews = Path("skills/sci-box/scibox-figure/assets/previews")
    if (REPO_ROOT / sci_box_templates).is_dir():
        return sci_box_templates, sci_box_previews
    # legacy 兜底：mathmodel-figure-templates 是 sci-box 的同源本地副本（含扩展模板）。
    return (
        Path("skills/mathmodel-figure-templates/scripts/templates"),
        Path("skills/mathmodel-figure-templates/assets/previews"),
    )


def _template_script_path(template_id: str) -> Path:
    """返回母版模板脚本相对仓库根的路径（sci-box 优先，legacy 兜底）。"""
    templates_dir, _ = _master_resources()
    candidate = templates_dir / TEMPLATE_SCRIPTS[template_id]
    if not (REPO_ROOT / candidate).is_file():
        legacy = (
            Path("skills/mathmodel-figure-templates/scripts/templates") / TEMPLATE_SCRIPTS[template_id]
        )
        if (REPO_ROOT / legacy).is_file():
            return legacy
    return candidate


def template_catalog_payload() -> dict[str, object]:
    """构造供 CLI、Agent 和图库前端共同消费的生产模板目录。"""
    template_root, preview_root = _master_resources()
    templates = []
    for template_id in SUPPORTED_TEMPLATES:
        script_name = TEMPLATE_SCRIPTS[template_id]
        preview_name = f"{Path(script_name).stem.removeprefix('make_')}_replica.png"
        preview = preview_root / preview_name
        title, category = _TEMPLATE_PRESENTATION[template_id]
        use_when, avoid_when, evidence_role = _TEMPLATE_GUIDANCE_OVERRIDES.get(
            template_id,
            _CATEGORY_GUIDANCE[category],
        )
        preview_fidelity, adaptation_level = _PREVIEW_FIDELITY[template_id]
        templates.append(
            {
                "template_id": template_id,
                "title": title,
                "category": category,
                "reference_script": (template_root / script_name).as_posix(),
                "preview": preview.as_posix() if (REPO_ROOT / preview).is_file() else None,
                "renderer_available": True,
                "requires_current_result": True,
                "demo_only": False,
                "use_when": use_when,
                "avoid_when": avoid_when,
                "evidence_role": evidence_role,
                "required_data_summary": _REQUIRED_DATA_SUMMARY[template_id],
                "min_paper_width_cm": _MIN_PAPER_WIDTH_CM.get(template_id, 12.0),
                "preview_fidelity": preview_fidelity,
                "adaptation_level": adaptation_level,
                "grayscale_readability": _GRAYSCALE_READABILITY.get(template_id, "good"),
            }
        )
    return {
        "schema_name": "production_figure_template_catalog",
        "schema_version": "1.1",
        "templates": templates,
    }


def recommend_template_candidates(structure: str) -> dict[str, object]:
    """按建模数据结构返回高级图候选，不替代当前论点和数据合同判断。"""
    normalized = structure.strip().lower().replace("/", "_").replace("-", "_")
    aliases = {"network_flow": "flow", "time": "temporal"}
    normalized = aliases.get(normalized, normalized)
    template_ids = _STRUCTURE_ROUTES.get(normalized)
    if template_ids is None:
        raise ContractError(
            f"未知图表结构: {structure}；可用: {', '.join(sorted(_STRUCTURE_ROUTES))}"
        )
    catalog = template_catalog_payload()
    by_id = {item["template_id"]: item for item in catalog["templates"]}
    candidates = [by_id[template_id] for template_id in template_ids]
    ready = [
        item for item in candidates
        if item["preview_fidelity"] != "needs_visual_refinement"
    ]
    refinement_queue = [
        item for item in candidates
        if item["preview_fidelity"] == "needs_visual_refinement"
    ]
    return {
        "structure": normalized,
        "advisory_only": True,
        "selection_rule": "按整篇论文主线、当前真实数据和论证角色选择，不按每问强行一张高级图。",
        "candidates": ready,
        "refinement_queue": refinement_queue,
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
    source_template = REPO_ROOT / _template_script_path(template_id)
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
    figure_stage: str = "publication",
    claim_ids: list[str] | None = None,
    scientific_question: str | None = None,
    expected_takeaway: str | None = None,
    cannot_prove: str | None = None,
    adaptation: str = "direct",
) -> dict[str, object]:
    """以 current 真实结果生成并登记一张 v3.1 图表（旧运行兼容，单步登记到 current）。

    v3.2 及以后的生产路径请用 :func:`render_candidate`（渲染 work 候选，不登记），
    再经 ``promote_figure_candidate.py`` 晋级。本函数保留旧 v3.1 运行的一次性登记行为。

    Args:
        run_dir: v3 运行目录。
        template_id: 已接入模板 ID。
        result_id: 数据来源结果 ID。
        output_prefix: ``figures/current/...`` 内的不含扩展名输出前缀。
        input_result: 可选的具体 JSON 输出路径。
        figure_id: 可选稳定图表 ID。
        figure_stage: 登记阶段（evidence / publication / current）。
        adaptation: ``direct`` / ``manual`` / ``reimplemented``。

    Returns:
        登记结果；direct 无 shim 或 manual 时返回编辑指引而不登记。

    Raises:
        ContractError: 输入不合法、模板不可用或渲染失败。
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
    figure_id = figure_id or default_id

    if adaptation == "manual" or (
        adaptation == "direct" and template_id not in DIRECT_ADAPTATION_READY
    ):
        guide = prepare_manual_adaptation(template_id, data, stem, root)
        guide.update(
            {
                "success": True,
                "mode": "manual",
                "result_id": result_id,
                "input_result": chosen_input,
                "notice": (
                    f"{template_id} 暂无自动 direct shim；已复制原母版脚本到 "
                    f"{guide['adapted_script']}，由你手工替换数据入口后运行，再走晋级流程。"
                ),
            }
        )
        return guide

    if adaptation == "direct":
        target_dir = root / "code" / "figures"
        target_dir.mkdir(parents=True, exist_ok=True)
        reference_target = _freeze_runtime_source(
            REPO_ROOT / _template_script_path(template_id),
            target_dir,
            prefix=f"reference_{Path(TEMPLATE_SCRIPTS[template_id]).stem}",
        )
        result = adapt_and_render(template_id, data, stem, root, figure_id=figure_id)
        outputs = result["outputs"]
        text_boxes = result["text_boxes"]
        visual_manifest = result["visual_manifest"]
        renderer_script = result["adapted_script"]
        reference_template = reference_target.relative_to(root).as_posix()
    else:  # reimplemented
        reference_template, renderer_script = _copy_runtime_sources(root, template_id)
        text_boxes = relative_inside(root, render(template_id, data, stem, figure_id=figure_id)).as_posix()
        outputs = [f"{relative_stem}{suffix}" for suffix in (".png", ".pdf", ".svg")]
        visual_manifest = f"{relative_stem}.visual_manifest.json"

    entry = register_figure(
        root,
        figure_id=figure_id,
        template_id=template_id,
        result_id=result_id,
        input_result=chosen_input,
        reference_template=reference_template,
        renderer_script=renderer_script,
        outputs=outputs,
        text_boxes=text_boxes,
        figure_stage=figure_stage,
        claim_ids=claim_ids,
        scientific_question=scientific_question,
        expected_takeaway=expected_takeaway,
        cannot_prove=cannot_prove,
    )
    return {
        "success": True,
        "mode": adaptation,
        "figure": entry,
        "outputs": outputs,
        "visual_manifest": visual_manifest,
        "layout_report": f"{relative_stem}.layout_report.json",
    }


def _promote_command(
    run_dir: Path,
    figure_id: str,
    relative_stem: str,
    layout_report: str,
    visual_manifest: str,
) -> str:
    """生成 work 候选晋级 current 的 promote 命令模板（角色与人工复核由 Agent 补充）。"""
    return (
        f"# 1) 打开 {relative_stem}.png 实际看图（文字溢出/箭头/面板/数据是否真实）\n"
        f"# 2) 确认 layout_report 的 needs_human_confirmation 字段（colorblind_safe / "
        f"locale_consistent / takeaway_annotation）后写入 figures/work/{figure_id}/<version>/*.human-review.json\n"
        f"python scripts/figures/promote_figure_candidate.py runs/{run_dir.name} \\\n"
        f"  --figure-id {figure_id} \\\n"
        f"  --candidate {relative_stem}.png --candidate {relative_stem}.pdf \\\n"
        f"  --target-stem figures/current/{figure_id} \\\n"
        f"  --rendering-mode plot \\\n"
        f"  --layout-report {layout_report} \\\n"
        f"  --visual-manifest {visual_manifest} \\\n"
        f"  --figure-role <model_understanding|decisive_evidence|insight|stability> \\\n"
        f"  [--presentation-role <data_portrait|question_hero|supporting|appendix>] \\\n"
        f"  --human-review figures/work/{figure_id}/<version>/{figure_id}.human-review.json"
    )


def render_candidate(
    run_dir: Path,
    *,
    template_id: str,
    result_id: str,
    output_prefix: str,
    input_result: str | None = None,
    figure_id: str | None = None,
    adaptation: str = "direct",
) -> dict[str, object]:
    """以 current 真实结果渲染一张 work 候选图（不登记，晋级走 promote_figure_candidate）。

    Args:
        run_dir: v3 运行目录。
        template_id: 已接入模板 ID。
        result_id: 数据来源结果 ID。
        output_prefix: ``figures/work/<figure_id>/<version>/`` 内的不含扩展名输出前缀。
        input_result: 可选的具体 JSON 输出路径。
        figure_id: 可选稳定图表 ID。
        adaptation: ``direct``（默认，复制 sci-box 母版脚本只换数据入口）、
            ``manual``（复制原脚本留 stub 由 Agent 手工换数据）或
            ``reimplemented``（本仓 v3 简化渲染器回退）。

    Returns:
        候选输出、机器生成的 text-boxes/visual_manifest/layout_report 与晋级命令；
        manual 模式返回编辑指引而不渲染。

    Raises:
        ContractError: 输入不合法、模板不可用或渲染失败。
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
    figure_id = figure_id or default_id
    if not relative_stem.startswith("figures/work/"):
        raise ContractError(
            "work 候选输出必须位于 figures/work/<figure_id>/<version>/ 下；"
            f"当前: {relative_stem}"
        )

    if adaptation == "manual" or (
        adaptation == "direct" and template_id not in DIRECT_ADAPTATION_READY
    ):
        # direct 无 shim 时自动进入 manual-copy（复制原母版留 stub），
        # 绝不静默回退到简化 reimplemented 渲染器。
        guide = prepare_manual_adaptation(template_id, data, stem, root)
        guide.update(
            {
                "success": True,
                "mode": "manual",
                "result_id": result_id,
                "input_result": chosen_input,
                "notice": (
                    f"{template_id} 暂无自动 direct shim；已复制原母版脚本到 "
                    f"{guide['adapted_script']}，由你手工替换数据入口后运行，再走晋级流程。"
                ),
            }
        )
        return guide

    if adaptation == "direct":
        # 冻结母版原脚本作为 reference；复制后的 adapted 脚本就是本次实际执行的母版。
        target_dir = root / "code" / "figures"
        target_dir.mkdir(parents=True, exist_ok=True)
        _freeze_runtime_source(
            REPO_ROOT / _template_script_path(template_id),
            target_dir,
            prefix=f"reference_{Path(TEMPLATE_SCRIPTS[template_id]).stem}",
        )
        result = adapt_and_render(template_id, data, stem, root, figure_id=figure_id)
        outputs = result["outputs"]
        text_boxes = result["text_boxes"]
        layout_report = result["layout_report"]
        visual_manifest = result["visual_manifest"]
        renderer_script = result["adapted_script"]
    else:  # reimplemented
        reference_template, renderer_script = _copy_runtime_sources(root, template_id)
        text_boxes = relative_inside(root, render(template_id, data, stem, figure_id=figure_id)).as_posix()
        outputs = [f"{relative_stem}{suffix}" for suffix in (".png", ".pdf", ".svg")]
        layout_report = f"{relative_stem}.layout_report.json"
        visual_manifest = f"{relative_stem}.visual_manifest.json"

    promote = _promote_command(root, figure_id, relative_stem, layout_report, visual_manifest)
    return {
        "success": True,
        "mode": adaptation,
        "figure_id": figure_id,
        "result_id": result_id,
        "input_result": chosen_input,
        "outputs": outputs,
        "text_boxes": text_boxes,
        "visual_manifest": visual_manifest,
        "layout_report": layout_report,
        "renderer_script": renderer_script,
        "promote": promote,
    }


def main() -> int:
    """解析命令行、渲染 work 候选图并输出晋级命令。"""
    parser = argparse.ArgumentParser(
        description="从 current v3 真实结果渲染 sci-box 母版 work 候选图（晋级走 promote_figure_candidate）"
    )
    parser.add_argument("run_dir", nargs="?", help="v3 运行目录")
    parser.add_argument("--template", choices=SUPPORTED_TEMPLATES)
    parser.add_argument("--result-id")
    parser.add_argument(
        "--output-prefix",
        help="figures/work/<figure-id>/<version>/ 下的不含扩展名输出前缀",
    )
    parser.add_argument("--input-result")
    parser.add_argument("--figure-id")
    parser.add_argument(
        "--adaptation",
        choices=("direct", "manual", "reimplemented"),
        default="direct",
        help="direct=复制 sci-box 母版脚本只换数据入口（默认，无 shim 时自动转 manual-copy）；"
        "manual=复制原脚本留 stub 手工换数据；reimplemented=本仓 v3 简化渲染器回退（明确要求才用）",
    )
    parser.add_argument("--list", action="store_true", help="列出已接入真实数据接口的模板")
    parser.add_argument("--catalog", action="store_true", help="输出机器可读的生产模板目录")
    parser.add_argument("--recommend", help="按建模结构推荐高级图候选")
    args = parser.parse_args()
    if args.recommend:
        try:
            recommendation = recommend_template_candidates(args.recommend)
        except ContractError as exc:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(recommendation, ensure_ascii=False, indent=2))
        return 0
    if args.catalog:
        print(json.dumps(template_catalog_payload(), ensure_ascii=False, indent=2))
        return 0
    if args.list:
        print("\n".join(SUPPORTED_TEMPLATES))
        return 0
    if not args.run_dir or not args.template or not args.result_id or not args.output_prefix:
        parser.error(
            "除 --list/--catalog/--recommend 外，必须提供 run_dir、--template、--result-id 和 --output-prefix"
        )
    try:
        payload = render_candidate(
            Path(args.run_dir),
            template_id=args.template,
            result_id=args.result_id,
            output_prefix=args.output_prefix,
            input_result=args.input_result,
            figure_id=args.figure_id,
            adaptation=args.adaptation,
        )
    except (ContractError, OSError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
