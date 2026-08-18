# v3 科研绘图模板适配器

该适配器将**已登记的真实执行结果**渲染为可追溯图表。它不自动选择模板，也不把图表当成科学质量证明；选择仍由当前题的证据需求和论证角色决定。

## 使用方式（渲染与登记分离）

```powershell
python -m pip install -e ".[figures]"

# 第一步：渲染 work 候选（不登记）
python scripts/figures/use_template.py runs/<run-id> `
  --template nature-chord-diagram `
  --result-id q3_classifier `
  --output-prefix figures/work/q3-chord/v1/q3-chord `
  --adaptation direct

# 第二步：打开真实 PNG 看图，确认 layout_report 的 needs_human_confirmation 字段，
# 写 human-review JSON，再晋级 current（命令由第一步输出给出）
python scripts/figures/promote_figure_candidate.py runs/<run-id> `
  --figure-id q3-chord --candidate figures/work/q3-chord/v1/q3-chord.png `
  --candidate figures/work/q3-chord/v1/q3-chord.pdf `
  --target-stem figures/current/q3-chord --rendering-mode plot `
  --layout-report figures/work/q3-chord/v1/q3-chord.layout_report.json `
  --visual-manifest figures/work/q3-chord/v1/q3-chord.visual_manifest.json `
  --figure-role insight --human-review <review.json>
```

`--result-id` 必须是 `results/index.json` 中 `status=current` 且 `execution_valid=true` 的条目。默认只在其恰有一个 JSON 输出时使用该输出；有多个 JSON 输出时，以 `--input-result results/raw/<file>.json` 明确选择。

渲染产出 `figures/work/<figure-id>/<version>/` 下的 PNG/PDF/SVG，并**机器生成**
`<prefix>.text-boxes.json`、`<prefix>.visual_manifest.json` 与 `<prefix>.layout_report.json`
（论文尺寸、字号、坐标范围、图例遮挡均从 Figure 提取；`needs_human_confirmation` 列出
色盲安全/语言一致性/结论标注等必须由人工看图确认的字段）。渲染阶段不登记，晋级走
`promote_figure_candidate.py`；旧 v3.1 运行的一次性登记仍由 `generate_from_result` 保留。

## 三种适配模式（sci-box 母版优先）

| `--adaptation` | 行为 | 何时使用 |
| --- | --- | --- |
| `direct`（默认） | **复制 sci-box 母版原脚本**（`skills/sci-box/scibox-figure/scripts/templates/make_<id>.py`，上游 jihe520/sci-box 原样副本）到 `code/figures/adapted_<id>.py`，进程内**先注入** `_real_data_<id>.py` shim（把 `simulate_*()`/模块常量替换为真实结果）**再调用 make_figure**，原样保留绘图结构。无 shim 时自动转 manual-copy，**绝不静默回退**到简化 reimplemented。 | 首选；母版结构能直接表达本题结果时。 |
| `auto` | direct 安全时原样适配，否则自动进入 `master_adapted`。 | 默认入口；优先保留高级母版视觉语法。 |
| `adapted` | 复制原脚本并由真实数据 shim 改造面板、尺度和语义，保留母版布局。 | direct 前提不满足但母版仍适合当前结果时。 |
| `manual` | 复制原脚本 + 写入标记好的数据入口 stub（`TODO(manual adaptation)`），不运行、不登记。 | 仅在需要人工重排且尚无自动适配器时显式使用。 |
| `reimplemented` | 本仓 v3 渲染器（`src/shumozizi/simple/figure_templates.py`）简化重绘。 | 明确要求才用；不作为默认路径。 |

`direct` 是“**用了人家的模板**”的唯一正确姿势：母版脚本的版式（面板几何、字号、轴线、
图例、间距、注释）是人工设计好的成品，只允许换数据入口和少量调整（标签、变量数、重点），
禁止默认重新实现。

**但 direct 不只看“有没有适配代码”，还要看“当前数据是否满足母版暗含的数学/视觉前提”。**
每个可 direct 的母版都带语义校验器（`DIRECT_ADAPTERS`），不满足前提直接拒绝并指引
manual/master_adapted：

| 母版 | 数据前提（校验器） |
| --- | --- |
| `correlation-pairgrid` | 任意量纲真实数据由 shim 按列 z-score（母版散点轴固定 [-3.1, 3.1]） |
| `grouped-corr-split-violin` | 恰好 13 列；Train/Test 图例与 Substrate/Biomass/Operation 括号由数据驱动（未提供 `feature_groups` 则删除括号） |
| `nature-chord-diagram` | ≥3 节点、有效正权边 |
| `taylor-diagram` | 恰好 3 面板、corr∈[0,1]（母版会把负相关截断为 0）、std/reference_std≤1.7（rmax=1.75 会裁点） |

**已移出 direct（必须先 master_adapted 剥离源论文语义才能恢复）：**
- `rf-tpe-surface`：母版把曲面混合成 `0.58×IDW(真实 trials) + 0.42×true_rmse_surface()`，
  其中 `true_rmse_surface` 是源论文的演示函数，且固定 grid/norm/axis/ticks；
- `grouped-circular-heatmap`：外围写死 `Brain Phenotype N`、`Normalize(-5,5)` 与
  `abs(values)>4.1 → "*"` 固定显著性星号规则，会把不存在的科学含义带进论文。

direct 渲染还会生成**可独立复现的 driver**（`code/figures/render_<id>.py`：母版 + shim +
真实数据 + `make_figure`），它就是正式 renderer_script，未来直接 `python render_<id>.py`
即可重新得到同一张正式图。

选图优先级（`skills/sci-box/scibox-figure` 的决策顺序）：
① sci-box 原生母版 → ② 模板深度改造/组合 → ③ scibox-diagram 结构图 → ④ 本题专用高级图 →
⑤ 普通 scatter/heatmap/line → ⑥ bar。柱状/折线不是禁止，而是能表达清楚就不准偷懒。
选模板前必须打开 `skills/sci-box/scibox-figure/assets/previews/` 的 preview 实际看图，
禁止只凭模板 id 名称选图。

结构解释图（技术路线/研究框架/阶段流程/任务流水线）由 `skills/sci-box/scibox-diagram` 承担，
它是一等候选：模板 id 为 `roadmap-5band` / `framework-3col` / `stageflow-3col` / `taskflow-land` /
`custom` / `replica`，产出 `.drawio` + PNG/PDF，在 `figures/work/` 迭代后晋级 `figures/current/`。

## 已接入真实数据接口

图库的 15 套模板均已接入真实数据接口；v3.4 另提供 5 个结构别名。运行以下命令取得当前机器目录，不再从本文手工统计数量：

```powershell
python scripts/figures/use_template.py --list
python scripts/figures/use_template.py --catalog
python scripts/figures/use_template.py --recommend optimization
```

`--catalog` 同时给出中文标题、分类、参考脚本、可用预览、真实 renderer 状态、`use_when`、`avoid_when`、`evidence_role`、`required_data_summary`、`min_paper_width_cm`、`preview_fidelity`、`adaptation_level` 和 `grayscale_readability`，可直接供 Agent 或图库前端消费。

`preview_fidelity` 不与 `renderer_available` 混用。`needs_visual_refinement` 只是视觉备注，不再把母版移出 `--recommend` 的主候选；候选会附带 `recommended_action`（`direct` 或 `master_adapted`）和 `adaptation_need`，最终以真实 PNG 复核决定。

| 模板 | `figure_data` 必需结构 |
| --- | --- |
| `cv-roc-ci` | `models[].name/folds[].fpr/tpr` |
| `prediction-marginal-grid` | `series[].name/actual/predicted` |
| `paired-raincloud` | `groups[].name/before/after` |
| `correlation-pairgrid` | `columns/values` |
| `multiclass-shap-combo` | `features/classes/mean_abs_shap/beeswarm[]` |
| `taylor-diagram` | `reference_std/panels[].title/points[].name/std/corr` |
| `rf-tpe-surface` | `x_label/y_label/metric_label/direction/trials[].x/y/metric` |
| `grouped-corr-split-violin` | `features/groups[2].name/values` |
| `grouped-circular-heatmap` | `items/rings[].name/values` |
| `nature-chord-diagram` | `nodes[].id/label/group` 与 `links[].source/target/weight` |
| `urban-park-cooling-combo` | `categories/components[].name/values/metrics[].groups[]` |
| `feasible-region-active-constraints` | `points/feasible_mask/boundaries/active_constraints/selected_point` |
| `interval-event-timeline` | `intervals/events/final_intervals` |
| `uncertainty-fan-threshold` | `x/median/bands/threshold` |
| `multi-panel-evidence-chain` | `panels[2..4].panel/title/takeaway/argument_unit_id/kind/data` |

结果文件可以将这些对象置于 `figure_data`，并同时保留正常的 `metrics` 字段，例如：

```json
{
  "metrics": {"auc": 0.91},
  "figure_data": {"models": []}
}
```

## 演示模板边界

`skills/mathmodel-figure-templates/scripts/render_template.py` 可验证 15 套冻结模板并生成 Sandbox 草图，但它使用确定性演示数据，不写入 v3 的 `figures/index.json`，因此不能被论文当作真实图引用。

正式图只能由本文入口读取 `current`、`execution_valid=true` 且通过质量层的结果。新增模板仍须同时具备真实 JSON 数据合同、运行目录内源/输出哈希、文字边界、视觉清单、人工 QA 和 smoke test。

高级结构必须服从证据边界：RF/TPE 曲面只可表述为真实 trials 之间的插值展示；SHAP 模板只消费实际计算的 SHAP；Taylor 图中的模型必须共享同一参考标准差；和弦、环形热图仅在真实关系、周期或环结构存在时使用。相关人工审图分层见 `evaluation/figure-template-audit/audit.json`。

## 失效与再生成

若同一问题和结果类型产生了新的成功执行，旧结果会变为 `superseded`。所有引用该结果的 current 图会在 `run_final_checks.py` 的 `current-figure-files` 中失败，直到重新通过适配器生成并登记新图。演示图无论是否存在，均不能通过该检查。
