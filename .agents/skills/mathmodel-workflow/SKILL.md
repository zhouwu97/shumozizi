---
name: mathmodel-workflow
description: 以 Capability-First v3 完成整道数学建模赛题的分析、求解、真实实验、论文和一次终检。仅在用户明确要求完整赛题交付时使用；局部分析、调试或改写论文不得隐式启动。
---

# Capability-First v3 数学建模工作流

目标是在有限时间内提高解题、实验和论文质量。能力 Skill 负责思考与产出；`results/index.json` 只证明程序真实运行；`results/quality.json` 分别记录执行、可行性、exact 重算、搜索充分性和题目有效进展，且每项必须引用已登记输出的路径、JSON 字段与哈希；机械 QA 只拦截确定性提交错误。不要把任一层、尤其是“保留 baseline”，误当成求解成功。

## 启动与恢复

1. 仅在用户要求整题、可运行实验和完整论文时使用本 Skill。局部任务直接使用相应能力 Skill。
2. 新运行使用：

   ```powershell
   python scripts/codex/init_run.py <problem_path> --workflow capability-first-v3 --run-id <run-id>
   ```

   也可使用 `scripts/codex/init_simple_run.py`。运行目录是 `runs/<run-id>/`。
3. 每次恢复先读取 `state/run.json` 和 `state/DECISIONS.md`，只读取当前阶段需要的材料。题面、数据摘要和已完成报告不得无目的重复全量读取。
4. 默认生产链只有一个连续任务：分析、建模、代码、图表、论文；随后最多一次整体审查；只有存在 P0/P1 时才进行一次定向修复。不要为每问、每个发现或格式小改创建顶层任务。
5. `blocked` 是恢复而非交付阶段：只能回到 `analysis` 或 `experiment`，不得直接进入 `paper`、`verify` 或 `complete`。恢复先记录失败证据和最小修复条件。

## 阶段路由

| `phase` | 行动 | 主要产物 |
| --- | --- | --- |
| `analysis` | 调用 `$mathmodel-solve`，理解题意、数据和候选路线 | `reports/ANALYSIS_MODELING_REPORT.md` |
| `experiment` | 调用 `$mathmodel-experiment` 实际运行代码、记录结果、按题型验证；仅在 Figure Contract 匹配时按需调用仓内科研绘图模板 | `results/index.json`、`reports/RESULTS_REPORT.md` |
| `paper` | 调用 `$mathmodel-paper`，只用仍为 current 的真实结果写作和编译 | `paper/final.pdf` |
| `verify` | 调用 `$mathmodel-final-check`，执行一次机械检查和整体科学审查 | `qa/mechanical-qa.json`、`qa/FINAL_REVIEW.md` |
| `complete` | 仅报告产物、复现命令与局限 | 交付摘要 |

用 `shumozizi.simple.state.update_simple_state()` 或受支持 CLI 更新阶段、路线、已完成问题和产物路径；不写入审核闭环、裁决、回执或科学判定状态。

## 路线后的首个 probe（P0）

路线确定后、投入完整求解前，先列出四类风险：**判定器**是否与题意一致、**求解器**能否恢复已知可行解、**约束可行性**是否由参数化或显式检查保证、以及**规模扩展**是否会使当前方法退化。选择最高风险做首个低成本 probe，并记录命令、输入、输出哈希和有效性。

若该 probe 不能用同一评分器恢复已知基线、发现硬约束被破坏，或求解器只有零分候选，立即停在 `analysis`/`experiment` 修复或切换路线；不得以退出码、库函数 `success` 或空模板填充推进论文。

对高风险非光滑优化，恢复基线后先冻结选择合同：exact 指标、方向、目标/评分器/约束版本、精细容差、接受阈值及其理由。分开 exact objective、近似评价器和带裕度的搜索代理；校准集独立于代理 top-k，含分层/低差异、边界和事件邻域。多实体/多阶段题还要声明共同变量、每个实体变量和交互变量组，分别报告组内联合覆盖与跨组交互覆盖；均值、首值或低维投影不能代替原生联合覆盖。并集或重叠目标的代理、校准、exact 和选择均用 union/marginal-gain 语义，零边际实体允许，但复现既有单实体解不是当前问题进展。

将可行性、exact 重算、充分性和 `problem_effectiveness=progressed` 从已登记输出复验后，才登记到按问题、目标、评分器、约束和语义版本分组的 candidate registry。新结果只在超过同组已验证 exact 下界（合同容差内）时替换 incumbent；失败、并列或较差结果必须恢复 incumbent，不得因执行较晚而回退。独立挑战必须用不同实现族，并以实际命令、命令收据、输入/输出哈希、实现文件哈希、候选池指纹和冻结 incumbent 的独立 exact 重算执行证明来源，不能接受 JSON 自报独立性。挑战不改善或不满足预登记可比条件时，执行一次合同定义且有界的加密或换族搜索；仍不通过则阻断。只有带上述证据、`accepted`、`search_adequacy=passed`、`exact_recomputed=true`、`problem_effectiveness=progressed` 且仍为 registry incumbent 的 current 结果可进入下一问、图表、论文和终检；Q4/Q5 等下游还必须消费前一问未降级的有效质量记录。

## 人工决策与路线切换

默认只在两种情况暂停询问用户：

1. 题意、核心目标或必做输出存在重大歧义；
2. 最终提交前请求确认。

以下情况无需重新请求批准：修复实现错误、调整参数或求解器、用已有 fallback 替代主路线、同一题意下更换模型类别。只有改变题意解释、核心目标、必做输出，或预计额外投入超过剩余预算 30% 时，才停下给出编号选项和推荐项。

## 预算与停止规则

- `fast`、`standard`、`deep` 的 token 软上限分别建议为 50k、200k、500k；达到软上限时缩减上下文和任务，而不是制造新的门禁。
- 每阶段最多加载一到两个知识文件；文献检索最多五次。
- 数据摘要和关键决策优先落盘；局部修改只读受影响章节。
- 连续两次修改没有实质改善时停止，记录原因并切换 fallback、缩小目标或请用户决定。
- 剩余时间少于 15% 时只处理 P0/P1 和可提交性。

本 Skill 不使用审核生命周期、独立审核对话编排或每问固定实验数量。最终科学判断来自完整结果和一次整体审查，而非状态文件。
