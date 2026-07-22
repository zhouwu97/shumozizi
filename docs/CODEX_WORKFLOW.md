# Capability-First v3 Codex 工作流

完整赛题只使用六项主动 Skill。它仍是一条连续生产链，不新增阶段、审批、人工 checkpoint 或固定算法配方：

```text
结构预检（按需使用知识卡）
→ 路线比较与低成本 oracle
→ candidate generator
→ exact scorer
→ search auditor
→ production 放行
→ 真实实验、图表与按需验证
→ 论文写作与编译
→ 一次机械 QA + 一次整体审查
→ 仅在 P0/P1 时定向修复
```

`state/run.json` 用于断点恢复，`DECISIONS.md` 保存题意解释、路线、失败原因和下一步，`results/index.json` 保存运行事实与文件哈希。它们都不裁定数学正确性或模型优劣。默认最多两个用户决策点：题意或必做输出存在重大歧义时，以及最终提交确认时。普通修代码、参数调整、求解器调整或 fallback 切换不需要重新批准。

## 三段式执行协议

搜索型问题必须先写题目合同。合同不是通用验证器，也不规定求解算法；它声明题目语义所需的目标与方向、硬约束、坐标与容差、共同/实体/交互变量组、覆盖度量、校准与挑战可比标准、依赖关系，以及三个 adapter 的标识和受控边界。

| 角色 | adapter 作者负责 | generic runtime 负责 |
| --- | --- | --- |
| candidate generator | 产生原始 candidate pool、参数坐标、代理值、配置和完整 search trace | 执行受控来源，登记输入输出、命令和 hash |
| exact scorer | 独立读取候选，按题意重算硬约束、可行性和 exact objective | 绑定 scorer 的 source/input/output/command provenance，拒绝漂移 |
| search auditor | 从原始 pool/trace、合同和 scorer 输出重算覆盖、校准、挑战独立性和选择影响 | 校验 adapter 版本、路径边界、允许命令和来源链 |

adapter 作者必须把数学判断写在 scorer/auditor 中，而不是让 generator 用自己的 `feasibility`、`exact_recomputed`、`search_adequacy` 或 `problem_effectiveness` 布尔字段自证。generic runtime 只执行合同明确允许的本地来源、相对路径和命令，并复验 source/input/output hash、版本与路径；输入变更、输出漂移、版本不一致、路径越界或不受控任意命令都会被拒绝。它不声称能验证任意题目的数学正确性。

原始 candidate pool 与 trace 必须供 auditor 读取。auditor 按合同中声明的共同、实体和交互变量组，直接从原生坐标重算至少一种明确覆盖度量。高维候选的平均值、首元素、低维投影或写在 JSON 中的 `joint_coverage` 摘要不能充当联合覆盖。代理校准应衡量决策影响，例如 top-k recall、局部改善方向、边界/高价值区域误差及对筛选的影响；只有足以反转选择结论的灾难性错误阻断。

## 搜索与 registry

baseline 可以作为显式标记的 warm start 进入 pool。它不计作挑战成果：auditor 仍需证明合同要求数量的独立新候选、独立覆盖与实际评估的新区域。verified candidate registry 按问题、目标、评分器、约束与语义版本分组；只有语义一致、经独立 scorer/auditor 证实的有效改善才可替换 current verified incumbent。弱、较差、legacy 或不可审计候选永远不能覆盖它。

| 挑战结果 | 解释与 registry 行为 |
| --- | --- |
| 独立且严格改善 | 经过 scorer 与合同检查后可成为替换候选 |
| 独立、覆盖充分、达到预登记可比标准但未改善 | 保留 incumbent，并增加稳定性证据 |
| 覆盖充分但较差 | 无信息或较弱搜索族；不覆盖 incumbent |
| scorer 或模型语义被发现错误 | 回到分析/精确评分，可能推翻 incumbent；challenger 不自动升级 |
| 独立性、覆盖或可比性不足 | diagnostic，不影响已验证 incumbent |

正常退出只说明执行完成，不能替代上述审计。并集或重叠目标在代理、校准、exact 与选择中使用 union/marginal-gain 语义。

## 探索与生产

| 模式 | 允许 | 禁止 |
| --- | --- | --- |
| `exploration` | 基于未 accepted 的上游诊断候选研究后续问题、共享结构或反向诊断 | 写入 accepted/current registry、论文、图表、提交或正式下游结论 |
| `production` | 使用合同依赖的 prior accepted/current 结果推进正式下游和论文 | 以 exploration 文件、重命名或自报质量字段绕过前序质量门 |

探索记录必须保留 diagnostic scope。生产下游按合同中的实际依赖检查 prior accepted/current，而不是按题号机械放行。

## 轻量论文参考接口

只有 production 结果冻结后，`mathmodel-paper` 才可按需读取 1-2 张已登记的离线论文卡，用于章节组织、模型解释表达、验证叙事或 Figure Contract。它不调用或合并 `mathmodel-learn-paper`，后者仍是离线学习能力，不修改当前运行状态也不进入比赛生产主链。

论文卡不是 citation、evidence 或 Claim-Evidence 输入。不得迁移卡或原论文中的数值、结论、代码、原公式段或实验结果；当前论文的事实和结论只能来自本次 production accepted/current 结果及其独立证据链。

使用 `register_paper_references()` 在 `paper/paper_references.json` 登记卡 ID 与有效 production 结果 ID，再通过 `writing_reference_cards()` 按需取得已复验的卡路径和允许用途。索引只能是受控仓库的 `knowledge/indexes/papers.json`，卡只能位于 `knowledge/cards/papers/`；收据只保存索引、卡和来源哈希，不保存卡正文。复验会拒绝生产结果、索引路径/哈希、卡身份或来源哈希的漂移。

## 贡献与五问论文

论文维护一个 contribution ledger，每项都要写明问题/章节、类型、题目特定内容、当前运行证据和限制。允许的类型仅为结构、模型、算法、实证或表达贡献。通用 Skill、质量协议、adapter、既有算法的直接调用和普通图表都不是数学创新；证据只支持工程实现或方法组合时，论文必须如实这样表述，不夸称新模型或新算法。若声明题目数学创新，还必须把机制差异、可检验预测、带指标/方向的对照改善和单组件消融绑定到当前 production accepted/current 证据：可用角色独立的结果，或在同组只有一个 incumbent 时用该 primary exact scorer 的两个受控 sidecar；对照和消融不能共用同一结果/sidecar 自证。它是可审计的证据角色合同，不是自动创新评分，也不要求每题有创新。

Q1-Q5 每问都必须有可定位的直接答案，不能只藏在总表、图注或前一问。每问最少包含：题目要求和采用解释、变量/数据/假设、核心模型或公式、实际求解、当前运行结果、验证和限制、直接答案；只有合同明确依赖时才说明前序消费关系。公式、图、表和引用必须服务于该问的直接答案，不以密集堆砌替代解释或证据。

`qa/FINAL_REVIEW.md` 需单列 PDF 内容异常：逐项报告 Q1-Q5 的直接答案和内容块覆盖，定位可能缺失或不一致的页/节，并报告页数、公式、图、表和引用的可疑密度。页数或任一密度单独异常仅为 warning，不能单独阻断；只有结合直接答案缺失、不可读、错误引用、无证据主张或提交要求冲突时，才按实际后果分级。若运行使用了离线论文卡或贡献账本，机械 QA 会在终检重放其收据；论文卡索引/卡哈希、冻结 production 结果或贡献链漂移均会阻断，但未使用接口不会因缺少可选文件失败。

## 迁移与边界

历史记录和旧质量布尔字段一律迁移为 `diagnostic/unverified`；只有在当前题目合同下补齐独立 generator、scorer、auditor 产物及 provenance 后，才可能成为 accepted。文件 hash、正常退出、恢复 baseline、机械 QA 或一次挑战均不能单独证明模型解决了题目。

该协议只能提高证据分层、可复验性和错误可见性。它没有验证模型是否真正理解题意、是否选择了合适路线、数学假设是否成立，或最终论文是否具有竞赛竞争力；这些仍须依靠结构预检、低成本 oracle、真实实验、论证质量和整体审查。生产任务不得按问题拆成独立审核，也不得为每个 finding 创建对话；一次整体审查的输出仍为 `qa/FINAL_REVIEW.md`，按 P0–P3 分级，重大修复后最多进行一次定向复查。
