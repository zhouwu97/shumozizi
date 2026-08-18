---
name: mathmodel-bzd-challenger
description: 基于 BZD 知识库执行题面逐句 Ledger 提取、隔离 Challenger 路线打擂与外部评委攻击。用于分析前置审查、异构路线拓宽及论文评委视角缺陷提取；不把外部主观打分和位次作为正式结论。
---

# BZD 题意、路线与评委增强

本技能作为外部增强桥接，分为三个明确阶段角色，严格服从 Competition-First 事实裁决：

## 1. 分析前置：题面逐句 Ledger (`analysis`)

- 使用 `python scripts/challenger/run_bzd_translator.py <run_dir>` 生成提示词。
- 任务：从题目标题第一句开始，逐句建立覆盖表格，提取明示条件、隐含信号、漏读风险与各问输入输出。
- 输出目标：`analysis/external/bzd-problem-ledger.md`（必须包含全问覆盖的 Mermaid 跨问联动图）。
- 原则：题面原句为一级硬事实，BZD 解释为二级参考，潜在歧义汇入 `analysis/objective-ambiguities.json`。

## 2. 路线竞争：独立 Challenger 打擂 (`analysis`)

- 使用 `python scripts/challenger/run_bzd_challenger.py <run_dir>` 生成隔离提示词。
- 上下文隔离：在新建独立 Thread/Subagent 运行，**只输入 `problem/` 与可选 Ledger**；严禁向其泄露本地已选路线、代码或实验结果。
- 候选提取：输出保存到 `analysis/external/bzd-route-candidates.md`，使用 `--extract` 抽取具备实质数学结构差异的候选路线 B/C。
- 擂台裁决：BZD 候选与 shumozizi 主路线 A 一起进入 `ROUTE_COMPETITION.md`，在同一 Exact Scorer、同等数据和计算预算下运行最低成本 Probe / 真实实验，由实测证据决定胜负，禁止 LLM 主观投票。

## 3. 论文评阅：外部评委视角攻击 (`paper_review`)

- 使用 `python scripts/review/show_bzd_judge_prompt.py <run_dir> --stage rubric` 生成阶段一提示词：仅读题面，独立构建 100 分制评分细则并保存至 `review/external/bzd-frozen-rubric.json`。
- 使用 `python scripts/review/show_bzd_judge_prompt.py <run_dir> --stage judge` 生成阶段二提示词：依据预冻结细则与冻结 PDF，输出评委评审报告 `review/external/bzd-review.md`。
- 使用 `python scripts/review/sanitize_bzd_review.py <review_file>` 进行清洗：
  1. 剔除推广广告、社群联系方式；
  2. 剔除 90% 打分天花板截断和主观位次预测；
  3. 提取 P0/P1/P2 结构化缺陷至 `review/external/bzd-review-findings.json`，合流进入修论文台账。
