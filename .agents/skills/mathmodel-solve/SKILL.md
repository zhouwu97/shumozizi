---
name: mathmodel-solve
description: 解析数学建模题面与附件，比较候选目标的策略后果，比较 baseline 和竞争路线，设计区分性 probe、主路线与 fallback。
---

# 路线竞争

分析前置阶段可按需运行 `python scripts/challenger/run_bzd_translator.py <run_dir>` 生成 `analysis/external/bzd-problem-ledger.md`，执行逐句题意翻译、明示/隐含条件提取与全问 Mermaid 联动图审计，确保零遗漏；题面原句为一级硬事实，推论需经忠实度核验。

先比较相邻问题新增的实体、资源、共享约束和聚合层，再区分题目对象、目标、约束、单位、输出和问题依赖。低风险题只做一次忠实重建，覆盖决策变量、成功事件、聚合和输出；任一问题要求重查聚合或 endpoint 尚待比较时，再增加一次语义攻击，专查量词次序、和/最小值/并集/交集、前问目标机械复制与分解失效，并构造能让两个解释排序相反的最小反例。重建结论是科学输入，线程回执和题面树哈希只作独立性记录；多份重建一致只说明共识，不证明正确。

对于核心优化/协同题，可在独立上下文调用 `python scripts/challenger/run_bzd_challenger.py <run_dir>` 生成候选路线 `analysis/external/bzd-route-candidates.md`；严禁向其泄露本地主路线或代码。抽取具备实质数学结构差异的路线 B/C，与主路线 A 一同排入 `analysis/ROUTE_COMPETITION.md`，在同一 Exact Scorer、同等数据和计算预算下运行最低成本 Probe 与真实实验，由实测证据决定胜负。

每个必答问题在提出复杂模型前先写直接答案合同，并进入 `MODELING_UNITS.json`：

- `required_output`：最终必须交付的数值、区间、分类、策略或解释；
- `decision_scope`：决策对象、目标总体、时间窗与适用场景；
- `primary_endpoint`：主估计量/主终点的名称、数学定义及其与 exact metric 的对应；
- `primary_criterion`：什么实测条件足以支持主答案；
- 自然 baseline 及其合理性；
- fallback 与可执行切换条件。

主终点必须在正式路线比较前显式声明。若 endpoint/聚合口径仍有合理歧义，标记 `comparison_planned`，登记至少两个候选 endpoint、题面依据和裁决规则，并运行候选后果 probe。实验结束必须写出 `actual_endpoint_resolution`；合理 endpoint 下路线翻转、行动漂移越界或缺少题意裁决依据时，答案资格由系统判为 `redesign_required / analysis`，不能降级成普通敏感性说明。

新运行使用 `MODELING_UNITS` 1.4。每问在答案合同前填写轻量 `question_delta`；新增实体、资源、共享约束、聚合词或分解后组合时必须重新检查目标。`primary_endpoint` 同时用自然语言和公式声明原子成功、实体内、资源间、实体间、时间和量词次序六项聚合。高风险问题复用这一处 `semantic_counterexample`，不在其它协议重复抄写。高风险核心问题在任何路线搜索前先运行 3--5 个人工评分案例，包括同时满足、错开满足、单主体长期满足、总量高但瓶颈为零，以及必要时多资源联合成功；评分器未按预期排序时先改 endpoint/scorer，不比较优化器。

每个核心问题还要把最高价值的前置攻击写入同一单元的 `risk_package`，可先用 `python scripts/simple/manage_risk_route.py plan <run_dir> --question <Q?> --auto` 生成模板后按题意修订。包中必须声明三类主张标签 `unconditional`、`conditional_on_assumption`、`sensitivity_only`、快速路线的四个进入条件、深化触发条件和每项检查的决策价值；它不是新状态门。逆问题用 profile、近优集合和补偿带攻击唯一性；多主体/分解用联合 scorer 最小反例；时间序列用连续留出或滚动留出；模型比较使用共同数据窗口、切分、scorer、预算和事前门槛。攻击推翻唯一性时，实际回填必须把结果标为条件结果或范围，不能只在局限性中补一句。

目标候选使用 `OBJECTIVE_CANDIDATES` 1.1，顺序固定为“题面合法性 -> 同源反例区分 -> 仍合理候选的策略后果”。每个候选先声明题面原句、保留/改变的量词、引入的价值偏好、是否只为方便求解，并分为直接支持、合理假设支持、仅敏感性或与题意不符；只有前两类能成为正式目标。仅剩一个合法候选时不强迫跑多目标实验；仍有两个及以上时，才用共同的效率与公平/瓶颈/安全指标跑低成本后果 probe。高风险问题不能靠一句 `determined_basis` 跳过：必须明确正式目标、一个被拒绝替代及拒绝理由，并由 `MODELING_UNITS` 中的反例区分。

标出决定奖项上限的核心问题（`core_question=true`）。核心问题必须事前声明 `significant_improvement_ratio`，其竞争路线还要写清结构利用方式和可量化的 `expected_improvement_ratio`——纯文字的"高上限"事后无法与实测对照。`significant_improvement_ratio` 必须同时声明 `threshold_provenance`（prompt_defined/domain_sourced/data_estimated/utility_optimized/engineering_heuristic）：工程启发式阈值必须给理由并做敏感性，不得作为强结论唯一依据。

**每个 v1.4 单元必须填写 `formalization_diff`，把"题面原句 → 正式目标"的转换显式化。** 转换类型只能是 equivalent / surrogate / relaxation / assumption；`silent_replacement`（把"风险最小化"静默换成"可靠性达标后最早"这类题面目标替换）直接阻断。surrogate/relaxation/assumption 必须同时声明 `support_level`（direct/assumption_supported 才够格作正式目标）与 `added_semantics`/`removed_semantics`/`equivalence_evidence`。下游 GEE/AFT/Logistic/敏感性再严谨，也不能补回在形式化阶段被替换掉的原题目标——这是最危险的故障点。

**正式路线比较前先跑冷启动目标忠实度门**：用 `python scripts/review/show_formalization_fidelity_prompt.py <run_dir>` 生成提示，交给完全隔离、未参与建模的新上下文 reviewer，只读原题 + 合同投影，逐项核验题面要求的决策变量、目标量、输出是否仍在正式目标里。返回 `silent_replacement` 时必须回到 analysis 重定义目标，禁止带着漂移目标进入 experiment。

**决策单元（optimization/coordination）的 `answer_contract` 必须声明 `infeasible_policy`**（无可行解的决策闭环）：严格结果、不可行集合内备用决策、备用时点可达可靠度、复检策略、可靠性敏感性（如 q=0.85/0.90/0.95）。只回答"窗口内无解"等于把决策责任甩回评委；也不许硬塞伪造可行解。

**当正式目标是首次达标/事件时点（`estimand_kind=event_time`）时**，用来判定主模型与 challenger 的指标必须与目标同构——时间依赖 Brier、landmark calibration、区间删失似然，而不是记录级 Brier。避免"估的是时点、比的却是单记录概率"的指标错位。

**v1.4 数据质量合同 `data_quality_contract` 强制四类硬约束**：
- `uncertainty.replications` 报 95% 区间时必须 >= 500（优先 1000+）；30 次会在极值样本间插值形成伪稳定。
- `decision_weights` 中的风险/损失权重必须是可调参数并给出 `weight_sensitivity` 区间敏感性，禁止单一常数（如漏检=4）作唯一结论依据。
- 决策单元若做分组/切分（如 BMI 分组），必须声明 `partition_optimization`（动态规划/贪心分段/优化目标决定组数），禁止纯分位数启发式。
- 前瞻推荐必须声明 `future_information_bound`：只使用决策当时可得变量，测序质量等事后才知的信息不得用于推荐时点。

先按任务类型分流：`evaluation`、`data_modeling` 和 `simulation` 使用主方法、自然核对与题型验证，不伪造路线赛马；`exact_oracle` 核对正式指标容差与区间/集合结构；只有 `optimization`、`coordination` 默认提出自然 baseline 和一条数学结构不同的 challenger。不要把只更换求解器的 GA、PSO、DE 当成不同数学路线，但 MATLAB 的结构优化器可以作为同一路线内的异构实现、独立 challenger 或 oracle。每条真实竞争路线说明结构差异、最低成本 probe、潜在上限、失败方式和切换条件，写入 `analysis/ROUTE_COMPETITION.md`。

对 `data_modeling`，先做“统计正确性审计”，再选主方法：在 `data_contract.methodology_audit` 写清数据生成过程、观测过程、时间/删失、重复测量或层级依赖、函数形式风险及未使用字段的处理。并在 `data_contract.outcome_kind` 显式写 `recommendation` 或 `descriptive`，不得从题目文字猜测。`statistically_valid_alternatives` 中的每条候选都必须说明它处理的风险、采用/拒绝/仅作敏感性的理由，以及可实际运行的区分检查；不能拿更简单的 OLS、固定阈值或单因素模型充当必然落败的 challenger。`outcome_kind=recommendation` 一律预登记 `recommendation_uncertainty.required=true`、具体区间/重抽样/重估方法；只有纯关系刻画的 `descriptive` 才可声明 `false`，并说明没有推荐对象的理由。

对 `optimization`、`simulation`、`exact_oracle` 和 `coordination`，必须先使用 `mathmodel-matlab` 完成能力选择。默认运行 `python scripts/capabilities/detect_tools.py <run_dir>`，在单元中写 `capability_decision`：`python_considered`、`matlab_considered`、`matlab_availability`、`tooling_sha256`、`selected_engine`、`matlab_role`、`probe_waiver`、`reason` 和 `expected_gain`。不接受 `not_probed`；真实探测可用或不可用时绑定当前 tooling 哈希，只有解析解、小规模精确枚举、外部引擎被环境禁止或不能形成异构科学增益时才允许 waiver。MATLAB 可以不入选，但必须说明它为什么不能改善当前路线或证据。

任何“分别求解再组合”的路线都必须声明为 `exact_decomposition`、`heuristic_decomposition` 或 `initialization_only`；精确分解给出等价依据，后两者必须继续接受联合 scorer 改进。无法证明可分、小规模对照不一致且又不继续联合优化时，不得把各子问题最优写成全局最优。

将有决策价值的实验排进 `analysis/NEXT_EXPERIMENTS.md`：它必须明确成功或失败会改变什么，以及失败后回到 analysis 还是 experiment。优先运行区分性 probe，再冻结主路线与 fallback。只登记用于资格计算的真实指标和阈值，不手填晋级结论。连续两轮不能超过 baseline、复杂度上升没有实质收益、优势只在 proxy、endpoint 排序翻转、guard 跌破下限或行动方案不稳定时，不得把弱赢家包装成最终建议；名义答案稳定时继续推荐题面赢家，只有不稳定或题面答案不可用时才选择已验证 fallback，或返回 analysis/experiment 重设计。

当单一加权分数掩盖效率、公平、瓶颈或安全冲突时，优先报告可靠性约束下的最优解、真实 Pareto 后果，或稳健/最小后悔决策。最终只保留一个主答案和一个明确 fallback，不并列多个同等地位答案让评委替作者决策。

仅当存在至少两个合理解释且会改变主要结果、题面不能排除、用户尚未裁决时，记录到 `analysis/objective-ambiguities.json` 并触发独立目标语义审查。
