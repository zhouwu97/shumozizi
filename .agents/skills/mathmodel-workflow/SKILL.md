---
name: mathmodel-workflow
description: 以 Capability-First v3 完成整道数学建模赛题的分析、求解、真实实验、独立科学红队、论文、独立 PDF 盲审和机械终检。仅在用户明确要求完整赛题交付时使用；局部分析、调试或改写论文不得隐式启动。
---

# Capability-First v3 数学建模工作流

目标是在有限时间内提高解题、实验和论文质量。能力 Skill 负责思考与产出；`results/index.json` 只证明程序真实运行；机械 QA 只拦截确定性提交错误。质量协议只验证受控的题目特定证据链，不把任一层、尤其是“保留 baseline”，误当成求解成功。

对搜索型问题，正式结果必须经过相互分离的 candidate generator、exact scorer 和 search auditor。生成器不能以自己输出的 `feasibility`、`exact_recomputed`、`search_adequacy` 或 `problem_effectiveness` 布尔值证明自己；这些旧字段最多是诊断。通用运行时也不声称理解任意数学模型，它只执行并复验受控 adapter 的来源、输入、输出与来源链。

## 启动与恢复

1. 仅在用户要求整题、可运行实验和完整论文时使用本 Skill。局部任务直接使用相应能力 Skill。
2. 新运行使用：

   ```powershell
   python scripts/codex/init_run.py <problem_path> --workflow capability-first-v3 --run-id <run-id>
   ```

   也可使用 `scripts/codex/init_simple_run.py`。运行目录是 `runs/<run-id>/`。
3. 每次恢复先读取 `state/run.json` 和 `state/DECISIONS.md`，只读取当前阶段需要的材料。题面、数据摘要和已完成报告不得无目的重复全量读取。
4. 分析后必须先调用 `$mathmodel-capability-router`，冻结主能力、交叉能力、独立验证方式、可用本地工具和知识资产；再进入代码和实验。随后必须断开上下文，分别新建科学红队和 PDF 盲审对话。不要为每问、每个发现或格式小改创建顶层审核任务，也不要以同一对话角色扮演独立审查。
5. `blocked` 是恢复而非交付阶段：只能回到 `analysis` 或 `experiment`，不得直接进入 `paper`、`verify` 或 `complete`。恢复先记录失败证据和最小修复条件。

## 阶段路由

| `phase` | 行动 | 主要产物 |
| --- | --- | --- |
| `analysis` | 调用 `$mathmodel-solve`，理解题意、数据和候选路线 | `reports/ANALYSIS_MODELING_REPORT.md` |
| `capability_route` | 调用 `$mathmodel-capability-router`，冻结求解、验证、工具和本地知识组合 | `state/capability-route.json`、`state/tooling.json` |
| `experiment` | 调用 `$mathmodel-experiment` 实际运行代码、记录结果和题型验证，并保存图表所需真实数据 | `results/index.json`、`reports/RESULTS_REPORT.md` |
| `scientific_review` | 创建冻结科学包，并在全新对话调用 `$mathmodel-red-team` 做清洁室复现、反例和搜索挑战 | `review/SCIENTIFIC_RED_TEAM.md`、`review/summary.json` |
| `visualization` | 调用 `$mathmodel-visual`，完成模型、搜索和结果证据图的 Figure Contract | `state/visualization-plan.json`、`figures/` |
| `paper` | 调用 `$mathmodel-paper` 并执行已实例化的完整 `skills/5writing/SKILL.md` 模板、写作和编译 | `paper/template_manifest.json`、`paper/final.pdf` |
| `paper_review` | 创建 PDF 盲审包，并在另一全新对话调用 `$mathmodel-red-team` 审阅匿名 PDF | `review/PAPER_BLIND_REVIEW.md`、`review/summary.json` |
| `verify` | 调用 `$mathmodel-final-check`，只执行机械检查和 PDF 内容覆盖报告 | `qa/mechanical-qa.json`、`reports/VERIFY_REPORT.md` |
| `complete` | 仅报告产物、复现命令与局限 | 交付摘要 |

用 `shumozizi.simple.state.update_simple_state()` 或受支持 CLI 更新阶段、路线、已完成问题和产物路径；不写入审核闭环、裁决、回执或科学判定状态。

`analysis -> capability_route -> experiment` 必须有可用工具和能力路由；`scientific_review -> visualization` 只能消费当前冻结科学包和独立报告；`visualization -> paper` 要求路由指定的 Figure Contract 已完成，且完整写作模板已选择并实例化；`paper -> paper_review` 会再次复验模板未漂移；`paper_review -> verify` 只能消费当前 PDF 盲审；`verify -> complete` 还要求当前 PDF 的机械 QA 通过。三段 adapter、哈希、local oracle 和机械 QA 均只是局部证据，不能绕过独立红队。审查包与报告的创建、导入和失效规则见 `$mathmodel-red-team`。

## 探索与生产边界

运行模式只区分产物用途，不增加阶段、审批或人工 checkpoint：

| 模式 | 可以做什么 | 不能做什么 |
| --- | --- | --- |
| `exploration` | 使用尚未 accepted 的上游诊断候选研究后续问题、共享结构或反向诊断，并记录假设和失败证据 | 不能写入 verified candidate registry 的 `accepted/current`，不能进入论文、图表、提交或正式下游结论 |
| `production` | 用已接受且仍为 current 的前序结果推进正式下游求解、图表和论文 | 不能用 exploration 产物绕过前序问题的 accepted/current 要求 |

探索结果必须显式保留 diagnostic scope；复制到生产目录、重新命名或补写布尔字段都不会使其升级。生产模式仍按问题合同声明的依赖关系检查前序 accepted/current，而不是把题号顺序或一次正常退出当作放行依据。

生产结果冻结后，论文阶段可按需读取 1-2 张已登记的离线论文卡，只借鉴章节组织、模型解释表达、验证叙事或 Figure Contract 的表达模式。这是轻量 reference interface，不调用或合并 `$mathmodel-learn-paper`，不迁移卡或原论文中的数值、结论、代码、原公式段或实验结果，也不把论文卡当作 citation、evidence 或 Claim-Evidence 材料。

## 路线后的首个 probe 与可验证执行协议（P0）

路线确定后、投入完整求解前，先列出四类风险：**判定器**是否与题意一致、**求解器**能否恢复已知可行解、**约束可行性**是否由参数化或显式检查保证、以及**规模扩展**是否会使当前方法退化。选择最高风险做首个低成本 oracle 或 probe，并记录命令、输入、输出哈希和有效性。顺序始终是：结构预检 → 路线与低成本 oracle → 生成 → 精确评分 → 搜索审计 → 生产放行。

若该 probe 不能用同一评分器恢复已知基线、发现硬约束被破坏，或求解器只有零分候选，立即停在 `analysis`/`experiment` 修复或切换路线；不得以退出码、库函数 `success` 或空模板填充推进论文。

### 题目 adapter 合同

每题先冻结合同，而不是伪造通用数学验证器。合同由题目作者定义：目标及方向、硬约束、输入坐标和容差、共同变量组/实体变量组/交互变量组、明确的覆盖度量、校准与挑战的可比标准、依赖关系，以及三个 adapter 的标识、版本、受控相对源路径、`source_files`、允许命令、输入与输出路径。`source_files` 必须等于入口经静态 import 可达的当前 run `code/` 本地 Python 源码闭包，且同时列入 `input_files`；三段不得共享其中任何本地源码。adapter 承载题目数学；generic runtime 只允许合同列出的本地 adapter 来源和命令，复验完整 source/input/output hash、版本和路径边界，并拒绝输入变更、输出漂移、版本不匹配、路径越界或不受控任意命令。该约束审计受信任 adapter 的静态本地依赖，不是恶意 Python 的操作系统级沙箱。

三个角色的职责不可合并：

| 角色 | 必须产生或重算的内容 | 不能充当的证据 |
| --- | --- | --- |
| candidate generator | 原始 candidate pool、参数坐标、代理值、搜索配置和完整 trace | 其自身的可行性、exact、充分性或题目进展布尔判断 |
| exact scorer | 独立读取候选并重算硬约束、可行性和 exact objective | 生成器的代理值、选中标签或自报结论 |
| search auditor | 从原始 pool/trace、合同和 scorer 产物重算覆盖、校准、挑战独立性与选择影响 | `joint_coverage` 等摘要数字或挑战者自报独立性 |

exact scorer 与 auditor 必须各自登记 input/output/source/command provenance。原始 pool 和 trace 是审计输入，不是可选摘要：对于合同声明的共同、实体和交互变量组，auditor 至少从原生坐标重算一种明确覆盖度量。高维候选的均值、首元素、投影或平均覆盖都不能伪造联合覆盖。并集或重叠目标的代理、校准、exact 和选择均使用 union/marginal-gain 语义；零边际实体可以存在，但复现既有单实体解不是当前问题进展。

代理校准面向决策影响，而不是“出现任一假零即失败”：按合同检查 top-k recall、局部改善方向一致性、边界/高价值区域误差及其对候选筛选的影响。只有会使选择结论失真的灾难性错误阻断；其余误差应缩小结论、补充校准或调整代理角色。

允许将冻结 incumbent 作为明确标记的 baseline/warm start 放入 candidate pool。auditor 仍必须证明存在合同要求数量的独立新候选、独立覆盖和实际评估的新区域；只复制 incumbent 或把它伪装为挑战成果会失败。挑战结果按下表解释：

| 挑战审计结果 | 对 incumbent 的作用 |
| --- | --- |
| 独立且严格改善 | 经 exact scorer 和合同检查后，才可作为替换候选 |
| 独立、覆盖充分、达到预登记可比标准但未改善 | 增强 incumbent 稳定性，保持 accepted/current |
| 覆盖充分但明显较差 | 记录为无信息或较弱搜索族，不覆盖 incumbent |
| 发现 scorer 或模型语义错误 | 回到分析/精确评分，可能推翻 incumbent；不能把 challenger 自动提升为 accepted |
| 独立性、覆盖或可比性证据不足 | 仅 diagnostic，不降级已验证 incumbent |

verified candidate registry 按问题、目标、评分器、约束和语义版本分组。只有有独立 scorer/auditor 证据且语义一致的有效改善可替换同组 incumbent；弱、较差、legacy 或不可审计候选不得覆盖它。旧记录和旧布尔质量字段统一迁移为 `diagnostic/unverified`，除非在当前合同下补齐独立 adapter 产物；不得无证据升级为 accepted。只有生产模式下、仍为 registry incumbent 且完整独立证据链通过的结果可进入下一问、图表、论文和终检；Q4/Q5 等下游还必须消费合同所需的前序未降级结果。

## 人工决策与路线切换

默认只在两种情况暂停询问用户：

1. 题意、核心目标或必做输出存在重大歧义；
2. 最终提交前请求确认。

以下情况无需重新请求批准：修复实现错误、调整参数或求解器、用已有 fallback 替代主路线、同一题意下更换模型类别。只有改变题意解释、核心目标、必做输出，或预计额外投入超过剩余预算 30% 时，才停下给出编号选项和推荐项。

## 预算与停止规则

- `fast`、`standard`、`deep` 的 token 软上限分别建议为 50k、200k、500k；达到软上限时缩减上下文和任务，而不是制造新的门禁。
- `analysis` 阶段先由 `$mathmodel-solve` 做结构预检，再按论证加载最多三个能力包（主能力、交叉能力、验证/不确定性）；文献检索最多五次。
- 数据摘要和关键决策优先落盘；局部修改只读受影响章节。
- 连续两次修改没有实质改善时停止，记录原因并切换 fallback、缩小目标或请用户决定。
- 剩余时间少于 15% 时只处理 P0/P1 和可提交性。

本 Skill 不复活 legacy-v2 审核生命周期，也不按题号增加固定审核数量。独立科学红队和 PDF 盲审是两个明确的交付边界：前者审模型、代码与结果，后者只审成文交付；状态文件不保存科学结论，`review/summary.json` 只绑定外部新对话报告与冻结输入。
