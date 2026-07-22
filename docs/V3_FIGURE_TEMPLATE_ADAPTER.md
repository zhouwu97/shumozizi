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

输出固定为 PNG、PDF、SVG 和 `<prefix>.text-boxes.json`。适配器同时复制冻结的原模板源与本次 v3 渲染器到 `code/figures/`，并在 `figures/index.json` 登记所有输入、脚本、输出的 SHA-256。

## 已接入真实数据接口

只有以下四项能通过此入口生成可进入论文的图；先运行 `python scripts/figures/use_template.py --list` 可确认：

| 模板 ID | `figure_data` JSON 格式 |
| --- | --- |
| `cv-roc-ci` | `{"models":[{"name":"Model A","folds":[{"fpr":[0,0.4,1],"tpr":[0,0.7,1]}]}]}` |
| `prediction-marginal-grid` | `{"series":[{"name":"Validation","actual":[1,2],"predicted":[1.1,1.8]}]}` |
| `paired-raincloud` | `{"groups":[{"name":"Treatment","before":[2,3],"after":[3,4]}]}` |
| `correlation-pairgrid` | `{"columns":["x1","x2"],"values":[[1,2],[2,3],[3,5]]}` |

结果文件可以将这些对象置于 `figure_data`，并同时保留正常的 `metrics` 字段，例如：

```json
{
  "metrics": {"auc": 0.91},
  "figure_data": {"models": []}
}
```

## 演示模板边界

`skills/mathmodel-figure-templates/scripts/render_template.py` 仍可用于验证冻结的 11 套模板能运行，但它输出的是确定性演示数据。该脚本不写入 v3 的 `figures/index.json`，因此不能被论文当作真实图引用。

目前未接入真实数据接口的 7 套模板是布局与改造参考，不得在报告或 PR 中表述为“已完成 v3 接入”。新增适配必须同时具备真实 JSON 数据接口、运行目录内源/输出哈希、文字边界导出、最终 QA 和 smoke test。

## 失效与再生成

若同一问题和结果类型产生了新的成功执行，旧结果会变为 `superseded`。所有引用该结果的 current 图会在 `run_final_checks.py` 的 `current-figure-files` 中失败，直到重新通过适配器生成并登记新图。演示图无论是否存在，均不能通过该检查。
