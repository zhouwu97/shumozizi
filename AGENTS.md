# shumozizi Competition-First v3.1 项目约定

## 目标

这是 Codex 桌面版驱动的数学建模工作台。生产主链的唯一目标是在同等模型、时间、Token、算力和资料条件下，提高路线质量、实验价值、结果洞察和匿名论文表现。不要把 Schema、审核任务、哈希、回执或全绿测试当作竞争力证明。

新 v3.1 运行使用：

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

`blocked` 仅用于真实生产失败或实际负面证据，不能因为缺少 metadata、可选文档或旧协议文件阻断。旧 v3.0 状态只读兼容：读取时映射 `capability_route -> analysis`、`scientific_review/visualization -> experiment`、`final_review -> verify`；第一次显式更新才保存 v3.1 和迁移日志。

## 主动 Skill

完整赛题只使用以下六个主动 Skill：

- `mathmodel-workflow`
- `mathmodel-solve`
- `mathmodel-experiment`
- `mathmodel-visual`
- `mathmodel-paper`
- `mathmodel-red-team`

`mathmodel-matlab`、`mathmodel-geometry-oracle`、`mathmodel-geometry-visual`、`mathmodel-optimizer-benchmark` 和 `mathmodel-learn-paper` 是按需工具。`mathmodel-capability-router` 仅为旧运行或按需工具探测保留，不能成为新运行阶段。`mathmodel-final-check` 只执行机械 QA。

局部分析、调试或论文修改不得自动启动完整工作流。

## 路线与实验

- 分析先识别题意、数学结构、baseline、实质不同的竞争或反证路线和最低成本区分性 probe。
- 每题至少有一个 baseline 和一个数学结构不同的竞争路线。单纯替换 GA、PSO、DE 等求解器属于同一路线比较。
- 将主路线、fallback、切换条件写入 `analysis/ROUTE_COMPETITION.md`；将只有决策价值的实验写入 `analysis/NEXT_EXPERIMENTS.md`。
- 实验必须真实执行，使用 `scripts/runtime/run_simple_experiment.py`。论文数字和图表只能来自 `current` 且 `execution_valid=true` 的生产结果。
- `analysis/method_facts.json` 是自动推断的建议；`method_profile.json`、`critical_claims.json` 是 legacy 兼容，均不参与 v3.1 跳转。
- 负面证据仍必须优先级联失效结果、图表和论文：反例、独立复算冲突、不可行、性质测试失败、proxy/exact 冲突、incumbent 不具竞争力都不能被报告文字覆盖。

## 审查

只有高影响且未解决的目标歧义才触发独立目标语义审查。判断来自 `analysis/objective-ambiguities.json`：至少两个合理解释、可能改变主结果、题面未排除、用户未裁决。

实验结束做一次自由科学挑战，报告 `review/SCIENTIFIC_CHALLENGE.md`。允许的专项追问最多一个，写入 `review/FOCUSED_FOLLOWUP.md`。不得创建默认 `required_risks`、coverage declaration、逐风险 follow-up 或 final audit。

PDF 盲评写入 `review/PAPER_BLIND_REVIEW.md`，要给出相对普通参赛论文的判断。P0/P1 与已验证负面证据始终阻断。PDF 盲评无法创建时必须明确写 `review/PAPER_BLIND_REVIEW_SKIP.md` 的原因；该说明只允许继续机械 QA，绝不能将运行标记为 `complete` 或 `submission_ready`。

## 图表与论文

- 图表输出默认在 `figures/current/`。每张图只需要真实来源、它回答的问题、读者看到的 takeaway，以及可选边界；不得为每题、3D、多种子、敏感性或双版本输出凑数量。
- 图必须由当前数据和当前脚本实际生成，PNG/PDF 可读，并在结果变化后失效。
- 论文只硬性要求每个必答问题在 `analysis/answer_map.json` 或 `paper/answer-map.json` 有直接答案位置和当前结果。运行时会自动生成 `paper/generated/argument_map.json`。
- `paper/STORYBOARD.md` 和 `paper/CONTRIBUTION_BRIEF.md` 是提高质量的软产物；贡献最多三项，不能把常规方法组合包装为创新。
- 小的正文文字改动只需重新编译和机械 QA；影响结论或图表的改动需重新盲评；代码、数据、目标或主要结果改动需回到实验和科学挑战。标记 `complete` 前必须重新验证科学挑战仍绑定当前生产事实。

## 工程约束

- Python 模块、类和公共函数使用 Google 风格 docstring；注释使用中文并解释 WHY。
- 写入运行目录使用原子写入或同目录安全替换；路径必须限制在运行目录内。
- Windows 可运行，不依赖 Bash；不自动提交或推送 Git。
- 不修改 `legacy/review-v2/` 的业务语义。旧协议函数可保留兼容，但不得成为 v3.1 主链硬门。
- 运行 `python -m pytest` 和 `python -m ruff check src scripts tools tests`。测试通过只证明工程行为，不证明竞赛竞争力；后者必须由 `evaluation/` 中的 held-out A/B、错误注入和匿名 pairwise 验证。
