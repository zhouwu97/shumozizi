---
name: mathmodel-experiment
description: 在 Capability-First v3 中编写、实际运行和调试数学建模实验，保存可追溯结果、图表和按题型选择的验证；用于整题或已明确的子问题实验。
---

# 真实执行与有信息量的实验

实验的职责是回答题目、验证关键主张和及时发现失败路线，不是完成固定的实验清单。

## 开始前

1. 读取 `state/run.json`、相关段落的 `DECISIONS.md` 和 `ANALYSIS_MODELING_REPORT.md`；只加载当前问题需要的数据与知识。
2. 为当前问题先建立可运行的最小 baseline 或可行性 probe，再决定是否投入复杂主模型。模型选择矩阵只提供候选，不能代替路线比较。
3. 将代码写入 `code/`，原始输出写入 `results/raw/`，论文图写入 `figures/`。不要把模拟示例数据当作真实结果。

## 执行与结果记录

每次需要进入论文或支撑重要判断的运行，都使用 v3 执行器：

```powershell
python scripts/runtime/run_simple_experiment.py runs/<run-id> `
  --question Q2 --kind primary --result-id q2_primary `
  --command "python code/q2.py" --expect results/raw/q2.json `
  --input problem/attachments/data.xlsx `
  --metrics-from results/raw/q2.json
```

脚本应将指标写入输出 JSON，例如 `{"metrics": {"objective": 123.45}}`。执行器使用 `shell=False`，从该输出自动提取指标并记录 JSON 路径和 SHA-256；不接受自由手填指标。只有 `results/index.json` 中 `status=current` 且 `execution_valid=true` 的条目可以作为论文事实候选；这只证明执行与文件仍可复验，不代表科学结论已获认可。新结果会把同问同类型旧 current 结果标为 `superseded`。

不要预写复杂 manifest、不要伪造指标，也不要把一次正常退出解释为模型优秀。非零退出、缺少输出、空输出或损坏 JSON 必须修复或如实记录失败。

## 验证按主张选择

只做能改变决策的最低成本实验：

- 预测/回归：切分与泄漏、baseline、泛化误差、残差、外推边界或不确定性；
- 分类：类别不平衡、宏 F1 或 PR-AUC、阈值、混淆矩阵、正类正控制、校准；
- 优化：可行性、目标值、简单 baseline、多初值或界、扰动、极端场景、运行时间；
- 机理/反演：合成恢复、已知真值、可辨识性、多初值、极限状态、误差传播；
- 评价/排序：权重来源与方向、权重扰动、排名翻转、替代方法和稳定区间。

不要求每题都有 baseline、primary、robustness 三种名字；但每个关键结论都必须有合适的反证、对照或边界说明。

## 每问结束时

在 `DECISIONS.md` 追加：当前结果、正控制、相对 baseline、是否直接回答题目、最可能失败原因、最低成本下一实验，以及“继续 / 修复 / 切换 fallback / 停止”的决定。然后更新 `reports/RESULTS_REPORT.md`。

实现错误直接修；参数或求解器问题路线内调整；fallback 更优则切换并记录。若结果无法回答题目，明确失败边界，不得用图表或论文措辞包装为成功。

## 按需科研绘图能力

`mathmodel-experiment` 同时是代码与科研可视化能力入口。生成图表前，先为每张主要图填写 Figure Contract，并按需读取：

- `skills/3coding-visual/SKILL.md`：把模型实现、真实运行、结果表和数据驱动图表组成可复现实验；
- `skills/mathmodel-figure-templates/references/figure-catalog.md`：在需要多面板或专业统计表达时匹配最接近的模板；
- `skills/mathmodel-figure-templates/references/plot-recipes.md`：仅在复制模板后需要改造布局或统计表达时读取。

普通折线图、散点图、箱线图或热图已能清楚回答问题时，优先使用普通图。只有 Figure Contract 的问题、证据结构和当前结果数据同时匹配时，才调用科研模板。`render_template.py` 只生成演示数据，不能进入论文；v3 的真实数据入口是：

```powershell
python -m pip install -e ".[figures]"
python scripts/figures/use_template.py runs/<run-id> `
  --template cv-roc-ci `
  --result-id q3_classifier `
  --output-prefix figures/q3_cv_roc
```

适配器只接受 `results/index.json` 中仍为 `current` 且 `execution_valid=true` 的 JSON 输出；会把冻结模板源和本次渲染器复制到 `code/figures/`，并登记输入、脚本、PNG/PDF/SVG 与文字 artist 边界的哈希。当前已接入真实数据接口的模板只有 `cv-roc-ci`、`prediction-marginal-grid`、`paired-raincloud`、`correlation-pairgrid`；其他七套仅是保留的演示/布局资源，不能被称为已接入。

结果 JSON 把图表数据放在 `figure_data`（或直接置于根对象）。具体格式和示例见 `docs/V3_FIGURE_TEMPLATE_ADAPTER.md`。源结果被同问同类的新执行替代后，旧图会在最终检查中阻断，必须重新生成。完成后在 `RESULTS_REPORT.md` 说明该图回答的问题、数据来源和证据边界。
