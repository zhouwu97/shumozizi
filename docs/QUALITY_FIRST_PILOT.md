# 质量优先试点

## 目标与边界

当前阶段只验证：在相同比赛预算、模型、工具和人工干预下，研究循环能否更早停止失败路线，
并提高完整论文对题目的直接回答、实验说服力和盲评质量。状态数、Schema 数、审核轮数和文档
长度不是成功指标。

暂停通用语义传播、Pattern 平台扩张、跨问依赖状态机、`RESULTS_VERIFIED` / `MODEL_SELECTED`
状态和更多回执链。只有完整陌生题试点证明这些能力是瓶颈时才恢复。

## 四类硬门

- H1 真实性：核心数字无真实执行来源，结果/引用伪造，代码结果明显不一致或关键产物不可验证；
- H2 必做问题：题意误读、required output 缺失，或用预测/拟合任务替代关联、决策、机理或方案；
- H3 科学有效性：泄漏、单位/硬约束错误、正控制无检出能力、关键参数不可辨识却输出确定结论，
  或核心比较不公平；
- H4 提交：文件不可打开、严重裁切、匿名/官方硬格式违规或缺少必交文件。

其余问题按 P1-P3 表达质量影响。Reviewer 先自由诊断，再映射结构字段。

## 研究循环

```text
重构题目目标
→ 最简单 baseline
→ 冻结最低科学合同
→ 识别最高风险不确定性
→ 最低成本证伪实验
→ Scientific Viability Check
  ├─ VIABLE: 深化
  ├─ WEAK_BUT_REPAIRABLE: 定向修复
  ├─ ROUTE_AT_RISK: 并行最小 fallback，禁止正式论文
  └─ ROUTE_FAILED: 停止 primary，返回路线竞争
→ 正式结果
→ 论文与盲评
```

初始化与复验：

```powershell
python scripts/codex/scientific_viability.py init-contract runs/<run_id> `
  --source runs/<run_id>/problem/PROBLEM_MANIFEST.json

python scripts/codex/scientific_viability.py verify-contract runs/<run_id>

python scripts/codex/scientific_viability.py init runs/<run_id> `
  --question Q1 --question Q2 `
  --source runs/<run_id>/results/result_registry.json

python scripts/codex/scientific_viability.py verify runs/<run_id>
python scripts/codex/scientific_viability.py verify runs/<run_id> --paper-entry
```

`analysis/MINIMUM_SCIENTIFIC_CONTRACT.md` 必须在正式实验前冻结 required outputs、核心目标、
硬约束、baseline、primary 模型族、数据划分、主要指标、positive control、路线失败判据、
fallback 条件和主要实验预算。`--paper-entry` 要求 viability 已允许进入论文；
`ROUTE_AT_RISK` / `ROUTE_FAILED` 均不能通过。

阈值必须引用题目容许误差、工程尺度、决策边界、baseline、搜索域或领域合理范围。不得给所有
题统一规定准确率、AUC、误差或区间覆盖阈值。

## 冻结补充证据

Reviewer 可请求与当前 finding 直接相关的原始数据摘要、中间结果、正控制、baseline、目标/约束
说明或图表源数据。生产主对话使用轻量 helper 冻结单问题证据包：

```powershell
python scripts/codex/scientific_viability.py freeze-supplemental `
  runs/<run_id> q2-positive-control R2_EXPERIMENT "核对 Q2 合成恢复" `
  --question-id Q2 `
  --material synthetic=results/q2_synthetic.json
```

创建审核请求时同时绑定：

- `supplemental_evidence_manifest`：生成的 `SUPPLEMENTAL_EVIDENCE.md`；
- `supplemental_evidence:synthetic`：原材料路径。

请求和输入清单会再次冻结逐文件哈希。禁止历史审核结论、作者辩解和未冻结临时说明。

## R1-R5 定位

- R1：路线是否值得进入最小实验，必须有目标/输出/指标一致性、正控制、失败判据和真实 fallback；
- R2：结果是否有信息量、通过正控制且值得继续；强耦合问题可联合审核，但必须逐问结论；
- R3：题目目标、模型输出、指标、accepted result 和论文直接答案是否闭合；
- R4：分别输出 `FORMAT_HARD_COMPLIANCE` 与 `PRESENTATION_QUALITY`；
- R5：只有核心模型、数据/数字、结论、主图或 P0/P1 重新打开时完整重审。局部排版只做 scoped
  recheck。取消固定三轮或五轮上限，完整 R5 总时间建议控制在比赛预算的 5%–10%；无核心变化
  时禁止重复完整 R5，核心变化但预算不足时由人决定提交或终止。scoped R5 不生成完整竞赛评分。

R5 范围判断可机械复验：

```powershell
python scripts/codex/scientific_viability.py r5-scope --change core_conclusion
python scripts/codex/scientific_viability.py r5-scope --change typography
```

## CUMCM 2025 B 回放

版本化回放位于 `benchmarks/cumcm-2025-b/quality-first-replay/`。它绑定真实运行快照的文件哈希，
并证明最迟在正式论文前应当得到 `ROUTE_FAILED`：Q1 已出现极端合成恢复失败，Q2 区间和误差
失去决策信息，Q3 模型选择正控制接近随机。诚实报告这些失败是必要的，但不能把它们包装成
完整成功解答。

## 陌生题 A/B 验收

只选一套未见过的多问题赛题，禁止检索同题论文。A 使用当前 main，B 使用本试点；保持相同模型、
时间、工具、数据、初始人工信息和 Prompt 总预算，Reviewer 不知道流程版本。两组都必须形成完整
PDF 并接受独立外部盲评，才允许比较题目完成度、模型合理性、实验说服力、结论价值、摘要、图表
和整体竞争力。

该阶段必须遵守路线确认与最终确认两个人工门。仓库不能替用户创建独立顶层审核对话，也不能
伪造盲评分数。协议和记录模板见 `benchmarks/quality-first-pilot/`。

停止扩展条件：新流程未更早识别失败路线；盲评无明显改善；耗时增加超过约 20% 且质量无相应
提升；新机制只增加字段而不改变路线；或连续两轮只修生命周期边界而未运行完整题。
