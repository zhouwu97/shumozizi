# 模型原生视觉模式卡

先写数学对象和视觉问题，再选 archetype。图形必须消费模型同次运行输出的结构数据，不能从最终标量反推可行域、置信带或机制。

| 数学结构 | `visual_archetype` | 模型必须输出 | 图中必须出现 |
| --- | --- | --- | --- |
| 空间几何/覆盖 | `spatial_scene_with_constraints` | 对象坐标、边界、交点、候选与最终布局 | 坐标、方向、障碍/目标、约束、最终方案；再配准确二维剖面 |
| 空间轨迹/事件 | `spatial_trajectory_with_constraints` | 时标轨迹、事件点、可行区、控制量 | 起终点、时间颜色、事件、速度方向、边界和局部放大 |
| 多目标优化 | `pareto_feasible_region` | 全部候选、可行标记、Pareto 标记、baseline/fallback/最终点 | 支配关系、前沿、约束边界、折中点和选点理由 |
| 参数优化 | `response_surface_with_constraints` | 参数网格、exact 目标、约束违反量、最优点 | 响应面/等高线、不可行区、敏感方向和局部剖面 |
| 分组与规则决策 | `decision_surface_with_fallback` | 参数到动作映射、样本密度、阈值、fallback | 决策区域、切换边界、稀疏区和 fallback 区 |
| 不确定性 | `uncertainty_fan_with_threshold` | 样本轨迹或分位数、阈值、切换事件 | 中位数、50/80/95% 区间、尾部、临界线和切换时刻 |
| 网络与流 | `network_flow_bottleneck` | 节点、边、容量、流量、瓶颈与主路径 | 拓扑、方向、边权、瓶颈、主路径；不用无意义弦图装饰 |
| 时空数据 | `spatiotemporal_density` | 位置、时间、强度、边界 | 空间位置、时间编码、密度/强度与区域边界 |
| 分类模型 | `classifier_diagnostic_bundle` | bootstrap 预测、阈值、校准分箱、业务代价 | PR/ROC 区间、校准、阈值和决策代价；类别不平衡优先 PR |
| 聚类 | `cluster_structure_embedding` | 嵌入、簇标签、轮廓值、原变量摘要 | 类间/类内结构、样本密度和原变量解释 |
| 方程与动力学 | `phase_field_bifurcation` | 状态轨迹、向量场、平衡点、参数扫描 | 稳定点、流向、状态转移、分岔和参数边界 |
| 数值搜索 | `search_trajectory_envelope` | 多种子历史、候选参数轨迹、预算和停机点 | best/median/quantile 包络、预算、方差、参数空间移动 |
| 时间集合/调度 | `interval_event_timeline` | 区间端点、并交关系、资源占用和临界事件 | 区间带、暴露缺口、资源冲突、临界事件和最终调度 |
| 几何剖面 | `geometric_section_projection` | 三维对象、剖切平面、交线和投影误差 | 关键剖面、交点、遮挡/覆盖边界和三维位置对应 |
| 活跃约束 | `feasible_region_active_constraints` | 候选点、可行标记、约束余量和最终点 | 可行域、活跃边界、不可行方向、baseline/fallback 和最优点 |
| 状态—控制—事件 | `state_control_event_timeline` | 状态轨迹、控制量、事件和阈值 | 状态、控制、触发事件、阈值和行动切换的同步关系 |
| 联合论证 | `multi_panel_evidence_chain` | 各面板共享 ID 的结构数据 | 2--4 个紧密关联面板：模型结构→优化→误差/不确定性→baseline |
| 仅路线得分 | `route_score_comparison` | 路线指标 | 只适合次要对照；不能替代主模型结构图 |

## 选择规则

1. 空间或场的第三维有数学含义时才用 3D，并提供剖面/投影帮助精确读数。
2. 二参数优化优先“曲面或等高线 + 不可行区 + 最优点 + 敏感方向”，不是裸 `surf`。
3. 多目标问题先画 Pareto 与可行域；算法得分柱形图只能作次要证据。
4. 动态问题同时呈现状态、控制和事件；单条目标值折线不能解释控制机制。
5. 不确定性问题必须显示区间、概率或尾部；均值曲线不够。
6. 多面板只用于一条连续证据链，不为凑图数拼接无关图。

## 评委视角复核

逐图检查：核心对象是否看得见；最优点为什么形成；哪个约束激活；fallback 在哪里；不确定性是否可能改变决策；图是否重复表格；3D 是否遮挡关键点；热力图是否只是彩色数字表；图后正文是否按“观察→机制→决策后果”闭环。任一核心问题若只能看到方法得分而看不到主模型，应返修模型输出和图形设计。
