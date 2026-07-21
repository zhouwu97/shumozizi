---
name: mathmodel-paper
description: 从 result_registry.json 中已接受且允许写入论文的真实结果增量撰写数学建模论文。用于每个子问题结果确认后的章节写作，以及全部实验完成后的摘要、结论和全文组装。
---

# 证据驱动的增量论文写作

只使用已注册、已接受的结果写作，不得从聊天记忆或未运行的代码猜测数值。

## 前置检查

1. 完整读取 `skills/5writing/SKILL.md`，沿用比赛模板、排版和编译要求。
2. 完整读取 `skills/mathmodel-figure-templates/SKILL.md` 和 `skills/3coding-visual/SKILL.md`，按图型选择项目原生科研绘图模板或通用数据绘图能力。
3. 读取 `state.json`、`brief/ROUTE_LOCK.json`、数学规格、
   `results/result_registry.json` 和 `claims/claim_evidence.json`。
4. 过滤出 `status=accepted` 且 `paper_allowed=true` 的结果；其他记录不得进入正文、
   摘要、图表结论或贡献声明。
5. 写作前生成论文主张门禁：

   ```powershell
   python scripts/runtime/gate_paper_claims.py runs/<run_id>
   ```

   `paper/claim_gate.json` 的 `stale=true` 时，主张证据完全禁止引用；必须先重新生成
   当前 claim evidence。不得根据路线锁中的自由文本或聊天内容绕过门禁。
6. 正式全文组装前执行：

   ```powershell
   python scripts/codex/scientific_viability.py verify runs/<run_id> --paper-entry
   ```

   只有 `VIABLE` 或已完成修复/明确人工接受风险的 `WEAK_BUT_REPAIRABLE` 可以继续。
   `ROUTE_AT_RISK`、`ROUTE_FAILED` 或未执行 action 必须停止；失败 primary 不得作为论文中心。
7. 在正文写作前生成并持续更新三个作者侧产物：
   `paper/PAPER_BLUEPRINT.md`、`claims/ARGUMENT_MAP.json`、`paper/FIGURE_STORYBOARD.md`。
   它们不增加主状态或审核门，但必须绑定当前路线、结果和证据摘要。

## 增量写作

某个子问题结果一经接受，立即写或更新对应章节，至少包含问题分析、模型推导、求解方法、
基线比较、主结果、稳健性/消融、图表解释、局限和逐问回答。每个关键数值都能依次追溯到
`result_id`、`execution_record_id`、执行清单、当前输入哈希和当前输出哈希。

把章节写入 `paper/sections/`，并在 `state.json` 记录已完成章节。不要等所有实验结束后才
突击写各问内容。

`PAPER_BLUEPRINT.md` 必须规划全文研究故事、共享符号和数学对象、各问章节职责、核心公式、
baseline、验证、直接答案位置、摘要准备使用的真实结果，以及文献需要支持的判断。

`ARGUMENT_MAP.json` 的每条主张必须包含动机、baseline 局限、模型支持、result IDs、比较证据、
验证证据、figure IDs、结论边界、结果状态和正文位置。不得只保存 claim、outcome 和 scope。

`FIGURE_STORYBOARD.md` 的每张图必须说明对应问题、数据、待证明主张、必要性、图型、坐标轴与
单位、正文解释位置。没有论证职责的图不得进入正式图表计划。

## 全文组装

只有状态达到 `RESULTS_ACCEPTED` 后，才统一写摘要、结论、优缺点和推广。摘要必须包含真实
核心数值。创新表述必须逐项服从 `paper/claim_gate.json`：

| claim status | 允许写法 |
| --- | --- |
| `supported` | 可写确定性贡献、结果和讨论 |
| `partially_supported` | 只能写有限贡献，并同时写明限制 |
| `rejected` | 只能写结果、失败分析和限制，不得写成贡献 |
| `inconclusive` | 只能写结果和未决讨论，不得写确定性贡献 |
| `stale=true` | 完全禁止引用该主张证据 |

按用户已锁定的比赛、语言和排版引擎组装并编译论文。

## 生产回执

在进入 `PAPER_DRAFTED` 前必须写入并通过机器校验：

- `paper/paper_plan.json`：绑定本 Skill、`skills/5writing`、`skills/typst-author`、比赛模板、model spec、结果注册表、claim gate、章节文件和使用的图表。
- `paper/PAPER_BUILD_RECEIPT.json`：绑定计划哈希、当前 state revision、最终 PDF 路径与 SHA-256。
- `figures/FIGURE_PLAN.json` 及每张图的 `figures/<figure_id>.receipt.json`：绑定 accepted result ID、数据、绘图脚本、PDF/PNG 输出、单位、图例和坐标轴。
- `questions/<question_id>/QUESTION_ACCEPTANCE.json`：逐项绑定题目要求、模型输出、一一对应关系、硬约束、baseline、accepted result、不确定性、direct answer、上游依赖和 claim status。未通过的问题不得进入 `paper/sections/`。

图表选择顺序固定为：首先匹配 `skills/mathmodel-figure-templates` 的 11 类项目原生模板；没有匹配图型时使用 `skills/3coding-visual` 编写自定义数据图。Nature 风格只在用户明确要求且脚本已纳入当前运行目录时使用，不作为默认生产依赖。每张图必须在 `FIGURE_PLAN.json` 中记录 `selected_skill`、`template_id` 和选择理由，回执不是简单的 `{"status":"pass"}`，必须由 `verify_production_receipts()` 复验所有路径、哈希、选型和 accepted 结果。

生成草稿后把状态设为 `PAPER_DRAFTED`，然后交给 `$mathmodel-review`。本 Skill 不执行多轮
审稿，也不把论文直接标记为最终提交稿。
