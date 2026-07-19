---
name: mathmodel-experiment
description: 在人工路线已锁定后，按子问题执行 baseline、primary、robustness 或 ablation 的有界实验，实际运行代码并把候选与已接受结果写入结果注册表。用于数学建模求解、验证和复现实验。
---

# 有界建模实验

包装上游编程能力，但把实验限制为可执行、可比较、可追踪的三轮主循环。

## 前置条件

1. 读取 `state.json`、`brief/ROUTE_LOCK.json` 和数学规格。
2. 只有 `route_locked=true` 且状态为 `MODEL_SPEC_READY` 或 `EXPERIMENTING` 才能执行。
3. 完整读取 `skills/3coding-visual/SKILL.md`，沿用其中的代码、图表和复现要求。
4. 当结果图型命中项目原生模板目录时，读取 `skills/mathmodel-figure-templates/SKILL.md`，复制对应脚本后替换为当前 accepted-result 数据；模板中的模拟数据只能用于样式预览，禁止直接写入论文。
5. 已完成的循环从状态和结果注册表恢复，不要因为新会话而重跑。

## 每个子问题的三个循环

1. `baseline`：先实现简单、可靠、可解释方法，验证数据、单位、指标和约束。
2. `primary`：实现锁定主模型，量化相对基线改善、代价、可行率和稳定性。
3. `robustness` 或 `ablation`：按题型选择灵敏度、误差、扰动、交叉验证、蒙特卡洛、
   外推或约束边界测试。

每轮都必须先按 `schemas/execution_manifest.schema.json` 写结构化执行清单，再调用：

```powershell
python scripts/runtime/execute_experiment.py runs/<run_id> <manifest.json>
```

执行器固定使用 `shell=False`，并保存不可变清单、标准输出、标准错误、退出码、输入哈希、
输出哈希和随机种子。不得直接运行未登记实验，也不得把管道、重定向或复合命令装进字符串。
失败时
依次修复代码/数据、调整同路线参数/求解器、使用已确认备用路线；再失败则触发路线漂移，
不得自行选择新模型类别。

## 结果注册

执行完成后，把引用 `execution_record_id` 的新结果登记为 `candidate`。只有完成以下检查后，
才能调用唯一准入入口：

```powershell
python scripts/runtime/accept_result.py runs/<run_id> --result-id <result_id> --paper-allowed
```

- 源脚本和输出文件存在且能复现；
- 指标定义与题意一致；
- 约束、单位和数据范围通过；
- 结论没有超出实验支持；
- 非 baseline 结果引用同题已接受且可复验的 baseline。

Codex 不得直接把 `status` 改成 `accepted`。准入脚本会复验执行记录 Schema、退出码、当前
输入/输出哈希、全部预期输出、非空指标、单位、强约束、验证和基线。结果只用
`claim_refs` 关联可能相关的主张，不保存“创新已成立”的判断；旧候选中的
`innovation_claims` 仅兼容读取并转换为引用。primary 可以在第三轮实验前 accepted。

创新主张必须由 `scripts/runtime/evaluate_claims.py` 独立评估。缺少路线要求的 robustness 或
ablation 证据时状态必须为 `inconclusive`；第三轮结果接受后再使用 `--refresh` 更新评估。
主张被 rejected 只限制论文贡献表述，不得撤销事实正确的 accepted result，也不得改写其
sealed result。

按 `schemas/result_registry.schema.json` 更新 `results/result_registry.json`。只有
`accepted` 且 `paper_allowed=true` 的记录可交给论文 Skill。

## 阶段交接

每个子问题接受结果后：

1. 更新 `state.json` 的该问题循环状态和产物路径；
2. 执行状态校验；
3. 立即调用 `$mathmodel-paper` 写该问题章节；
4. 再继续下一个子问题。

全部子问题完成后，把状态设为 `RESULTS_ACCEPTED`。不要在本 Skill 中集中写整篇论文。
