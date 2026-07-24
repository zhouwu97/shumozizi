---
name: mathmodel-red-team
description: 在 Capability-First v3 中执行目标语义预审、独立科学红队、PDF 盲审或最终交付审核。用于发现题意目标、模型、几何、约束、搜索、论证和提交物中的错误；每轮必须在不同的全新 Codex 对话中使用，不得由求解对话角色扮演替代。
---

# 独立红队审查

此 Skill 是生产工作流中的隔离审查阶段，不是 legacy-v2 审核生命周期。它不评分、不决定奖项，也不把哈希、`exact` 名称、两份相同实现的一致性或机械 QA 当作科学正确性证明。

## 隔离规则

1. 审查必须在**全新的 Codex 任务**完成。协调任务实际调用 `create_thread`，再用 `wait_threads` 等待；不得在求解任务内角色扮演审查者，也不得用 `fork_thread` 继承历史。新任务初始只接收本 Skill、绝对审查包路径、报告输出路径和任务说明；不得继承求解对话、其摘要、`DECISIONS.md`、`results/quality.json`、既有审查、QA 结论或预期结果。
2. 审查期间只读取对应 `review/packet/` 的冻结副本。可按需读取仓库的通用本地知识库来选择方法或攻击，但不得读取历史 run、同题旧解、公开同题答案或网络内容。
3. 审查者独立形成判断。不能为了“通过流程”默认认可候选，也不能以缺少外部标准答案为理由跳过复现、反例或挑战。
4. 对发现的 P0/P1，保存最小复现、受影响问题和恢复条件；不得替求解器直接改写模型、结果、论文或历史运行。审查任务只写指定报告并返回；协调任务用 `create_thread` 返回的真实 `threadId` 导入。环境不能新建任务时必须阻断，不能自填 ID 放行。

## 目标语义预审

正式题面完成初步分析后、进入 `capability_route` 前，由协调任务创建：

```powershell
python scripts/review/build_review_packet.py runs/<run-id> --kind objective-semantics
```

用全新 Codex 对话只读 `review/packet/objective-semantics/<packet-id>/`。不得读取求解报告、代码、结果、历史 run、网络或公开同题答案。逐问枚举可能的目标公式、单位、聚合语义和题面语言依据，重点区分逐实体求和、并集、交集、加权与多目标；选中的主目标必须给出题面依据。若语言仍不足以排除多个解释，保留备选，并将依据标为用户裁决或显式假设，不能假装题面已经唯一确定。

将结构化评估写入 `review/OBJECTIVE_SEMANTICS.json`，自由报告写入 `review/OBJECTIVE_SEMANTICS_REVIEW.md`，再导入：

```powershell
python scripts/review/import_review.py runs/<run-id> `
  --kind objective-semantics `
  --manifest review/packet/objective-semantics/<packet-id>/manifest.json `
  --assessment review/OBJECTIVE_SEMANTICS.json `
  --verdict pass --severity none --thread-id <fresh-codex-thread-id>
```

该任务只校验题意目标，不替代后续科学红队；后续三轮审核必须使用另外三个新对话。题面、评估或报告变化会撤销预审结论。

## 科学红队

仅在当前 run 已进入 `scientific_review` 时执行。先由协调任务创建包：

```powershell
python scripts/review/build_review_packet.py runs/<run-id> --kind scientific
```

新建 Codex 对话时只给它生成的 `review/packet/scientific/<packet-id>/`。该包只含题面与附件、当前运行内源代码和候选原始结果；不含质量标签、决策日志、审查结论或 QA。

审查者应根据题目和风险自由选择最有信息量的攻击，而不是机械逐项打勾。

## 开放审核 → 动态查漏

### 第一步：自由攻击（不填表）

审查者从题面独立重建目标、变量、约束、量纲和语义后，选择题目真实相关的高风险方向完成自由攻击，通常包括：

- 对最危险的共同原语做清洁室推导或独立小实现，特别检查端点、退化、边界和单位；
- 构造能推翻当前结论的反例、极端输入或小规模穷举；
- 以不同参数化、不同搜索族或局部剖面挑战候选区域，区分”可行””已搜索到足够区域”和”具有竞赛竞争力”；
- 检查 proxy、exact 和 oracle 是否共享同一数学定义，避免把共模一致性误报为验证；
- 检查下游问题是否继承了未经充分挑战的搜索区域或题意解释。

自由报告必须直接回答这些开放式问题：

1. 当前解法实际解决了什么——与题面的真实关系；
2. 最致命的一处风险是什么；
3. 哪一问最薄弱；
4. 是否存在更简单的反例；
5. 模型、数值和搜索是否因同一错误而系统性偏差；
6. 当前结果的真实竞争力上限在哪里。

### 第二步：独立覆盖提取

协调程序在自由报告完成后，**由另一个轻量 AI 或程序**读取报告，提取实际覆盖的风险方向（不是审核者自报），检查本题路由所需的高风险 `risk_id` 是否被讨论。

### 第三步：专项追问

若开放审核未覆盖某个高风险方向（例如几何题未检查切触和端点、优化题未做多种子验证），协调程序不直接判失败，而是对审核者发出专项追问：

> 整体审核尚未检查 [缺失方向] 的 [具体问题]。请只针对这一点设计并执行独立攻击。

### 第四步：结构化摘要

全部审核和专项追问完成后，协调层从报告中提取 findings / affected_questions / severity / repair_condition，作为**记录而非审核题目**。

---

几何/运动题若要获得 `qualified/strong`，必须实际运行并登记 `kind=geometry-continuous-validation`：连续量和采样近似使用不同变量名，采用连续一维优化、区间验证、根隔离或显式离散化误差界，并逐一覆盖左/右临界端点、切线、退化和线段外反例。可变动作数量问题另须登记 `kind=action-activation-challenge`，完整挑战题面允许的动作数量；只复算当前三个动作不能放行 Q5。

对涉及几何、优化或多实体的题，优先选择与题目相关的反例，而非只重复原求解器。高风险攻击菜单包括：有限线段与无限直线混淆、端点落入球体、烟幕/区间重叠重复计数、把“至多”误写为“恰好”、量纲不一致、数据或未来信息泄漏、proxy 与 exact 排序反转、高维联合覆盖被投影伪造、两个 oracle 共享同一判定语义，以及下游继承前题的弱搜索区域。命中任一项时，报告其是否污染候选、exact、oracle、图表和论文。

将自由报告写入 `runs/<run-id>/review/SCIENTIFIC_RED_TEAM.md`。报告至少给出独立重建、已执行攻击及证据、每个 P0/P1 的最小复现和污染范围、可支持的结论与未证明边界。只有没有未解决 P0/P1、无需全量重跑且审查者认为证据可支撑继续时，才能建议 `pass`。

求解任务收到报告后，使用实际新对话 ID 绑定结论：

```powershell
python scripts/review/import_review.py runs/<run-id> `
  --kind scientific --manifest review/packet/scientific/<packet-id>/manifest.json `
  --verdict pass --severity none --competition-strength qualified `
  --thread-id <fresh-codex-thread-id>
```

导入只记录隔离声明、冻结输入和报告哈希；它不替代报告本身。源代码、输入或结果在审查后变化会使结论失效，必须重新审查。通过后状态才可从 `scientific_review` 进入 `visualization`。图表叙事完成且冻结后才进入 `paper`；这不会让红队替视觉阶段验收美学或排版。

## PDF 盲审

仅在 PDF 已生成、当前 run 进入 `paper_review` 时执行：

```powershell
python scripts/review/build_review_packet.py runs/<run-id> --kind paper-blind
```

为此再新建一个 Codex 对话，只给 `review/packet/paper-blind/<packet-id>/`。它初始只含题面、附件、匿名 PDF 和提交材料；不得读取源码、科学审查、质量结果或 QA。

盲审依据题意和 PDF 判断：是否逐问直接回答、建模假设与结论是否自洽、推导和图表能否支撑主张、结果解释是否诚实、是否存在空洞章节、不可读图表、无证据的竞争力宣称或匿名问题。对声明为空间、求解或稳定性证据的图，要核查实际可见对象、坐标/单位、边界和论证关系；一张漂亮但不呈现这些对象的 3D 散点图不能承担模型验证。它可标出需要求解任务进一步复核的证据，但不能在看不到代码时臆造数值或数学结论。

将报告写入 `runs/<run-id>/review/PAPER_BLIND_REVIEW.md`，再由协调任务导入：

```powershell
python scripts/review/import_review.py runs/<run-id> `
  --kind paper-blind --manifest review/packet/paper-blind/<packet-id>/manifest.json `
  --verdict pass --severity none --thread-id <fresh-codex-thread-id> `
  --argumentation-complete --readability-passed
```

只有逐问“主张—推导—证据—解释—限制”完整、没有空壳章节，且正文字号、图表、分页和公式均可读时，才能带上这两个通过标志。发现空章节或不可读页面时，以 `--empty-section`、`--unreadable-page` 记录并给出非通过 verdict。

PDF 或提交材料变更会撤销盲审。盲审通过后进入 `verify`，由 `$mathmodel-final-check` 做机械检查。

## 最终交付审核

机械 QA 通过并进入 `final_review` 后创建：

```powershell
python scripts/review/build_review_packet.py runs/<run-id> --kind final-audit
```

第三个新审核对话只读该包，不读取前两轮报告或求解上下文。它必须按数学建模竞赛论文标准自由判断题意、模型、推导、算法、结果、图表、源码可复现性、边界和提交规范；不得把预设清单逐项勾选或“表格全通过”当作科学结论。最终 PDF 必须直接包含完整源码附录，不能只给路径。发现问题时给出严重性、位置和应回退的生产阶段，不直接修改文件。报告写入 `review/FINAL_SUBMISSION_REVIEW.md`，再以 `--kind final-audit` 导入。审查发现问题后只允许一次集中修订并重新独立审核；第二次仍未通过则停止，不循环自我修补。只有三轮审核使用不同对话、全部有效且科学强度为 `qualified` 或 `strong` 时才能进入 `complete`。
