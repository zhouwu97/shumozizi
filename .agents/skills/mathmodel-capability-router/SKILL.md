---
name: mathmodel-capability-router
description: 为 Capability-First v3 数学建模赛题选择并冻结求解、交叉、独立验证和本地工具能力。仅在分析完成、实验开始前的 capability_route 阶段使用；用于几何、优化、机理、网络、预测或评价题的能力组合，不生成题目答案或论文。
---

# 建模能力路由

能力路由把已经存在的知识库、Skill 和工具变成当前题的实际执行计划。它不决定答案、不设置质量门，也不以“使用更多能力”为目标。

1. 读取题面、`reports/ANALYSIS_MODELING_REPORT.md`、`state/run.json` 与 `state/DECISIONS.md`。只使用本地知识库；不得联网查同题答案。
2. 从 `geometry_kinematics`、`optimization`、`mechanism_dynamics`、`network_system`、`prediction_statistical`、`evaluation_ranking` 中选一个或多个题型；选一项主能力、至多两项交叉能力、至多一项验证能力。每项必须记录它解决的当前风险。
3. 运行工具探测：

   ```powershell
   python scripts/capabilities/detect_tools.py runs/<run-id>
   ```

   Python 是可用默认生产工具。只有探测成功时才选择 MATLAB 或 Octave；没有 MATLAB/Octave 时不得伪造其可用性。
4. 对几何/运动或机理题，声明并实际运行独立 oracle：优先使用不同语言/运行时；否则使用不同数学推导和不共享领域判定源码的独立实现。不能把同一函数换采样密度称为独立验证。运行须以 `kind=independent-oracle` 通过 v3 执行器登记；替代运行时/语言时，登记的输入源码必须是相应 `.m` 或 `.py` 文件。状态机拒绝只声明未运行 oracle 的 `experiment -> scientific_review`。
5. 选择最多五个本地知识资产。主能力可读取相关 `knowledge/cards/`、一个 Cookbook、`skills/2analysis-modeling/SKILL.md` 的相关段；优化题额外选择搜索充分性或不确定性资产。资产只能帮助生成候选，不替代建模判断。
6. 写入 JSON 后登记：

   ```powershell
   python scripts/capabilities/record_route.py runs/<run-id> `
     --input code/capability-route.json
   ```

   `toolchain.production_engine` 必须真实可用。`alternative_runtime` / `alternative_language` 必须选不同的 `independent_engine`。随后才可进入 `experiment`。

最小结构：

```json
{
  "schema_version": "1.0",
  "run_id": "<run-id>",
  "status": "ready",
  "problem_families": ["geometry_kinematics", "optimization"],
  "primary_capability": {"id": "geometry-kinematics", "reason": "有限视线与连续目标是主风险。"},
  "cross_capabilities": [{"id": "nonsmooth-optimization", "reason": "遮挡窗口使目标函数存在不连续事件边界。"}],
  "verification_capability": {"id": "independent-segment-oracle", "reason": "需与生产几何判定使用不同推导复算边界。"},
  "toolchain": {"production_engine": "python", "independent_engine": "octave", "independence_strategy": "alternative_language", "reason": "Octave 可独立求根并生成三维核验图。"},
  "knowledge_assets": [{"path": "knowledge/cards/structural-preflight.json", "purpose": "检查退化、单位和小规模 oracle。"}],
  "created_at": "2026-07-23T00:00:00Z"
}
```
