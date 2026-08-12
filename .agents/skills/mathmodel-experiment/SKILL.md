---
name: mathmodel-experiment
description: 真实执行数学建模实验，比较路线、保存 current 结果、生成可验证图表数据并挖掘结果洞察。
---

# 高价值实验

代码写入 `code/`，输出写入 `results/raw/`，影响路线或论文的实验必须使用执行器登记。前置 probe 使用 `python scripts/runtime/run_simple_experiment.py ... --execution-mode exploration`，它默认 provisional/diagnostic，不能替换 current、正式图、answer-map 或论文。候选胜出后必须从源数据使用 `--execution-mode production` 重跑；没有“无重跑提升”的捷径。生产执行默认检查输出新鲜度，探索执行不以旧输出冒充正式证据。

预算优先给搜索，不给复算。核心问题的搜索与深化耗时必须超过其验证与复算耗时，且核心搜索要占实际算力的 40% 以上——把复算跑成 exploration 不能稀释这条检查。建议分配：主路线深化与候选搜索 60%、竞争路线 15%、机制与敏感性 15%、独立复核 10%。

优先 baseline、区分性 probe 与能推翻当前结论的实验。实验的价值来自改变路线、模型、主要结论、机制解释或贡献，不来自填满敏感性、多种子或收敛图清单。

**图表资产是实验的一级交付物，不是 SECOND STEP 的事后装饰。** 每个核心问题除了数值结果，还必须产出**可画高级图的结果数据**与**正式图本身**：

- **可画图数据（data side）**：按问题特征至少产出两类可支撑高级图型的数据——例如 SHAP 值（分类/回归解释）、区间删失生存/达标曲线（阈值事件时间）、相关矩阵（EDA）、Bootstrap/重抽样分布（不确定性）、校准/PR/ROC 曲线（判别验证）、灵敏度矩阵（决策稳健）。这些数据随 production 结果写入 `results/raw/`，供正式稿直接消费。
- **正式图（figure side）**：用统一风格（seaborn 主题 + 语义调色板 + SimSun/中文字体 + DPI≥300）渲染，优先复用 `.agents/skills/mathmodel-advanced-figures/scripts/render_advanced.py` 的现成模板（`survival_curve` / `shap_combo` / `correlation_heatmap` / `paired_raincloud` / `cv_roc_ci` / `ci_forest` / `group_violin`）；数据支撑多面板时画组合图，不用单面板草率了事。图必须承担数据直觉、机制、决定性证据或边界中的论证角色，不能为了凑图数画装饰图。

**不是配额驱动**：目标是"图种多样、可论证、好看"，不是"凑到 N 张"。实验阶段的图画得越好，SECOND STEP 越不需要重画；实验只画基础折线/柱状而把高级图全部推给 SECOND STEP，等于把最该在数据新鲜时完成的事拖到最后。

在首次 production 前，先执行 `MODELING_UNITS.risk_package` 的最低成本检查，并用 `python scripts/simple/manage_risk_route.py record <run_dir> --question <Q?> --input <risk-assessment.json>` 写回真实结果。所有检查 clear 才按 fast 路线结束普通问题；出现目标分歧、补偿带、留出反转、oracle/硬约束冲突或持续改善时进入 deepening。触发结构攻击后，`claim_boundary` 必须为 `conditional_on_assumption` 或 `sensitivity_only`，正式答案和 Author Pass 会自动继承该边界。

比较必须真的判胜负：赢家由统一 exact scorer 的实测结果决定，核心问题的赢家还要相对 baseline 达到事前声明的显著改善阈值。达不到时继续搜索、换更强路线，或用 `baseline_near_bound` 加实际界证据说明已接近上限。深化后的最终结果不得比比较阶段的赢家更差。路线预期上限明显落空时登记 `upside_shortfall` 的原因与决定，不要继续按原声明叙述优势。

数据建模单元的统计审计不得停在分析文档：所有已采用/拒绝的统计正确替代路线要以真实 production 结果写入 `actual.validation.methodology_result_ids`。`outcome_kind=recommendation` 时不确定性是必需结果：必须另以 production 结果写入 `uncertainty_result_ids`，例如 Bootstrap 区间、删失口径重估、时间窗/阈值/分组切点敏感性；结果必须登记可复述的数值指标或区间端点，供正式稿的 `metric_assertions` 精确绑定。仅在散文中出现“稳健”或“敏感性”不算完成。

核心优化/协同问题出现首个可行解后，不直接投入剩余大预算。先运行 `python scripts/review/show_first_feasible_prompt.py <run_dir> --question <Q?>`，把固定提示交给不继承当前求解上下文的 AI。它只给出最多三项最高风险、一个可推翻假设、是否值得测试结构不同路线、下一项最低成本区分实验，以及 `continue_experiment` / `return_analysis` 决策。将 JSON 回填到当前单元的 `actual.refinement.first_feasible_checkpoint`；reviewer context ID 可选记录，不要求 task receipt。返回 analysis 时先修订并重新取得首解；继续 experiment 时先执行所提区分实验，再追加首解之后产生的 `followup_result_ids` 与 `followup_conclusion`，最后做计划内深化。这不是第二轮综合科学挑战，也不新增状态阶段。

exact 赢家只获得“候选主答案”身份。执行者只登记 `actual_endpoint_resolution` 与 `qualification_evidence` 的真实结果指标：路线升级由 exact 分数和事前阈值计算，endpoint 一致性由最终裁决、合理口径下的路线排序和行动后果计算，guard 与决策稳定性由预登记指标阈值计算。系统据此唯一派生 `promoted`、`fallback_selected` 或 `redesign_required`；不得手填布尔值覆盖结果。endpoint 未决或合理口径导致路线翻转时回到 `analysis`，搜索或验证不足时回到 `experiment`。论文的 `primary_result_id` 必须与系统派生结果一致。

真实结果后可以生成 `analysis/method_facts.json`。它的 true/false/unknown 只触发建议：随机求解器建议多种子，proxy 建议检查 exact 排序，时间切分检查泄漏，连续几何检查端点和离散误差。缺失或 unknown 绝不阻断。

规律挖掘和实验同等重要。核心问题必须产出带 `insight_id` 的结构化规律，每项记录观察、机制、真实结果证据和边界；其中至少一条属于机制、边际收益、活跃约束或权衡——只有反直觉描述不算理解。同时写 `analysis/INSIGHTS.md` 作为可读版本。任何反例、独立复算冲突、不可行、性质失败或更优 incumbent 都先让相关结果、图表和论文失效。
