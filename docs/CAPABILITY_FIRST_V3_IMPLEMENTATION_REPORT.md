# Capability-First v3 实施总结

日期：2026-07-22
目标：将主动生产主链从审核生命周期模式迁移为 Capability-First v3，同时冻结 legacy-v2，保留可恢复性、真实执行证据和确定性提交检查。

## 实施结论

v3 的并行运行时、主动 Skill、按需知识库、机械 QA、迁移边界和回归测试均已实现。新运行完全位于 `shumozizi.simple`，不导入旧 `StateService`、审核、回执、裁决或闭环模块；自动发现目录仅保留六个 v3 Skill。

尚未把 v3 设为默认，也没有删除 legacy-v2。该限制是计划本身的安全条件：默认切换必须先在同一陌生完整旧题、同一模型与同一时间预算下完成真实 A/B，且由独立盲评确认质量不低于旧链。代码测试不能代替该经验验证，因此没有伪造 A/B 结论。

## 已交付内容

### 1. 并行 simple 运行时

新增 `src/shumozizi/simple/`：

- `initialization.py`：创建计划定义的 v3 目录、隔离复制题面与附件、初始化最小状态、决策记录、结果索引和空图表索引；
- `state.py`：Schema 校验、原子读写和受保护的修订更新；
- `execution.py`：固定 `shell=False` 运行、保存 stdout/stderr、退出码、耗时和失败原因；
- `results.py`：记录源脚本、命令、输入输出路径和 SHA-256，维护 `current`、`superseded`、`failed` 状态，并在终检时重新校验 current 结果的输入、输出和指标来源哈希；
- `figures.py` 与 `figure_templates.py`：仅对已接入的真实数据模板，登记源结果、保留模板源、渲染器、三种图表输出和文字 artist 边界，并在终检时复验它们。

新增 Schema：

- `schemas/simple_run_state.schema.json`（状态版本 3.0）；
- `schemas/simple_result_index.schema.json`（结果索引版本 1.0）。
- `schemas/simple_figure_index.schema.json`（图表索引版本 1.0）。

新增入口：

```powershell
python scripts/codex/init_run.py <problem_path> `
  --workflow capability-first-v3 --run-id <run-id>

python scripts/codex/init_simple_run.py <problem_path> --run-id <run-id>

python scripts/runtime/run_simple_experiment.py runs/<run-id> `
  --question Q2 --kind primary --command "python code/q2.py" `
  --expect results/raw/q2.json
```

`init_run.py` 的 legacy-v2 默认行为仍保持兼容；v3 必须显式选择，直到 A/B 通过后再变更默认值。

### 2. 主动 Skill 与 legacy 归档

`.agents/skills/` 现在恰好包含：

```text
mathmodel-workflow
mathmodel-solve
mathmodel-experiment
mathmodel-paper
mathmodel-final-check
mathmodel-learn-paper
mathmodel-capability-router
mathmodel-visual
mathmodel-matlab
mathmodel-red-team
mathmodel-geometry-oracle
mathmodel-geometry-visual
mathmodel-optimizer-benchmark
```

新 Skill 采用“分析/路线比较 → 真实实验 → 论文 → 一次终检”的连续主链，限制无意义的全量读取、固定实验族、重复审查和顶层任务膨胀。路线切换以 probe 和 `DECISIONS.md` 为依据；只有题意、核心目标、必做输出或重大预算变化才请求用户决定。

旧审核、路线和检索 Skill 已迁移至 `legacy/review-v2/skills/`，相关历史文档迁移至 `legacy/review-v2/docs/`。它们仍受冻结回归测试保护，但不再自动发现，也不会被 v3 运行时调用。

### 3. 机械 QA 与论文追溯

新增 Windows 可运行的工具：

- `tools/qa/figqa.py`：检查图片可读性和绘图脚本导出的文字边界重叠；
- `tools/qa/pdf_qa.py`：检查 PDF 打开、空白页、文字裁切/重叠、重复图表编号和可选匿名元数据；
- `tools/qa/make_contact_sheet.py`：渲染 PDF 联系表；
- `scripts/qa/check_placeholders.py`：扫描源文件占位符；
- `scripts/qa/check_result_references.py`：检查源码注释中的 `@result` 只引用 `current` 且 `execution_valid=true` 的结果；
- `scripts/qa/check_numeric_consistency.py`：将源码注释中的 `@metric` 与结果索引内、由当前 JSON 输出提取的真实指标比对；
- `scripts/qa/run_final_checks.py`：聚合上述检查，生成 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 与 `reports/VERIFY_REPORT.md`。

机械 QA 只报告确定性问题，最终科学审查仍由 `mathmodel-final-check` 在完整论文、代码和结果的上下文中写入 `qa/FINAL_REVIEW.md`，按 P0–P3 分级。图表和表格重复编号采用图注/表题行匹配，当前作为 warning，避免正文“如图 1 所示”造成硬阻断；匿名检查必须通过 `--anonymous` 显式启用，附加身份词可通过 `--anonymous-term` 指定。

### 4. 知识、模板与来源边界

新增可按需读取的知识文件：问题拆解、模型选择矩阵、预测/优化/评价/机理/统计学习/网络系统 Cookbook、模型检验菜单、论文写作说明和 Figure Contract。每个文件明确“仅生成候选，不能自动决定路线”，并在 `knowledge/README.md` 规定当前阶段最多读取一到两个相关文件。

原有十个主动 Skill 保持主工作流职责，三个新增入口只处理几何 oracle、空间证据图和优化器公平比较。`mathmodel-solve` 按题型调用已保留的分析建模能力、一个 Cookbook 和适配的算法模板；`mathmodel-paper` 按比赛类型参考对应论文模板。科研模板渲染、真实 LaTeX、真实 Typst 和模板矩阵已拆成独立阻断 CI job。

科研绘图能力的状态必须如实区分：仓内保留 11 套演示模板，v3 已以真实 JSON 结果、运行目录源/输出哈希和终检失效检查接入其中 4 套（`cv-roc-ci`、`prediction-marginal-grid`、`paired-raincloud`、`correlation-pairgrid`）。其余 7 套仍只作为可运行演示和布局参考，不能进入 v3 论文证据链，也不能称为“已接入”。详细数据接口、调用和失效规则见 `docs/V3_FIGURE_TEMPLATE_ADAPTER.md`。

`THIRD_PARTY_NOTICES.md` 已更新：v3 QA 是对参考项目思路的独立 Windows 实现，不复制其工作流、状态机或审核机制。现有 MathModelAgent 模板作为能力基线继续保留。

### 5. 文档与运行边界

已重写：

- `README.md`：v3 架构、命令、目录、主动 Skill、机械 QA 和 legacy 状态；
- `AGENTS.md`：v3 运行约束、结果证据边界、预算策略、论文追溯和禁止事项；
- `docs/CODEX_WORKFLOW.md`：连续生产、一次整体审查和定向修复流程。

## 验证结果

新增 `tests/test_capability_first_v3.py`，覆盖：

- v3 初始化、题面/附件隔离复制和最小状态更新；
- Windows 带空格 Python 路径的真实子进程执行；
- 输入输出哈希、日志、结果替代和论文可用性；
- v3 CLI 初始化；
- PDF 缺失时可定位的机械 QA 报告；
- 图表文字边界重叠检测；
- 真实 PDF 联系表生成；
- 主动 Skill 目录只包含六项 v3 能力。

### 6. 评审后的确定性加固

在合并前评审中发现的确定性问题已进一步收敛：

- 实验 CLI 不再接受手工 `--metric`；指标只能从本次注册的 JSON 输出中，经 `--metrics-from` 或 `--metric-path` 提取，并保存 JSON 路径与输出文件哈希；
- 结果资格字段统一为 `execution_valid`，仅表示执行证据仍可验证，不将科学质量混入索引状态；
- `run_final_checks.py` 会重新计算所有 current 结果的输入、输出和指标来源哈希，失败覆盖输出会阻断终检；
- `@result`、`@metric` 追溯标记只存在于 Typst/LaTeX/Markdown 注释；旧的可渲染双中括号标记会被源码和 PDF 检查拦截；
- 匿名检查支持 PDF 元数据与用户指定身份词，并在 `--anonymous` 启用时成为硬检查；
- v3 运行阶段收敛为 `analysis → experiment → paper → verify → complete`，避免 `analysis` 与 `solve` 的职责重叠；
- Windows PR CI 现在覆盖 v3 运行时、主动 Skill、机械 QA 与核心 legacy smoke；完整 legacy 回归改为每周定时或手动触发，避免其重型审核闭环拖慢 v3 小改反馈。
- v3 图表适配器只接受已登记的 current JSON 结果，输出 PNG/PDF/SVG、文字边界和哈希索引；源结果被替代、输入/输出/脚本哈希漂移或图表被标记为 demo 时，`current-figure-files` 会阻断终检。

此前主链改造完成后的历史基线为 241 条；本轮新增图表适配测试后，当前收集数为 245 条。本轮可在本机命令时限内完成的验证结果：

```text
python -m pytest --collect-only -q
245 tests collected

python -m pytest -q tests/test_v3_figures.py tests/test_capability_first_v3.py tests/test_init_run.py
16 passed

python tests/figure_template_smoke.py
已验证 11 套冻结演示模板，且四类 v3 真实数据适配器通过

python -m ruff check src scripts tools tests
All checks passed

python -m py_compile <v3 CLI、QA 及 simple 运行时入口>
All checks passed

git diff --check
No whitespace errors
```

本轮再次执行完整 `python -m pytest -q` 时被桌面运行器的 10 分钟上限终止，未把它记作通过或失败；完整 frozen legacy 回归仍由每周定时或手动 CI（30 分钟）执行。新增代码所影响的 v3、初始化和图表测试已在本地通过。迁移暴露的一处旧测试路径已更正为读取 `legacy/review-v2/skills/mathmodel-review/`，不会恢复该 Skill 的自动发现。

冻结 v2 的审核合同测试保留并通过；其中的路径断言已改为验证 `legacy/review-v2/skills/` 的归档完整性，而不是要求旧 Skill 继续自动发现。

### 7. Capability-First v3 解题能力与质量协议重构

本轮发现的根因不是缺少更多质量字段，而是质量层允许 generator 的同一份 JSON 同时声明候选、可行性、exact 重算、搜索充分性和题目进展。文件哈希只能证明这份 JSON 未变，不能证明题目数学被独立重算；同样，申报的 coverage 数字不能证明原始高维候选真的覆盖了合同所述的联合区域。旧的挑战语义还把“未改善”机械视为失败，反而可能让较弱挑战影响已验证 incumbent。

v3 因而将搜索型生产结果拆为三段题目特定 adapter：candidate generator 只产出原始 candidate pool、参数、代理值和完整 trace；exact scorer 独立重算硬约束、可行性与 exact objective；search auditor 从原始 pool/trace、合同和 scorer 产物重算覆盖、校准、挑战独立性与选择影响。题目合同声明三个 adapter 的 id/version、受控相对源路径、允许命令、输入输出、hash、目标方向、约束、变量组、覆盖度量和挑战可比标准。generic runtime 只验证 provenance、路径与漂移，拒绝未受控命令、路径越界、输入变化、输出漂移和版本不一致；题目数学仍是 adapter 作者的职责，而非 generic runtime 的能力声明。

覆盖审计直接使用原生 pool/trace 坐标。共同变量组、实体变量组和交互变量组必须按合同各自重算明确度量；平均、首元素、低维投影或 generator 自报的 `joint_coverage` 都不能作为 accepted 证据。代理校准改为关注决策相关指标，例如 top-k recall、局部改善方向、边界/高价值区域误差与筛选影响，只有可能反转选择结论的灾难性错误阻断。

挑战允许显式标记的 baseline/warm start，但必须另外证明独立新候选、独立覆盖和实际新区域。独立、充分且达到预登记可比标准但不改善的挑战支持 incumbent 稳定性；充分但较差的挑战只是无信息或较弱搜索族；只有 scorer 或模型语义错误可以推翻 incumbent。verified candidate registry 保持单调：同一目标语义下，弱、较差、legacy 或不可审计候选不能覆盖 current verified incumbent。

运行与质量语义新增 `exploration` / `production` 用途边界，但不增加 phase、总控 Skill、审批或固定算法。探索可使用未 accepted 的上游诊断候选研究后续问题、共享结构或反向诊断，产物永久保持 diagnostic，不能进入 registry accepted/current、论文、图表或提交；生产正式下游仍要求合同指定的前序 accepted/current。旧质量记录和旧自报布尔字段统一降为 `diagnostic/unverified`，除非在当前合同下补齐三段独立证据及 provenance。

生产结果冻结后，论文阶段还可按需读取 1-2 张已登记的离线论文卡，用于章节组织、模型解释表达、验证叙事或 Figure Contract。该轻量 reference interface 不调用或合并 `mathmodel-learn-paper`；卡和原论文中的数值、结论、代码、原公式段、实验结果均不得迁移，也不得成为 citation、evidence 或 Claim-Evidence 材料。

论文交付同时采用贡献账本和五问内容蓝图。账本只接受与当前运行证据和限制相连的题目特定结构、模型、算法、实证或表达贡献；通用 Skill、质量协议、adapter、已有算法的直接调用和普通图表不被称为数学创新。若证据仅支持工程实现或方法组合，论文必须如实说明。若声明题目数学创新，账本还绑定机制差异、可检验预测、明确指标/方向的对照改善和单组件消融；对照/消融可使用角色独立的结果，或在同组 registry 只有一个 incumbent 时使用同一 primary exact scorer 的两个受控 sidecar，且绝不能由单一结果或 sidecar 自证。该账本不自动评分、不要求创新数，也不替代 adapter 的数学判断。Q1-Q5 各自需要可定位的直接答案，以及题目解释、模型/公式、实际求解、当前结果、验证和限制等内容块。终检在 `qa/FINAL_REVIEW.md` 报告 PDF 内容异常，包括五问直接答案覆盖与页数、公式、图、表、引用的可疑密度；页数或任一密度单独异常只作 warning，不单独阻断。已登记的离线论文卡收据和贡献账本会在机械 QA 中重放，任何冻结结果、受控索引/卡哈希或当前证据漂移均阻断终检。

这项重构强化的是证据分层、可复验性和搜索结论的解释，不是对模型实际解题能力的实证。它不能证明模型正确理解题意、选择了正确路线、adapter 的数学实现无误、假设有效，或论文具备竞赛竞争力。那些主张仍需要结构预检、低成本 oracle、真实实验、适当验证、完整论文审查，以及冻结条件下的陌生完整赛题 A/B。

## A/B 与默认切换的剩余执行条件

以下不是未实现的代码功能，而是必须由真实赛题运行产生的外部证据：

1. 选一套陌生完整旧题，冻结模型、附件、时间、工具权限与初始提示；
2. 分别运行 legacy-v2 和 v3，保留 PDF、代码、结果、运行说明和 token/时间统计；
3. 对最终材料做不暴露工作流的盲评；
4. 验证 v3 的顶层任务数不超过 3、前 20% 预算内得到 baseline/probe、关键数字真实执行、逐问直接回答、致命科学错误更少或相等、盲评分不低于 legacy；
5. 仅在满足条件后，将 `init_run.py` 的默认 workflow 改为 `capability-first-v3`，再决定是否进一步归档旧代码。

远端发布状态应以 GitHub PR 页面为准；本报告只陈述代码与本地验证，不用本地测试替代 A/B 或默认切换的真实赛题证据。
