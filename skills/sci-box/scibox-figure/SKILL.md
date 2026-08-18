---
name: mathmodel-figure-templates
description: Use this skill in the MathModel LaTeX sandbox when the user asks to reproduce built-in scientific visualization templates, especially prompts from the Improve tab mentioning $mathmodel-figure-templates, 科研绘图模板, SHAP蜂群柱状图, 配对云雨图, 交叉验证ROC, 泰勒图, 相关矩阵组合图, 预测真实值边缘分布图, TPE调参3D曲面, 下三角相关矩阵半边小提琴图, 分组环形热图, 城市公园降温组合图, or Nature和弦图. It provides ready-to-run Python scripts bundled inside the skill.
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob
---

# MathModel Figure Templates

This skill is bundled into the LaTeX sandbox at `/home/user/.claude/skills/mathmodel-figure-templates`. It contains ready-to-run Python/matplotlib scripts for the figure templates exposed in the MathModel Improve tab.

## Fast Path

1. Match the requested chart in `references/figure-catalog.md`.
2. From `/home/user/workspace`, run the renderer with the template id:

```bash
python3 /home/user/.claude/skills/mathmodel-figure-templates/scripts/render_template.py paired-raincloud
```

3. The renderer copies the bundled template script into `绘图复刻/scripts/`, runs it there, and writes outputs to `绘图复刻/outputs/`.
4. Return the generated PNG/PDF/SVG paths and the copied script path to the user.

Use `--list` to show supported ids:

```bash
python3 /home/user/.claude/skills/mathmodel-figure-templates/scripts/render_template.py --list
```

## Output Contract

- Work under the current workspace unless the user gives another path.
- Default project folder: `绘图复刻`.
- Script path: `绘图复刻/scripts/make_<template>.py`.
- Outputs: `绘图复刻/outputs/<template>_replica.png`, `.pdf`, `.svg`.
- Use the bundled scripts as the first choice; edit the copied workspace script only when the user requests customization.
- The bundled scripts use deterministic simulated data. Do not claim simulated values reproduce a source study exactly.

## Template Ids

- `multiclass-shap-combo`
- `paired-raincloud`
- `cv-roc-ci`
- `taylor-diagram`
- `correlation-pairgrid`
- `prediction-marginal-grid`
- `rf-tpe-surface`
- `grouped-corr-split-violin`
- `grouped-circular-heatmap`
- `urban-park-cooling-combo`
- `nature-chord-diagram`

## When Customizing

If the user asks for changes, copy/run the nearest template first, then edit the copied file in `绘图复刻/scripts/`. Preserve:

- `MPLCONFIGDIR` before importing matplotlib.
- deterministic seeds for simulated data.
- PNG/PDF/SVG export.
- readable labels, legends, and high-DPI output.

Use `references/plot-recipes.md` for implementation patterns.

---

## shumozizi 生产集成（本仓库）

本技能是**母版库**：11 套模板脚本的版式（面板几何、字号、轴线、图例、间距、注释）是人工设计好的成品。
在生产运行（uns/<run-id>）里，**使用模板 = 复制原脚本 → 只替换真实数据入口 → 尽量保留绘图结构 → 按本题少量调整**，
禁止默认重新实现。数据入口替换由 scripts/figures/use_template.py --adaptation direct 自动完成
（把 simulate_*() / 模块常量换成真实结果 JSON 的转换结果，其余 draw_*、ig.add_axes、ig.legend 原样保留）：

`powershell
python scripts/figures/use_template.py runs/<run-id> 
  --template grouped-corr-split-violin --result-id <current-id> 
  --output-prefix figures/publication/q3-corr --adaptation direct
`

- --adaptation direct（默认）：自动复制原脚本 + 注入真实数据 shim 后原样运行；
- --adaptation manual：复制原脚本并写入标记好的数据入口 stub，由 Agent 手工换数据（允许拆/并/删面板、改变量数）；
- --adaptation reimplemented：本仓 v3 简化渲染器回退（最后一档，不当作默认路径）。

### 决策顺序（硬性优先级，前面的能表达清楚就不准偷懒跑后面）

`
① 本技能原生母版（direct adaptation）
        ↓ 不合适
② 母版深度改造 / 组合（拆 panel、并 panel、删 panel、改语义）
        ↓ 不合适
③ scibox-diagram（结构解释图：路线/框架/流程，是一等候选）
        ↓ 不合适
④ 本题专用高级 Python/Matplotlib 图（真实结构原型）
        ↓ 不合适
⑤ 普通 scatter / heatmap / line
        ↓
⑥ bar（最后选择）
`

不是禁止 ⑤⑥，而是能表达清楚就不准偷懒；柱状/折线确实最清楚时可用，由人工视觉评审说明理由，不填预防性 override 表单。

### 选模板前必须看预览

禁止只凭模板 id 名称选图。选择前必须打开 ssets/previews/*_replica.png（或运行
python skills/sci-box/scibox-figure/scripts/render_template.py --list 后用 --project <dir> 生成一张），
回答三个问题：① 结构和我的数据匹不匹配？② 比普通图多表达了什么？③ 换真实数据后视觉优势是否保留？
满足才用；不满足换下一张。在 FIGURE_PLAN 里记录 	emplate_preview_viewed: true。

### FIGURE_PLAN 衔接

- selected_skill：skills/sci-box/scibox-figure（数据图）或 skills/sci-box/scibox-diagram（结构图）。
- preferred / allback：在 sci-box、mathmodel-figure-templates、3coding-visual、4drawio 中按优先级填写。
- 	emplate_id：直接写母版 id（如 grouped-corr-split-violin）或 diagram 模板 id（oadmap-5band 等）。
- 	emplate_source：master_original / master_adapted / combined / custom；
  dapted_template_ids：组合改造时列出来源模板；	emplate_adaptation：记录改了哪些面板、标签、语义。

### 科学真实性底线

不能造数据；不能把模拟数据当结果；不能改答案迎合图；不能画不存在的关系。模板里的确定性演示数据只用于预览，
绝不能冒充本次 run 的真实结果；正式图只能绑定 current 且 xecution_valid=true 的结果。
