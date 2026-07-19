---
name: mathmodel-paper
description: 从 result_registry.json 中已接受且允许写入论文的真实结果增量撰写数学建模论文。用于每个子问题结果确认后的章节写作，以及全部实验完成后的摘要、结论和全文组装。
---

# 证据驱动的增量论文写作

只使用已注册、已接受的结果写作，不得从聊天记忆或未运行的代码猜测数值。

## 前置检查

1. 完整读取 `skills/5writing/SKILL.md`，沿用比赛模板、排版和编译要求。
2. 读取 `state.json`、`brief/ROUTE_LOCK.json`、数学规格和
   `results/result_registry.json`。
3. 过滤出 `status=accepted` 且 `paper_allowed=true` 的结果；其他记录不得进入正文、
   摘要、图表结论或贡献声明。

## 增量写作

某个子问题结果一经接受，立即写或更新对应章节，至少包含问题分析、模型推导、求解方法、
基线比较、主结果、稳健性/消融、图表解释、局限和逐问回答。每个关键数值都能依次追溯到
`result_id`、`execution_record_id`、执行清单、当前输入哈希和当前输出哈希。

把章节写入 `paper/sections/`，并在 `state.json` 记录已完成章节。不要等所有实验结束后才
突击写各问内容。

## 全文组装

只有状态达到 `RESULTS_ACCEPTED` 后，才统一写摘要、结论、优缺点和推广。摘要必须包含真实
核心数值；创新只能写入 `keep` 且有基线/消融证据的主张。按用户已锁定的比赛、语言和排版
引擎组装并编译论文。

生成草稿后把状态设为 `PAPER_DRAFTED`，然后交给 `$mathmodel-review`。本 Skill 不执行多轮
审稿，也不把论文直接标记为最终提交稿。
