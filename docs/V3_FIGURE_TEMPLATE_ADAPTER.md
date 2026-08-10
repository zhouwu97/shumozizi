# v3 科研绘图模板适配器

该适配器将**已登记的真实执行结果**渲染为可追溯图表。它不自动选择模板，也不把图表当成科学质量证明；选择仍由 Figure Contract 和当前题的证据需求决定。

## 使用方式

```powershell
python -m pip install -e ".[figures]"

python scripts/figures/use_template.py runs/<run-id> `
  --template cv-roc-ci `
  --result-id q3_classifier `
  --output-prefix figures/q3_cv_roc
```

`--result-id` 必须是 `results/index.json` 中 `status=current` 且 `execution_valid=true` 的条目。默认只在其恰有一个 JSON 输出时使用该输出；有多个 JSON 输出时，以 `--input-result results/raw/<file>.json` 明确选择。

输出固定为 PNG、PDF、SVG、`<prefix>.text-boxes.json` 和 `<prefix>.visual_manifest.json`。适配器同时复制冻结的原模板源与本次 v3 渲染器到 `code/figures/`，并在 `figures/index.json` 登记所有输入、脚本、输出的 SHA-256。

## 已接入真实数据接口

图库的 15 套模板均已接入真实数据接口；v3.4 另提供 5 个结构别名。运行以下命令取得当前机器目录，不再从本文手工统计数量：

```powershell
python scripts/figures/use_template.py --list
python scripts/figures/use_template.py --catalog
python scripts/figures/use_template.py --recommend optimization
```

`--catalog` 同时给出中文标题、分类、参考脚本、可用预览、真实 renderer 状态、`use_when`、`avoid_when`、`evidence_role`、`required_data_summary`、`min_paper_width_cm`、`preview_fidelity`、`adaptation_level` 和 `grayscale_readability`，可直接供 Agent 或图库前端消费。

`preview_fidelity` 不与 `renderer_available` 混用：`preview_grade` 表示高级结构通过本轮人工视觉晋级；`safe_adapted` 表示证据语义可靠但不宣称等同参考预览；`needs_visual_refinement` 只进入 `refinement_queue`，不会被 `--recommend` 自动列为高级成品。推荐入口覆盖 optimization、uncertainty、classification、distribution、network/flow 和 temporal，但结果只作建议；Hero 图按整篇论文主线选择，不按每个问题强行配置高级图。

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
