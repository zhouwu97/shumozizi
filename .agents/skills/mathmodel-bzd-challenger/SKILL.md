---
name: mathmodel-bzd-challenger
description: 基于 BZD 知识库与双解题大脑 (Dual-Solver) 执行独立全题建模、科学陪审团 (Scientific Jury) 代码交叉复算与外部评委攻击。用于拓宽解题上限、方案深度融合与论文评委视角攻击；不搞形式主义，以真实代码与算力决定最优方案。
---

# 双解题大脑 (Dual-Solver) 与科学评审团 (Scientific Jury) 协作规范

本技能承载“第二独立解题大脑 (Solver B)”与“科学评审团 (Scientific Jury)”的核心桥接，彻底摒弃 route hash 等繁文缛节，依靠真实独立新对话与代码复算提高解题上限：

```text
               原始赛题 + 全部数据附件
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
   【新对话 A】                       【新对话 B】
   shumozizi 独立完整解题             BZD 独立完整解题 (原版Skill+Refs)
   (题意形式化/代码/计算/保守结论)       (原题输入包/推导/算法/验证/论文结构)
        │                                 │
        ▼                                 ▼
   产物：对话记录A + 代码A + 结果A    产物：对话记录B + 代码B + 结果B
        └────────────────┬────────────────┘
                         ▼
        【新对话 C：Scientific Jury 总评审】
                         │
     ├─ 重新通读原始题面与全部附件
     ├─ 深度审核 A 与 B 的题意理解、数学模型、约束覆盖与算法实现
     ├─ 独立交叉复算核心数值与边界反例（不因数值大小或模型复杂度偏信，验证约束/口径/收敛）
     ├─ 逐问独立裁决：采纳 A / 采纳 B / 融合 A+B / 推翻重做
     └─ 输出统一方案：`analysis/FINAL_SCIENTIFIC_PLAN.md`
                         ▼
        【正式实验重跑与必要补强】（由 Jury 确定的最优模型产出 current production 结果）
                         ▼
        【④ Author】（拿最终 Plan + 真实结果 + 高级科研图，自然写入选型对比与机制分析成文）
```

---

## 1. 独立解题大脑准备 (Solver B)

- 运行 `python scripts/dual_solver/prepare_solver_b.py <run_dir>` 生成独立提示词与干净隔离包（`analysis/dual_solver/solver_b_packet/`）。
- 在新对话 B 中，使用加载的上游原版 BZD Modeling Ideas 技能与近五年国赛蒸馏 References 知识库，独立完成整题建模、推导、Python 实现与计算。
- 解题结果归档至 `analysis/dual_solver/solver_b/SOLUTION_B.md` 及附带的代码与结果。

## 2. 科学评审团交叉复算与融合裁决 (Scientific Jury)

- 运行 `python scripts/dual_solver/run_scientific_jury.py <run_dir>` 生成包含 10 项严苛审核规则的 Jury 提示词。
- 在新对话 C (Scientific Jury) 中：
  1. 重新从原题出发审题，审查题意忠实度与约束完整性；
  2. 严禁因模型更复杂或数值看似更优就直接判胜；
  3. 审查目标同一性、数据口径、未满足约束与收敛性；
  4. 执行代码复算与边界反例检验；
  5. 逐问独立裁决：**采纳 A / 采纳 B / 融合 A+B / 均推翻重做**；
  6. 组合产生比 A、B 单一方案都显著更强的最终方案。
- 运行 `python scripts/dual_solver/run_scientific_jury.py <run_dir> --import-verdict`，将裁决一键导出为 `analysis/FINAL_SCIENTIFIC_PLAN.md`，直接指导后续生产实验重跑与论文撰写。

## 3. 论文外部评委攻击 (`paper_review`)

- 论文初稿编译完成后，作为外部红队评委进行攻击：
  - `python scripts/review/show_bzd_judge_prompt.py <run_dir> --stage rubric`：独立构建 100 分制评分细则 (`review/external/bzd-frozen-rubric.json`)；
  - `python scripts/review/show_bzd_judge_prompt.py <run_dir> --stage judge`：基于原题、细则与冻结 PDF 输出评委报告 (`review/external/bzd-review.md`)；
  - `python scripts/review/sanitize_bzd_review.py <review_file>`：彻底清洗广告与分数，提取 P0/P1 缺陷合流进入 `paper/repair-directives.json`（`MODEL_REPAIR` 缺陷必须绑定新生产结果才能关闭）。
