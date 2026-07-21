# Codex 原生工作流说明

质量优先试点在 baseline 和最小证伪实验后增加 Markdown
`analysis/SCIENTIFIC_VIABILITY.md`。它不新增状态或回执，只决定继续深化、定向修复、并行
fallback 或停止路线。`ROUTE_AT_RISK` / `ROUTE_FAILED` 不得进入正式论文；详细规则见
`docs/QUALITY_FIRST_PILOT.md`。

## 为什么先做减法

Codex 已能读取题面、操作本地文件、运行 Python/Typst/LaTeX、保存状态并与人工交互。第一版
因此移除了旧 WebUI、Redis、后端队列、Docker 和自建多 Agent 应用，只保留可复用的原始
Skills。这样比赛时间主要投入题意、建模、实验和论文，而不是维护控制面。

## 状态序列

```text
NEW
→ WAITING_HUMAN_ROUTE
→ ROUTE_LOCKED
→ MODEL_SPEC_READY
→ EXPERIMENTING
→ RESULTS_ACCEPTED
→ PAPER_DRAFTED
→ QA_RUNNING
→ WAITING_HUMAN_FINAL
→ COMPLETE
```

主枚举之外，`state.json.review_gates` 是同一状态机内的阶段证明，不是第二套状态机：

```text
MODEL_SPEC_READY --MODEL_SPEC_REVISED--> MODEL_SPEC_READY
MODEL_SPEC_READY --R1_MODELING--> EXPERIMENTING
每问实验完成 --R2_EXPERIMENT_<question_id>--> RESULTS_ACCEPTED
PAPER_DRAFTED --R3_PAPER_LOGIC + R4_FORMAT_VISUAL--> QA_RUNNING
QA 机械通过 --R5_STANDARD_FINAL--> WAITING_HUMAN_FINAL
J0 仅作为可选自然评委模拟，不是最终硬门
```

R1 发现规格补全、实现澄清或验证细节问题时，使用 `MODEL_SPEC_REVISED`，绑定旧/新模型规格、
修复计划和当前路线锁，并将旧 R1 门标记为 `stale`。只有题意解释或路线核心字段发生实质变化
才使用 `ROUTE_DRIFT` 返回人工路线确认。

R1 报告必须包含完整 17 项 coverage 矩阵（目标与约束分别检查），且 `unchecked_items=[]`；矩阵中的每个失败项必须有
对应 finding，防止审核逐轮只暴露少量问题。

其中八项具有运行时最低证据预检：参数可辨识性、模型选择准则、不确定性读取规格文本中的
方法与阈值；数据/附件映射、方程闭合、停止规则、baseline 和 evidence plan 读取每问的
`r1_evidence` 结构。`evidence_plan` 必须与 `PROBLEM_MANIFEST.json` 中该问全部必做
`required_outputs` 精确对应，并逐项给出实验或结果 ID、图表 ID 和论文章节。预检只证明材料
结构完整，不替代审核员对公式、方法和实验质量的判断。

## 独立审核材料与领取协议

每轮审核先生成 `review/<stage>/<round>/REVIEW_INPUT_MANIFEST.json`，逐项冻结材料的 role、
规范化 run 内相对路径、SHA-256、required 和 reviewer 可见性。阶段强制 role 不能由调用方
删除，策略外 role 不能加入；`read_paths` 只能引用 manifest 中的材料并覆盖全部强制项。
运行时会先解析真实路径，再拒绝 `..`、反斜杠别名、越界路径和前轮报告等禁止材料。

审核请求显式冻结 `review_mode`：`full_scientific` 使用阶段完整材料；`targeted_recheck` 只能
包含原 finding、生产裁决、修改前后 diff、修复证据和直接依赖；`diff_check` 只包含原 finding、
生产裁决、局部差异与修复证据；`machine_check` 只包含原 finding、生产裁决和确定性机器
证据。scoped 请求必须绑定既有 `full_scientific` 根门的 gate ID、receipt、report、adjudication
路径及 SHA-256；运行时复验阶段、问题、目标 finding、原裁决关闭模式和当前开放状态。scoped 模式禁止
通过额外 read path 或角色重标记读取完整题面、其他报告、结果、论文或源码。

targeted recheck 只允许复核原问题、修改范围和直接依赖，不得新增无关 P2/P3。新增 P0/P1
必须同时提供与修改的关系、此前无法合理发现的原因、重新打开证据和 production
`reopen_justification`。机器 P1 由 `machine_check` 关闭，科学 P0/P1 由
`targeted_recheck` 关闭，非语义 P2 由 `diff_check` 关闭，P3 可作为不阻断建议关闭。P2/P3
修复若改变科学语义，必须重新分类为科学 P1。经验未知可标记 `deferred_empirical`，但必须冻结
阻断点、关闭条件与失败动作，并登记到 `state.json.deferred_obligations`。开放义务分别在正式实验、
论文完成（当前作为模型选择和 paper claim 的最迟边界）或最终提交前阻断状态推进，只能由绑定原始
根审核的合法 scoped closure 关闭。
`deferred_obligations.status=closed` 不是可信输入；状态推进会从当前完整根、同一 finding 和同一
source receipt 的真实 closure 回执重建关闭状态。R1 的 `model_selection` 义务可在
`EXPERIMENTING` 或 `RESULTS_ACCEPTED` 登记关闭证据。

`review_request.json` 只绑定材料清单，不包含线程身份。生产主对话写完请求后必须停止，向用户
输出独立审核交接提示。用户只需在 Codex 桌面版中新建一个顶层对话并提交该请求；该新对话中的
审核 AI 自动调用对应审核 Skill，读取冻结材料并生成 `review_session.json` 和报告。报告返回
生产主对话完成裁决后，再生成绑定裁决哈希的回执。用户
不需要逐项辅助审核、复现、测量、判分或手工填写报告。领取通过独占创建和仓库级锁串行化，
一个 request 只能领取一次；
`.review_registry/thread_claims/` 保证同一 thread ID 在整个仓库的 `runs/*/review` 中只能领取
一次。subagent、fork、继承上下文和旧 revision 均被拒绝。报告绑定 `session_sha256`，回执继续绑定
input manifest、session、request、report 和 adjudication 五层哈希，
`StateService.record_review_gate()` 只登记或更新 `full_scientific` 完整根门；
`StateService.record_review_closure()` 只向既有完整根追加 scoped 关闭证明，不能替换根回执。
`stale` 根不能再创建或登记 scoped closure；它必须由新的 `full_scientific` 根替换，旧根的
closures 与 deferred obligations 不得继承到新根，只保留在状态历史中。
两者登记前都重新计算五层哈希、逐文件材料哈希、session 身份和仓库级 thread claim；状态推进还会
从根裁决重建未关闭 blocker，并复验每条 closure 的模式、裁决、通过结论和来源链。

`attestation_level=self_declared` 是当前平台未暴露可信父子任务元数据时的诚实声明，不是
密码学证明。只有编排器或平台提供可核验元数据时，才能提升为 `orchestrator_verified` 或
`platform_verified`。

R5 使用原题、模型规格、接受结果、关键代码、复现入口和 QA 做技术全面审核，并禁止读取前轮
审核报告；J0 的强制输入由冻结比赛 Profile 的 `judge_visible_roles` 决定，只能包含该比赛中
评委实际可见的原题、附件、最终 PDF、提交清单或允许提交物，不读取 Profile 未声明可见的模型
规格、结果注册表、QA 或源码清单。旧 Profile 缺少该字段时，才根据
`required_submission_files` 使用兼容推导。

QA hard failure 的唯一修复回路为：

```text
QA_RUNNING → BLOCKED → PAPER_DRAFTED → QA_RUNNING
```

禁止从 `BLOCKED` 直接进入最终批准或完成状态。

`state.json` 是唯一状态来源。每次进入新的桌面任务，先读状态，再读与当前阶段直接相关的
Skill 和产物。关闭任务或发生上下文压缩都不影响恢复。

## 第一个暂停点

`mathmodel-route` 只产出候选路线和简报。候选必须在数学本质、关键假设或决策结构上真正
不同，并同时给出基线、创新、验证、成本、风险和退路。写完后状态变为
`WAITING_HUMAN_ROUTE`，必须停止。

路线候选生成时同时冻结 `problem/PROBLEM_MANIFEST.json`，列出全部题目、必做输出和依赖关系。
人工明确回复后，批准协议物化绑定候选路线、配置锁、问题全集和原始回复的 receipt，再生成
`ROUTE_LOCK.json`。工作流只在批准范围内建模。所有运行时文件显式声明 Schema 名称和 2.0
版本；随后再检查跨文件 ID、文件哈希和证据引用。
改变题意、目标函数、核心约束、
模型类别、未批准路线，或新增实验超过剩余预算的 30%，都要重新暂停。

## 执行闭环

每问执行 baseline、primary、robustness/ablation。每轮先写执行清单，由统一执行器以结构化
参数运行 Python，生成包含退出码、日志、输入输出哈希的不可变执行记录。指标由白名单提取器
生成 provenance，候选结果必须通过约束、基线和来源复验后，才按 RFC 8785 封存；创新主张由
独立 evaluator 评估，不阻断 primary 的事实准入。每问实验完成后先登记 R2 回执，再进入结果
汇总和论文。

审核对话只写本轮审核目录中的 session 和报告，不修改生产代码、模型、实验、论文或
`state.json`，也不直接推进状态。报告返回原生产主对话后，主 AI 必须独立核验 finding 并形成
`REVIEW_ADJUDICATION.json`，再物化绑定裁决哈希的回执和定向修复计划，随后决定状态推进。桌面版 AI 负责读取状态和决定下一阶段；项目不提供调用 AI
的 CLI 调度器。用户完成一次新对话交接后，生产主对话再次调用 `$mathmodel-workflow`，即可从
`state.json` 恢复。

## 第二个暂停点

完整论文和 PDF 后按依赖创建 R3/R4 请求；机械 QA 通过后由用户新开独立对话，交由该对话中的
AI 自动执行 R5，原 J0 的自然评委视角并入 R5。完整 R5 只由核心模型、数据/数字、结论、主图
变化或 P0/P1 重新打开触发，总时间建议为比赛预算的 5%–10%；局部修改只做 scoped recheck，
不生成完整竞赛评分。所有回执必须登记到
`review_gates` 并绑定当前生产事实；未登记或任一绑定变化时，不能进入 `WAITING_HUMAN_FINAL`。
R4/R5 必须绑定机器 `FORMAT_AUDIT.json`；其硬失败不可被文字结论覆盖。R5 必须同时给出 A 轴（`A_PASS`/`A_BLOCKED`）和 B 轴（质量分数及题目覆盖、模型深度、实验验证
分项）；联合结论由程序校验，失败时自动生成 `REPAIR_PLAN.json`，只重跑受影响审核阶段。

## 三种模式

- `competition`：默认轻量主链，两个强制人工点。
- `training`：同一主链，额外记录失败原因和复盘，但不增加评审层。
- `audit`：用于旧题或留出题的严格复现检查，不应成为比赛默认模式。

三种模式共用状态和结果 Schema，避免为模式复制三套文件协议。
