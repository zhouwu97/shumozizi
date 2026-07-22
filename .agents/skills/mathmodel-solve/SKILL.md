---
name: mathmodel-solve
description: 解析数学建模题面与附件、识别数学本质、比较候选路线并形成主路线和 fallback；用于 Capability-First v3 的分析与建模阶段。
---

# 题目解析、路线比较与连续建模

只处理当前赛题，输出能直接指导实现的连续建模报告，而不是审批申请。

1. 读取题面、附件摘要、`state/run.json` 和已有决策。先分解所有必答问题、问题间依赖、数据字段/规模/缺失/单位，以及题意歧义。
2. 先做结构预检：列守恒量/上下界/极端情形，尝试消元或可行重参数化，辨别可分解和事件驱动结构，并确定小规模 oracle 与敏感性/可辨识性风险。预检只缩小候选空间，不得指定模型或算法；它还应说明题目特定 exact scorer 需要重算的硬约束和 oracle，而不是把数学判断交给通用运行时。
3. 根据预检论证，按需加载**最多 3 个能力包**：一个主能力包、至多一个交叉能力包、至多一个验证/不确定性包。可选资产是 `knowledge/cards/*.json`、模型选择矩阵、一个 Cookbook 或 `skills/2analysis-modeling/SKILL.md` 的相关段落；每个包都要记录其回答的当前风险。知识只能提出候选，不得自动决定模型。
4. 为完整题生成两到三条真正不同的候选路线，分别说明关键假设、可回答的问题、最低成本 baseline/probe、代价、风险和 fallback 条件。路线必须在进入执行协议前完成比较。若路线包含搜索，在此处起草题目合同：目标方向、硬约束、坐标与容差、共同/实体/交互变量组、覆盖度量、校准和挑战可比标准，以及 candidate generator、exact scorer、search auditor 的受控输入输出边界。合同描述证据接口，不指定固定算法。
5. 先做能区分路线的最低成本 oracle 或 probe；然后才依次生成原始候选、独立精确评分和搜索审计。实现或数据错误立即修正，probe 显示 fallback 更优时直接记录切换。只有题意解释、核心目标或必做输出改变时，才请求用户决定。
6. 写入 `reports/ANALYSIS_MODELING_REPORT.md`，包含：

   ```markdown
   # 赛题分析与建模方案
   ## 1. 题目目标与各问关系
   ## 2. 数据与附件理解
   ## 3. 关键歧义与采用解释
   ## 4. 候选路线
   ## 5. 快速 probe 与路线比较
   ## 6. 暂定主路线
   ## 7. fallback
   ## 8. 各问数学模型
   ## 9. 实现接口
   ## 10. 可验证执行合同（如需搜索）
   ## 11. 题目特定贡献候选与证据计划
   ## 12. 当前最高风险
   ```

7. 在“题目特定贡献候选与证据计划”中，只列当前题的结构发现、建模变换、算法设计、实证发现或表达组织候选，分别写明机制差异、可检验预测、需要的对照/单组件消融和限制。此时不得把通用 Skill、质量协议、现成算法调用或常规图表写成数学创新；没有当前 production 证据的条目只是研究假设。后续 `$mathmodel-paper` 只会把已绑定 accepted/current 结果的条目写入 contribution ledger；同组只保留一个 incumbent 时，应预先让 exact scorer 输出独立的受控对照/消融 sidecar，而不是制造多个互相覆盖的 current 结果。缺少完整机制→预测→对照→消融链时降级为方法组合或工程实现。
8. 将主路线、fallback、放弃路线和关键解释压缩写入 `state/DECISIONS.md`，并更新 `state/run.json`。不要创建审核材料、状态机或科学结论门。

## 非光滑或黑箱优化的恢复性 P0

对黑箱、非光滑、稀疏命中或仿真优化，先让题目特定 **exact scorer** 对已知可行解做恢复性检查：记录 exact、近似评价器和搜索代理的口径、离散容差和硬约束。baseline 可以作为显式标记的 warm start 进入候选池；它只是下界、单元测试和初始候选，不能限制全域边界、冒充挑战成果或充当搜索成功条件。

搜索前冻结包含目标/评分器/约束版本、方向、精细容差、接受理由和挑战可比标准的合同。candidate generator 只保留原始 pool、每个 seed 的参数坐标、代理值、各阶段轨迹和配置；不得写入可用于 accepted 的质量结论。exact scorer 独立重算 pool 中候选的硬约束、可行性与 exact；search auditor 读取原始 pool/trace、scorer 输出和合同，重算覆盖、校准、独立性和选择影响。三者各自有来源、受控命令、输入输出和哈希，任何版本、路径、输入或输出漂移都回退为 diagnostic。

校准集不能由同一 surrogate 的 top-k 选出，应按题目风险纳入独立分层/低差异、边界和事件邻域样本。多实体/多阶段题必须把共同变量、实体变量、交互变量组写入合同；auditor 从原生坐标重算各组联合覆盖和跨组交互覆盖，不能用平均、首值或低维投影冒充充分搜索。并集/重叠目标的搜索代理、校准、exact 和候选选择都使用 union/marginal-gain；允许零边际实体，但不把复现上阶段单实体解算作本题进展。

库函数的 `success` 只表示停止条件，不是科学成功。校准优先检查决策相关的 top-k recall、局部改善方向一致性、边界/高价值区域误差和候选筛选影响；只有足以反转选择结论的灾难性假零或错序阻断，其他误差只要求缩小结论、补充校准或调整代理角色。挑战前冻结 incumbent 的登记输出哈希、exact 值和可比标准；挑战可以包含明确标记的 warm start，但审计必须证明独立新候选、独立覆盖和实际新区域。独立且可比但未改善的挑战增强 incumbent 稳定性；充分但较差的挑战只是无信息或较弱搜索族；只有 scorer 或模型语义错误才可推翻 incumbent。候选 registry 不得让低于已有 verified incumbent 的弱或不可审计候选覆盖 current。

## 按需建模能力增强

`mathmodel-solve` 是比赛主链中的建模专家入口，而不只是流程分发器。完成结构预检后，按当前题型在上述 3 个能力包上限内按需加载下列已有能力资产：

- `skills/2analysis-modeling/SKILL.md`：将题意、变量、假设、目标、约束、算法和实现接口写到可编码的粒度；
- `knowledge/cards/structural-preflight.json`：预检不变量、界、消元、分解、事件、小规模 oracle 与可辨识性；
- `knowledge/cards/structured-optimization.json`、`sparse-nonsmooth-search.json` 与 `uncertainty-validation.json`：分别辅助结构化优化、非光滑搜索及验证/不确定性论证；
- `knowledge/problem-decomposition.md` 与 `knowledge/model-selection-matrix.md`：识别数学本质并生成候选路线；
- `knowledge/cookbooks/` 中最多一个与题型匹配的 Cookbook：预测统计、优化、机理反演、评价排序、统计学习或网络系统；
- `templates/algorithms/` 中与已选路线匹配的代码模板：只在其接口和假设适合当前题时改造成真实代码，不能把模板输出当作结果。

这些资产用于提升模型设计和验证质量，不是审批清单：矩阵不能代替路线比较，模板不能代替题目建模，Cookbook 不能要求每题执行固定实验。结构预检、能力卡和 Cookbook 都只能提出候选；既有质量协议只在路线比较后约束实际执行证据。若一个简单模型已直接回答题目且通过必要验证，不为“使用高级方法”而增加复杂度。
