# 高级图目录（按数据特征挑图种）

不要从图库名称反推图；先问"这个结果是什么数据特征"，再在这里找对应图种。
每张图必须能回答：解释什么、读者一眼看见什么、删除后论文失去什么。

## 关系 / 相关性

- 相关系数热力图、成对关系图 pairplot、聚类热图 clustermap、六边形分箱 hexbin、二维 KDE 等高线
- 适用：多变量之间的相关性、代理面、参数耦合

## 分布

- 小提琴图 violinplot、山脊图 ridgeline、联合分布 jointplot、雨云图 raincloud、蜂群图 swarmplot、ECDF、直方图叠密度
- 适用：组间分布对比（如 Q1 各组的间隙分布）、随机配置统计、蒙特卡洛样本分布

## 概率 / 统计推断

- 置信区间误差带、森林图 forest plot、bootstrap 分布
- 适用：Q2/Q3/Q4 的点估计与 Wilson 区间、多验证对比、复验证据

## 优化 / 运筹

- 帕累托前沿 Pareto front、可行域与约束图、成本等高线/等值线 contour、收敛曲线、算法对比
- 适用：Q4 整数可行域与成本前沿、Q3 阈值寻根、优化搜索

## 时间序列 / 收敛

- 收敛带、样本量-区间收缩、时序分解、自相关 ACF/PACF、堆叠面积流 streamgraph
- 适用：蒙特卡洛收敛、稳定性、样本量证据

## 仿真 / 概率演化

- 概率密度演化、蒙特卡洛散点云、相图、流线图
- 适用：渗流概率随体积分数演变、物理过程

## 网络 / 结构

- 网络图 networkx、弦图 chord、树状聚类 dendrogram
- 适用：Q1 接触网络、导电骨架、图结构

## 模型诊断

- 灵敏度龙卷风图 tornado、残差图、Q-Q、ROC/PR、校准曲线、特征重要性/SHAP、PDP
- 适用：阈值/参数敏感性、判定器验证、模型选择

## 多目标 / 决策

- TOPSIS/熵权法排序图、AHP 权重图、雷达图、平行坐标、桑基图 Sankey
- 适用：方案权衡、成本-概率-稳健性多维比较

## 风格统一

所有图复用 `scripts/style.py` 的 `apply_competition_style()`：seaborn 主题 + 统一调色板 +
SimSun 中文字体 + DPI≥300。颜色语义：正式答案深青、阈值金色虚线、敏感性灰、不可行暖红、骨架蓝。

## 即用模板索引（`render_advanced.py --template`）

先完成 [contract.md](contract.md) 五点合同，再按下表选模板。每个模板读
current production 结果 JSON 的字段（见下），**不模拟、不硬编码**。

| 模板 id | 论证角色 | 读入字段 | 典型来源 |
|---|---|---|---|
| `survival_curve` | 机制/决定性证据 | `groups[].points[]{x,probability,ci_lower,ci_upper}` + `threshold` | 区间删失 AFT 达标曲线（Q2/Q3） |
| `ci_forest` | 边界/稳健性 | `rows[]{label,estimate,low,high}` + `threshold` | Bootstrap/扰动后的推荐时点区间 |
| `probability_curve` | 机制/边界 | `points[]{x,probability,ci_lo,ci_hi}` + `threshold` | 单组达标比例与阈值带 |
| `group_violin` | 数据直觉 | `groups[]{group,values[]}` 或 `{group,estimate,ci_lo,ci_hi}` | 组间分布对比 |
| `paired_raincloud` | 数据直觉/边界 | `groups[]{label,values[]}` | 正常/异常样本特征分布 |
| `correlation_heatmap` | 数据直觉 | `matrix[[]]` + `labels[]` | 关键变量相关矩阵（EDA） |
| `cv_roc_ci` | 决定性证据 | `fpr[],tpr[],ci_lower[],ci_upper[]` + `auc` + `operating_point` | 分类器留出/交叉验证 ROC |
| `shap_combo` | 机制/解释 | `shap_values[[]]` + `feature_names[]` + `feature_values[[]]` | Elastic-Net/树模型 SHAP |
| `feasible_region` | 边界/决策 | `lattice_points[]{x,y,feasible,cost}` | 优化可行域 |
| `pareto_frontier` | 权衡/决策 | `candidate_points[]{cost,probability,ci_lo,ci_hi,label}` | 成本—可靠性前沿 |

结构解释图（路线图/问题递进/机制判定）走 `render_structure.py`，见 structure-spec.md；
`argument_role=decisive_evidence` 不接受结构图。
