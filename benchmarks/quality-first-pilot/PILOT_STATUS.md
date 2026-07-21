# 试点状态

```yaml
status: CASE_SELECTED
case_id: CUMCM-2023-B
case_title: 多波束测线问题
case_source: official_cumcm_2023_problem_package
selection_reason: >
  陌生多问题工程优化题，适合检验直接答案、信息价值、
  正控制能力、路线切换和完整论文展示质量。
known_exposure: false
model_pretraining_exposure: unknown
allowed_sources:
  - official_problem_statement
  - official_attachments
  - official_format_rules
forbidden_sources:
  - official_commentary
  - same_problem_papers
  - same_problem_code
  - blogs_and_tutorials
  - cross_arm_outputs
human_gate_decision: approved
route_selection_mode: ai_autonomous
interactive_human_modeling_advice: forbidden
next_status: WAITING_BASELINE_FREEZE
```

`known_exposure: false` 只表示当前仓库、当前对话和已登记训练案例中没有系统完成该题的已知记录；
基础模型预训练语料不可审计，因此单独保留 `model_pretraining_exposure: unknown`。该限制对 A/B
两组相同，不得据此宣称真正 held-out 或 production ready。

本次人类决定已明确授权两组 AI 在各自隔离任务中独立生成候选路线、选择期望价值最高的路线并
冻结选择证据，不再等待交互式人工路线选择。该授权仅适用于 `CUMCM-2023-B` 质量试点，不修改
常规生产工作流的人工路线门；AI 不得读取另一组路线或接受运行期人工建模建议。
