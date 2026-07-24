---
name: mathmodel-workflow
description: 以 Capability-First v3 完成整道数学建模赛题的分析、求解、真实实验、论文和三轮独立审核闭环。仅在用户明确要求完整赛题交付时使用；局部分析、调试或改写论文不得隐式启动。
---

# Capability-First v3 数学建模工作流

目标是提升解题、实验和论文质量，而不是让模型维护审核平台。先理解数学结构和可执行路线；脚本自动保存最小可复验证据。

1. 创建运行：

   ```powershell
   python scripts/codex/init_run.py <problem_path> --workflow capability-first-v3 --run-id <run-id>
   ```

   只在用户要求整题、真实实验和完整论文时使用。恢复时只读当前状态和当前阶段产物；`blocked` 必须有失败证据与最小恢复条件，才回到分析、路由或实验。
2. 正式题面完成初步分析后、进入能力路由前，创建 `objective-semantics` 冻结包，并用一个全新 Codex 对话只读题面审查逐问目标。它必须枚举仍合理的目标口径、单位和聚合语义，特别区分逐实体求和、至少一个成立的并集、全部同时成立的交集和多目标；不得联网或查公开同题答案。歧义未由题面消除时，记录用户裁决或显式建模假设，不能让两个共享同一错误公式的实现互相背书。
3. 连续交付：

   | 阶段 | 责任 | 主要产物 |
   | --- | --- | --- |
   | `analysis` | `$mathmodel-solve` 做结构分析、推导和路线比较 | 建模报告 |
   | `capability_route` | 独立目标语义预审通过后，`$mathmodel-capability-router` 按题型选择并调用匹配的主动 Skill、工具和本地知识 | 目标语义结论、路由与消费收据 |
   | `experiment` | `$mathmodel-experiment` 真实编码、运行和验证 | 结果与实验报告 |
   | `scientific_review` | 1. 新对话用 `$mathmodel-red-team` 自由攻击模型与搜索；2. 独立覆盖提取；3. 对缺失高风险方向专项追问 | 科学红队报告与逐问裁决 |
   | `visualization` | `$mathmodel-visual` 生成真实的模型/求解证据图，并选择模板 | 图表与模板清单 |
   | `paper` | `$mathmodel-paper` 实际调用 `$research-writing-skill` 建立论证提纲、写作并编译 | `paper/argument_outline.md`、`paper/final.pdf` |
   | `paper_review` | 另一新对话只读匿名 PDF 盲审 | PDF 盲审报告 |
   | `verify` | `$mathmodel-final-check` 复验提交产物 | 机械 QA |
   | `final_review` | 第三个新审核对话只读最终交付包综合审核 | 最终交付审核报告 |

4. 目标语义预审和后续三轮审核必须使用四个互不相同、也不同于求解任务的新 Codex 任务。协调任务必须实际调用 Codex 的 `list_projects`、`create_thread` 和 `wait_threads`：用当前项目的 local 环境新建任务，只传绝对冻结包路径、报告输出路径和审核职责；使用 `create_thread` 返回的真实 `threadId` 导入结论。不得用同一任务自审，不得用 `fork_thread` 继承求解历史，不得自填或伪造审核任务 ID。若当前环境不能新建 Codex 任务，生产流程必须停在相应边界。
5. 审核任务只读对应冻结包，不访问网络、公开同题答案、历史 run、求解上下文或前轮结论，也不能修改论文、代码、结果、图表或提交表。它只写指定的目标语义评估或 `review/*.md` 报告。协调任务收到问题后回到生产阶段修复、重编译并重建包；每次复审仍要新建 Codex 任务。
6. 主对话优先写题意、变量单位、假设、核心推导、路线比较、probe、结果含义和失败边界。能力路由只填写五项决定：题型、实际能力、独立验证、工具链、本地知识；空间视觉结论仅在相关时补充。哈希、来源、命令和收据由运行时生成。
7. 图表完成后、进入 `paper` 前选择并实例化模板：

   ```powershell
   python scripts/paper/select_template.py runs/<run-id> `
     --language zh --engine auto `
     --reason "比赛和语言匹配，优先 LaTeX。" --materialize
   ```

   `auto` 优先 LaTeX；Typst 仅为用户显式选择或 LaTeX 不可用时的有记录回退。未知赛事不得静默用 `default`。
8. 任何审核发现问题都回到 `analysis`、`experiment` 或 `paper` 修复；论文必须直接收录完整 Python/MATLAB 源码文本，不能只列路径；启用 MATLAB 的高风险几何/优化题还必须有 `.m` 脚本生成的证明/验证图及正文解释。论文相关修改后重新编译，并重新执行受影响的盲审、机械 QA 和最终交付审核；审查后只允许一次集中修订，再次不通过即停止并保留失败证据。正常退出、保住 baseline、空图或模板文本都不等于解题成功。

详细的搜索边界、收据格式和防伪规则只在实际需要时查阅 `docs/CODEX_WORKFLOW.md`，不要把它逐项抄进主对话。
